# CaseClosed API詳細設計書

Version: 0.3  
作成日: 2026-05-22  
対象: 個人用案件管理Webアプリ CaseClosed  
関連文書: `CaseClosed_Overview_Design_v0.4.md`, `CaseClosed_Detailed_Design_v0.4.md`, `CaseClosed_DB_Design_v0.3.md`

---

## 0. 本書の位置づけ

本書は、CaseClosed のAPI詳細設計書である。

概要設計・詳細設計・DB詳細設計で定義した概念を、Web UI、Worker、Single DB Writer、Audit Log Writer、External Operation が利用するAPIとして具体化する。

本書は以下を目的とする。

- 画面実装者が必要なAPIを把握できること
- DB更新がSingle DB Writerを経由する原則を崩さないこと
- 外部副作用を二重実行しないこと
- ユーザー操作由来の状態とLLM/System由来の状態を混同しないこと
- 必要なボタン・操作に対応するAPIを欠落させないこと

本書はOpenAPI定義を完全固定するものではない。実装時には型定義、JSON Schema、バリデーション、認可チェック、エラーコードを追加・調整してよい。

---

# 1. API設計基本方針

## 1.1 基本原則

1. API名は英語で統一する。
2. Read API は原則としてSQLiteを直接読む。
3. 業務DB更新は原則として `write_requests` を作成し、Single DB Writer が反映する。
4. Audit Log は Audit Log Writer へ送る。
5. 外部副作用は `external_operations` 経由で実行する。
6. 単純な属性編集は `PATCH` を使う。
7. 業務上意味を持つ操作は `POST action` を使う。
8. 物理削除は通常APIからは提供しない。
9. 軽量な操作は `optimistic_state` を返してUIに即時反映させる。
10. 競合時はユーザー値を守る。
11. LLM/System由来のAPI・Jobは `user_*` を上書きしてはならない。

## 1.2 APIの種類

```text
Read API:
  画面表示・検索・詳細取得

Command API:
  ユーザー操作をWrite Request / Job / External Operationへ変換

Job Control API:
  Job状態の確認、再実行、停止、保守画面用

Maintenance API:
  証明書、設定、バックアップ、ログ閲覧など
```

## 1.3 更新経路

### 通常DB更新

```text
Browser UI
  -> Web/API Process
  -> write_requests INSERT
  -> Single DB Writer
  -> business tables UPDATE/INSERT
```

### LLM処理

```text
Browser UI or System Trigger
  -> jobs INSERT
  -> Orchestrator
  -> LLM Worker
  -> llm_runs INSERT
  -> write_requests INSERT
  -> Single DB Writer
```

### Gmail送信 / Gmailスター / Calendar作成

```text
Browser UI
  -> Web/API Process
  -> external_operations INSERT
  -> External Operation Worker
  -> Gmail / Calendar API
  -> write_requests INSERT for local reflection
```

### Audit Log

```text
Browser UI
  -> Web/API Process
  -> Audit Log Writer
  -> audit_logs / audit_exposure_batches / audit_exposure_items
```

---

# 2. 共通仕様

## 2.1 Base URL

初期実装では相対URLでよい。

```text
/api/v1
```

## 2.2 認証

APIはログイン済みセッションを前提とする。

アクセス条件:

```text
Tailscale到達
+ mTLSクライアント証明書検証済み
+ アプリ内パスワードログイン済みセッション
```

API側では、セッションから以下を取得できる前提とする。

```text
session_id
client_certificate_id
device_name
user_agent
remote_ip
```

## 2.3 Content-Type

```http
Content-Type: application/json
Accept: application/json
```

ファイルアップロードのみ `multipart/form-data` を許可する。

## 2.4 共通レスポンス形式

### 成功

```json
{
  "ok": true,
  "data": {},
  "meta": {}
}
```

### Command成功

```json
{
  "ok": true,
  "write_request_id": "wr_...",
  "job_id": null,
  "external_operation_id": null,
  "optimistic_state": {},
  "message": "accepted"
}
```

### エラー

```json
{
  "ok": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid request",
    "details": {}
  }
}
```

## 2.5 共通エラーコード

```text
UNAUTHORIZED
FORBIDDEN
SESSION_EXPIRED
VALIDATION_ERROR
NOT_FOUND
CONFLICT
BASE_VERSION_CONFLICT
WRITE_REQUEST_FAILED
JOB_FAILED
EXTERNAL_OPERATION_UNKNOWN
EXTERNAL_OPERATION_FAILED
RATE_LIMITED
COST_LIMIT_EXCEEDED
MAINTENANCE_MODE
```

## 2.6 Pagination

一覧系APIは cursor pagination を基本とする。

Request:

```text
?limit=50&cursor=...
```

Response meta:

```json
{
  "next_cursor": "...",
  "has_more": true
}
```

## 2.7 Filtering / Sorting

一覧APIでは必要に応じて以下を使う。

```text
q=keyword
status=...
case_id=...
contact_id=...
importance=...
from=...
to=...
created_from=...
created_to=...
sort=updated_at_desc
```

複雑な検索は初期実装では最小限でよい。

## 2.8 base_version

更新系APIでは、可能な限り対象レコードの `base_version` を受け取る。

```json
{
  "base_version": 7
}
```

Single DB Writer は現在versionと比較し、競合時は安全側に倒す。

## 2.9 optimistic_state

軽量操作ではAPIレスポンスに `optimistic_state` を含める。

対象例:

- Mail処理済み化
- Mail重要度変更
- Case関連メール追加/解除
- Task完了
- Taskキャンセル
- Contact登録
- Draft保存

仕様:

- `write_request_id` を必ず返す。
- UIは `optimistic_state` を即時反映する。
- 30秒以内に実DB状態へ再同期する。
- 30秒を超える場合は「反映待ち」と表示する。
- DB反映失敗時は失敗表示を出す。
- 複数タブ操作では最新DB状態を優先し、古い optimistic state は破棄する。

---

# 3. Audit API方針

## 3.1 自動監査ログ

以下のRead APIは、API側で監査ログを自動生成する。

- メール一覧表示
- メール本文表示
- ファイルカード表示
- ファイル詳細表示
- ファイルダウンロード
- 監査ログ閲覧
- 設定変更画面閲覧

## 3.2 メール一覧表示ログ

メール一覧APIは、表示されたメールID集合を `audit_exposure_batches` / `audit_exposure_items` に記録する。

記録単位:

```text
exposure_batch:
  screen_name
  query_json
  displayed_at
  session_id

exposure_items:
  batch_id
  target_type = mail
  target_id = message_id
```

## 3.3 ファイルカード表示ログ

Case詳細やFile一覧でファイルカードが表示された場合も exposure batch として記録する。

## 3.4 Command APIログ

Command APIは以下を監査ログに記録する。

- 操作種別
- 対象種別
- 対象ID
- before/afterの要約
- write_request_id / job_id / external_operation_id
- session_id

---

# 4. Auth / Session API

## 4.1 ログイン

```http
POST /api/v1/auth/login
```

Request:

```json
{
  "password": "..."
}
```

Response:

```json
{
  "ok": true,
  "data": {
    "session_expires_at": "2026-05-23T01:00:00Z"
  }
}
```

仕様:

- パスワード形式。
- 失敗5回でロックする。
- ロック解除はサーバーへの物理アクセスを前提とする保守操作。
- ログインから24時間で自動ログアウトする。
- セッション有効期限は延長しない。

## 4.2 ログアウト

```http
POST /api/v1/auth/logout
```

## 4.3 セッション確認

```http
GET /api/v1/auth/session
```

Response:

```json
{
  "ok": true,
  "data": {
    "authenticated": true,
    "session_expires_at": "...",
    "client_certificate_id": "cert_...",
    "device_name": "iPhone"
  }
}
```

---

# 5. Dashboard API

## 5.1 トップ画面取得

```http
GET /api/v1/dashboard
```

Response data:

```json
{
  "today_events": [],
  "important_mails": [],
  "pending_contacts": [],
  "active_cases": [],
  "due_tasks": [],
  "system_alerts": []
}
```

目的:

- トップ画面の初期表示。
- 詳細画面用の完全情報ではなく、カード表示用サマリを返す。

---

# 6. Case API

## 6.1 Case一覧

```http
GET /api/v1/cases
```

Query:

```text
status=open|closed|archived|all
ball_status=user|other|date_wait|stalled|none
tag=...
q=...
limit=50
cursor=...
```

Response item:

```json
{
  "id": "case_...",
  "name": "情報リテラシー演習",
  "progress_status": "in_progress",
  "ball_status": "user",
  "closed_at": null,
  "archived_at": null,
  "is_system_case": false,
  "tags": [],
  "mail_count": 12,
  "open_task_count": 3,
  "next_task_due_at": "..."
}
```

## 6.2 Case詳細

```http
GET /api/v1/cases/{case_id}
```

Response data:

```json
{
  "case": {},
  "tags": [],
  "context_latest": {},
  "related_mails": [],
  "tasks": [],
  "calendar_events": [],
  "contacts": [],
  "files": [],
  "recent_events": []
}
```

仕様:

- Caseが持つ関連メール集合を `related_mails` として返す。
- `primary` と `copy` を区別して返す。
- ファイルカード表示を含む場合はファイル exposure log を記録する。

## 6.3 Case作成

```http
POST /api/v1/cases
```

Request:

```json
{
  "name": "...",
  "description": "...",
  "tags": ["..."],
  "ball_status": "user"
}
```

処理:

- Write Requestを作成する。
- `progress_status` 初期値は `not_started`。
- 作成後の optimistic_state を返す。

## 6.4 Case更新

```http
PATCH /api/v1/cases/{case_id}
```

Request:

```json
{
  "base_version": 3,
  "name": "...",
  "description": "...",
  "progress_status": "in_progress",
  "ball_status": "other",
  "tags": ["授業", "2026"]
}
```

禁止:

- `closed_at` を直接PATCHしない。
- `archived_at` を直接PATCHしない。
- system case の削除・アーカイブ相当操作。

## 6.5 CaseをClosedにする

```http
POST /api/v1/cases/{case_id}/close
```

Request:

```json
{
  "base_version": 5,
  "note": "年度作業完了"
}
```

仕様:

- 未完了Taskが残っている場合は `CONFLICT`。
- `completed` / `canceled` TaskのみならClosed可能。
- `closed_at` を設定する。
- system case のうち Inbox / システムメンテナンスはClosed不可。

## 6.6 Caseを再オープンする

```http
POST /api/v1/cases/{case_id}/reopen
```

仕様:

- `closed_at` をNULLに戻す。
- `progress_status` は原則 `in_progress`。
- 監査ログに記録する。

## 6.7 Caseをアーカイブする

```http
POST /api/v1/cases/{case_id}/archive
```

仕様:

- `archived_at` を設定する。
- system case はアーカイブ不可。
- Closedでなくてもアーカイブ可能にするかは実装時設定で制御してよいが、初期値はClosed済みのみ許可を推奨する。

## 6.8 Caseのアーカイブ解除

```http
POST /api/v1/cases/{case_id}/unarchive
```

## 6.9 Case関連メール一覧

```http
GET /api/v1/cases/{case_id}/mails
```

Query:

```text
link_role=primary|copy|all
processed=0|1|all
importance=...
limit=50
cursor=...
```

## 6.10 Caseへメールを追加する

```http
POST /api/v1/cases/{case_id}/mails
```

Request:

```json
{
  "message_id": "mail_...",
  "link_role": "primary|copy",
  "base_version": 4
}
```

仕様:

- UI表現は「このCaseにメールを入れる」「別Caseにコピー」。
- DBは `case_mail_links` を更新する。
- `primary` は1メールにつき1件のみ。
- 既存primaryがある状態で別Caseをprimaryにする場合は、既存primaryを外すWrite Requestを同一transactionで行う。
- `copy` は複数Caseに許可する。

## 6.11 Caseからメールを外す

```http
DELETE /api/v1/cases/{case_id}/mails/{message_id}
```

仕様:

- 実体メールは削除しない。
- `case_mail_links` のみ論理削除または削除する。
- primaryを外した結果、メールがCaseなしになることは許容する。

---

# 7. Mail / Gmail API

## 7.1 メール一覧

```http
GET /api/v1/mails
```

Query:

```text
folder=inbox|sent|all
processed=0|1|all
importance=Pinned|High|Middle|Low|Skip|Pending|all
case_id=...
contact_status=pending|resolved|all
q=...
date_from=...
date_to=...
limit=50
cursor=...
```

Response item:

```json
{
  "id": "mail_...",
  "gmail_message_id": "...",
  "gmail_thread_id": "...",
  "subject": "...",
  "from_address": "...",
  "from_contact_id": null,
  "received_at": "...",
  "processed_status": "unprocessed",
  "effective_importance": "Pending",
  "initial_is_starred": false,
  "external_importance": null,
  "summary_status": "not_started",
  "primary_case": null,
  "copy_cases": [],
  "has_attachments": true
}
```

監査ログ:

- 表示されたメールIDを exposure batch として記録する。

## 7.2 メール詳細

```http
GET /api/v1/mails/{message_id}
```

Response data:

```json
{
  "message": {},
  "thread_messages": [],
  "user_state": {},
  "auto_state": {},
  "summary": {},
  "case_links": [],
  "attachments": [],
  "drafts": [],
  "available_actions": []
}
```

監査ログ:

- メール本文表示を記録する。

## 7.3 Gmail同期開始

```http
POST /api/v1/gmail/sync
```

Request:

```json
{
  "mode": "initial_7days|delta|sent_recent"
}
```

処理:

- Gmail Sync Jobを作成する。
- 初回は過去7日。
- 既に読み込んだメールはGmailスター状態を再監視しない。
- 既存メールのスター解除はアプリ側に反映しない。

## 7.4 メール重要度変更

```http
POST /api/v1/mails/{message_id}/importance
```

Request:

```json
{
  "base_version": 3,
  "importance": "Pinned|High|Middle|Low|Skip"
}
```

仕様:

- ユーザー操作なので `mail_user_state.user_importance` を更新する。
- `High` にした場合はGmailスター付与 `external_operation` を作成する。
- `Pinned` はGmailスターと無関係。
- `Skip` はProcessedとは別扱い。
- 手動でHigh/Middleへ変更した場合はCase判定Jobを発火する。

## 7.5 メール処理済み化

```http
POST /api/v1/mails/{message_id}/process
```

Request:

```json
{
  "base_version": 4,
  "reason": "manual|replied|task_created|calendar_created|ignored"
}
```

仕様:

- `processed_status = processed` を設定する。
- 要約閲覧、本文閲覧、返信草案作成、Caseへの追加、Contact確認だけでは処理済みにしない。

## 7.6 メール未処理へ戻す

```http
POST /api/v1/mails/{message_id}/unprocess
```

## 7.7 メールから新規Case候補作成

```http
POST /api/v1/mails/{message_id}/suggest-case
```

仕様:

- LLMまたは簡易抽出により新規Case候補を作る。
- 即時Case作成はしない。
- 採用時は `POST /cases` と `POST /cases/{case_id}/mails` を組み合わせるか、専用APIを使う。

## 7.8 メールからTask作成

```http
POST /api/v1/mails/{message_id}/create-task
```

Request:

```json
{
  "case_id": "case_...",
  "title": "返信する",
  "description": "...",
  "due_at": "...",
  "base_version": 2
}
```

仕様:

- `case_id` が未指定でメールにprimary Caseがなければ Inbox Case 配下に作成する。
- Task作成後、メールは原則として処理済みにする。
- 理由は、詳細設計上「タスク化」はメール処理完了操作であり、運用上もこの頻度が高いと想定するためである。
- 将来、必要が明確になった場合に限り、「Task化しても未処理に残す」オプションを追加検討する。

## 7.9 メールから予定候補抽出

```http
POST /api/v1/mails/{message_id}/extract-calendar-candidates
```

処理:

- LLM Jobを作成する。
- 候補は正式予定ではない。

## 7.10 メールから予定作成

```http
POST /api/v1/mails/{message_id}/create-calendar-event
```

Request:

```json
{
  "case_id": "case_...",
  "task_id": null,
  "title": "...",
  "start_at": "...",
  "end_at": "...",
  "location": "...",
  "description": "..."
}
```

処理:

- Google Calendar作成 `external_operation` を作成する。
- 成功後、`calendar_event_links` を作成するWrite Requestを発行する。
- 成功後、メールを処理済みにする。

## 7.11 フィルタ作成支援

```http
POST /api/v1/mails/{message_id}/suggest-rule
```

用途:

- この件名パターンをSkipする
- From + Subject 条件の複合Skipを作る
- 特定キーワードをHigh/Middleにする

注意:

- From単独Skipルールは作成しない。
- Fromのみで今後Skipしたい場合はContactを作成し、Contactを `skipped` にする。

---

# 8. Contact API

## 8.1 Contact一覧

```http
GET /api/v1/contacts
```

Query:

```text
status=active|skipped|archived|all
q=...
tag=...
limit=50
cursor=...
```

## 8.2 Contact詳細

```http
GET /api/v1/contacts/{contact_id}
```

## 8.3 未解決From一覧

```http
GET /api/v1/contacts/unresolved-from-addresses
```

Response item:

```json
{
  "email_address": "...",
  "message_count": 3,
  "latest_message_id": "mail_...",
  "latest_subject": "...",
  "suggestion_status": "not_started|running|succeeded|failed",
  "suggestion": {}
}
```

仕様:

- Fromに出現したContact未登録メールアドレスを表示する。
- To/Cc/Bccの未知アドレスはPending対象ではない。

## 8.4 Contact登録画面の自動Fill生成

```http
POST /api/v1/contacts/unresolved-from-addresses/{encoded_email}/generate-prefill
```

Request:

```json
{
  "message_id": "mail_..."
}
```

処理:

- `contact_registration_prefill` LLM Jobを作成する。
- Pending中でもこのLLMだけは実行可能。
- メール本文、署名、件名、Fromアドレスから候補を生成する。

Response:

```json
{
  "ok": true,
  "job_id": "job_..."
}
```

## 8.5 Contact作成

```http
POST /api/v1/contacts
```

Request:

```json
{
  "display_name": "...",
  "organization": "...",
  "role": "...",
  "memo": "...",
  "status": "active|skipped",
  "tags": ["..."],
  "email_addresses": [
    {
      "email_address": "...",
      "is_primary": true
    }
  ],
  "source_suggestion_id": "suggest_..."
}
```

仕様:

- Contact作成後、該当FromのPendingメールについて重要度判定Jobを再開する。
- `status = skipped` で作成された場合、該当メールは重要度判定前にSkip扱いにする。

## 8.6 Contact更新

```http
PATCH /api/v1/contacts/{contact_id}
```

## 8.7 ContactをSkipにする

```http
POST /api/v1/contacts/{contact_id}/skip
```

仕様:

- Contact全体を `skipped` にする。
- そのContactに紐づくFromからのメールはSkip扱い。
- Email Address単独Skipは存在しない。

## 8.8 ContactをActiveに戻す

```http
POST /api/v1/contacts/{contact_id}/activate
```

## 8.9 Contactにメールアドレス追加

```http
POST /api/v1/contacts/{contact_id}/email-addresses
```

Request:

```json
{
  "email_address": "...",
  "is_primary": false
}
```

## 8.10 Contact Merge

```http
POST /api/v1/contacts/{contact_id}/merge
```

Request:

```json
{
  "merge_from_contact_id": "contact_...",
  "merge_policy": {
    "display_name": "keep_target",
    "tags": "union",
    "email_addresses": "union"
  }
}
```

仕様:

- マージ履歴を保存する。
- メールアドレス、タグ、関連Caseを統合する。

---

# 9. Task API

## 9.1 Task一覧

```http
GET /api/v1/tasks
```

Query:

```text
case_id=...
status=not_started|in_progress|completed|canceled|open|all
due=overdue|today|week|none|all
include_deleted=0|1
limit=50
cursor=...
```

## 9.2 Task詳細

```http
GET /api/v1/tasks/{task_id}
```

## 9.3 Task作成

```http
POST /api/v1/tasks
```

Request:

```json
{
  "case_id": "case_...",
  "parent_task_id": null,
  "title": "...",
  "description": "...",
  "due_at": "...",
  "estimate_minutes": 60,
  "source": "user"
}
```

仕様:

- Taskは必ず1つのCaseに属する。
- Case未指定で作るUIは原則用意しない。
- メール起点でCase未定の場合はInbox Case配下に作る。

## 9.4 Task更新

```http
PATCH /api/v1/tasks/{task_id}
```

Request:

```json
{
  "base_version": 2,
  "title": "...",
  "description": "...",
  "status": "in_progress",
  "due_at": "...",
  "estimate_minutes": 90
}
```

注意:

- `completed` への変更は `POST /complete` を推奨する。
- `canceled` への変更は `POST /cancel` を推奨する。

## 9.5 Task完了

```http
POST /api/v1/tasks/{task_id}/complete
```

仕様:

- 未完了下位Taskがある場合は完了不可。
- `completed_at` を設定する。
- optimistic_state を返す。

## 9.6 Taskキャンセル

```http
POST /api/v1/tasks/{task_id}/cancel
```

Request:

```json
{
  "reason": "不要になった"
}
```

仕様:

- `status = canceled`。
- 下位Taskの扱いはユーザー確認を推奨する。

## 9.7 Task論理削除

```http
POST /api/v1/tasks/{task_id}/delete
```

Request:

```json
{
  "reason": "誤作成"
}
```

仕様:

- `deleted_at` を設定する。
- 物理削除しない。
- audit/eventから参照されるTaskを破壊しない。

## 9.8 Task復元

```http
POST /api/v1/tasks/{task_id}/restore
```

## 9.9 サブタスク候補生成

```http
POST /api/v1/tasks/{task_id}/suggest-subtasks
```

処理:

- LLM Jobを作成する。
- 結果は `task_suggestions`。
- 正式Taskにはしない。

## 9.10 サブタスク候補採用

```http
POST /api/v1/task-suggestions/{suggestion_id}/accept
```

仕様:

- 採用時に正式Taskを作成する。
- 編集後採用を許可する。

## 9.11 サブタスク候補破棄

```http
POST /api/v1/task-suggestions/{suggestion_id}/reject
```

---

# 10. Draft / Mail Send API

## 10.1 返信草案生成

```http
POST /api/v1/mails/{message_id}/draft-reply
```

Request:

```json
{
  "additional_prompt": "簡潔に、今後の対応を中心に",
  "case_id": "case_..."
}
```

仕様:

- LLM Jobを作成する。
- Gmail Draftではなくアプリ内draftを作成する。
- 既存草案がある場合、まず既存草案を返すか、再生成確認を挟む。

## 10.2 新規メール草案作成

```http
POST /api/v1/drafts
```

Request:

```json
{
  "draft_type": "new_mail",
  "case_id": "case_...",
  "to": [],
  "cc": [],
  "bcc": [],
  "subject": "...",
  "body": "..."
}
```

## 10.3 草案詳細

```http
GET /api/v1/drafts/{draft_id}
```

## 10.4 草案更新

```http
PATCH /api/v1/drafts/{draft_id}
```

## 10.5 草案送信

```http
POST /api/v1/drafts/{draft_id}/send
```

Request:

```json
{
  "base_version": 6,
  "confirm": true
}
```

仕様:

- 重要操作確認の対象。
- Gmail送信 `external_operation` を作成する。
- `idempotency_key` 必須。
- `unknown` になった場合は自動再実行しない。
- 送信成功後、送信済みメールのローカル反映Write Requestを作成する。
- 返信元メールを処理済みにする。

## 10.6 草案削除

```http
POST /api/v1/drafts/{draft_id}/delete
```

仕様:

- 論理削除。

---

# 11. Calendar API

## 11.1 今日・今週の予定取得

```http
GET /api/v1/calendar/events
```

Query:

```text
from=2026-05-22T00:00:00+09:00
to=2026-05-29T00:00:00+09:00
case_id=...
```

仕様:

- Google Calendarから直接取得するか、同期済みキャッシュから返すかは実装時に選択する。
- 予定の正本はGoogle Calendar。

## 11.2 作業ブロック候補取得

```http
POST /api/v1/calendar/suggest-work-blocks
```

Request:

```json
{
  "task_id": "task_...",
  "duration_minutes": 60,
  "search_from": "...",
  "search_to": "..."
}
```

## 11.3 Taskを作業ブロックとして登録

```http
POST /api/v1/tasks/{task_id}/schedule-work-block
```

Request:

```json
{
  "title": "案件名：タスク名",
  "start_at": "...",
  "end_at": "...",
  "description": "..."
}
```

処理:

- Google Calendar作成 `external_operation`。
- 成功後 `task_work_blocks` / `calendar_event_links` を更新。
- `scheduled_minutes` に反映。

## 11.4 Calendar予定変更

```http
PATCH /api/v1/calendar/events/{calendar_event_link_id}
```

仕様:

- Google Calendar変更 `external_operation`。
- 成功後ローカルリンク情報を反映。

## 11.5 Calendar予定削除/解除

```http
POST /api/v1/calendar/events/{calendar_event_link_id}/cancel
```

仕様:

- Google Calendar側の予定削除またはCaseClosedとのリンク解除を区別する必要がある。
- 初期実装では「Google Calendar予定を削除する」は重要操作確認対象。

---

# 12. Follow-up Watch API

## 12.1 Follow-up Watch作成

```http
POST /api/v1/follow-up-watches
```

Request:

```json
{
  "case_id": "case_...",
  "message_id": "mail_...",
  "gmail_thread_id": "...",
  "wait_until": "...",
  "note": "1週間返事がなければリマインド"
}
```

仕様:

- すべての送信メールに自動では作らない。
- ユーザー明示、またはLLM候補をユーザー承認した場合のみ作成。

## 12.2 Follow-up Watch解除

```http
POST /api/v1/follow-up-watches/{watch_id}/close
```

## 12.3 リマインドTask生成

```http
POST /api/v1/follow-up-watches/{watch_id}/create-reminder-task
```

仕様:

- Case配下に「リマインドを送る」Taskを作成する。
- Watch状態は `reminder_task_created`。

---

# 13. File / Storage API

## 13.1 Caseファイル一覧

```http
GET /api/v1/cases/{case_id}/files
```

仕様:

- ファイルカード表示ログを記録する。
- Mail添付由来ファイルは、添付元メールのCase表示に連動する。

## 13.2 ファイルアップロード

```http
POST /api/v1/cases/{case_id}/files
Content-Type: multipart/form-data
```

Fields:

```text
file
origin=upload
memo
llm_policy=allowed|confirm_required|forbidden
```

処理:

- storage objectを作成する。
- files / file_links をWrite Requestで登録する。

## 13.3 ファイル詳細

```http
GET /api/v1/files/{file_id}
```

## 13.4 ファイルダウンロード

```http
GET /api/v1/files/{file_id}/download
```

監査ログ:

- ファイルダウンロードを記録する。

## 13.5 ファイルをゴミ箱へ移動

```http
POST /api/v1/files/{file_id}/trash
```

## 13.6 ファイル復元

```http
POST /api/v1/files/{file_id}/restore
```

## 13.7 ファイル物理削除

```http
POST /api/v1/files/{file_id}/purge
```

仕様:

- 重要操作確認対象。
- 保守・運用画面からのみ利用する。
- 物理削除後もDBメタ情報は残す。

## 13.8 LLM Policy変更

```http
POST /api/v1/files/{file_id}/llm-policy
```

Request:

```json
{
  "llm_policy": "allowed|confirm_required|forbidden",
  "confirm": true
}
```

仕様:

- `forbidden` からの変更は重要操作確認対象。

## 13.9 ファイル要約生成

```http
POST /api/v1/files/{file_id}/summarize
```

仕様:

- `forbidden` は不可。
- `confirm_required` はユーザー確認後のみ。
- LLM入力ログには全文を保存しない。

---

# 14. LLM API

## 14.1 LLM Run一覧

```http
GET /api/v1/llm/runs
```

Query:

```text
function_type=...
status=...
case_id=...
mail_id=...
limit=50
cursor=...
```

## 14.2 LLM Run詳細

```http
GET /api/v1/llm/runs/{llm_run_id}
```

Response:

```json
{
  "id": "llm_...",
  "function_type": "mail_summary",
  "model_name": "...",
  "prompt_version_id": "...",
  "input_hash": "...",
  "input_source_json": {},
  "input_diagnostic_json": {},
  "applied_instruction_rule_ids_json": [],
  "output_json": {},
  "status": "succeeded",
  "error_type": null,
  "retry_count": 0,
  "estimated_cost": 0.02
}
```

## 14.3 手動LLM再実行

```http
POST /api/v1/llm/runs/{llm_run_id}/rerun
```

Request:

```json
{
  "additional_prompt": "この点を強調してください"
}
```

仕様:

- 既存結果を入力に含める。
- 追加プロンプトを反映する。
- UI上の既存結果は新結果で置き換える。
- `llm_runs` には履歴を残す。

## 14.4 メール要約生成

```http
POST /api/v1/mails/{message_id}/summarize
```

仕様:

- 手動要約用。
- Lowでも手動なら実行可。
- Pending中は原則不可。ただしContact登録prefillは例外。

## 14.5 Case Context更新

```http
POST /api/v1/cases/{case_id}/update-context
```

## 14.6 Contact Context更新

```http
POST /api/v1/contacts/{contact_id}/update-context
```

## 14.7 Prompt Version一覧

```http
GET /api/v1/llm/prompt-versions
```

Query:

```text
function_type=...
is_active=1
```

## 14.8 Prompt Version詳細

```http
GET /api/v1/llm/prompt-versions/{prompt_version_id}
```

仕様:

- system/user/retry prompt templateを確認する。
- output_schema_jsonを確認する。
- LLM入力全文・過去実行入力全文は表示しない。

## 14.9 Prompt Version作成

```http
POST /api/v1/llm/prompt-versions
```

仕様:

- 既存versionを上書きしない。
- function_typeごとにversion_noを増やす。
- schema変更時も新versionを作成する。

## 14.10 Cost Limit超過時の挙動

LLM実行前にCost Limit超過が予測される場合、APIは以下を行う。

- LLM Jobを作成しない。
- システムメンテナンスCase配下にTaskを自動生成するWrite Requestを作成する。
- UIには `COST_LIMIT_EXCEEDED` を返す。

Response例:

```json
{
  "ok": false,
  "error": {
    "code": "COST_LIMIT_EXCEEDED",
    "message": "LLM cost limit would be exceeded. A maintenance task was created."
  },
  "write_request_id": "wr_..."
}
```

---

# 15. Rule API

## 15.1 重要度フィルタ一覧

```http
GET /api/v1/mail-importance-rules
```

## 15.2 重要度フィルタ作成

```http
POST /api/v1/mail-importance-rules
```

Request:

```json
{
  "name": "newsletter skip",
  "conditions": {
    "from_contains": "...",
    "subject_contains": "newsletter"
  },
  "output_importance": "Skip",
  "additional_llm_prompt": null,
  "priority": 100
}
```

仕様:

- From単独Skipは禁止。
- From条件を含むSkipは、Subject / Body / attachment / label 等との複合条件に限る。
- FromだけでSkipしたい場合はContact skippedを使う。

## 15.3 重要度フィルタ更新

```http
PATCH /api/v1/mail-importance-rules/{rule_id}
```

## 15.4 重要度フィルタ削除

```http
POST /api/v1/mail-importance-rules/{rule_id}/delete
```

論理削除。

## 15.5 Case候補ルール一覧

```http
GET /api/v1/case-candidate-rules
```

## 15.6 Case候補ルール作成

```http
POST /api/v1/case-candidate-rules
```

---

# 16. Job API

## 16.1 Job一覧

```http
GET /api/v1/jobs
```

Query:

```text
status=pending|running|succeeded|failed|canceled|stale|all
job_type=...
priority=...
limit=50
cursor=...
```

## 16.2 Job詳細

```http
GET /api/v1/jobs/{job_id}
```

## 16.3 Jobキャンセル

```http
POST /api/v1/jobs/{job_id}/cancel
```

仕様:

- pendingのみキャンセル可。
- runningはGraceful ShutdownまたはWorker制御に任せる。

## 16.4 Job再実行

```http
POST /api/v1/jobs/{job_id}/retry
```

仕様:

- failed jobのみ手動再実行可。
- stale running jobは保守画面から確認後に再実行可。
- 外部副作用を伴うJobは `external_operations` 状態を確認し、unknownなら自動再実行不可。

## 16.5 Write Request一覧

```http
GET /api/v1/write-requests
```

## 16.6 Write Request詳細

```http
GET /api/v1/write-requests/{write_request_id}
```

---

# 17. External Operation API

## 17.1 External Operation一覧

```http
GET /api/v1/external-operations
```

Query:

```text
status=pending|running|succeeded|failed|unknown|canceled|all
operation_type=gmail_send|gmail_star|calendar_create|calendar_update|google_tasks_export
limit=50
cursor=...
```

## 17.2 External Operation詳細

```http
GET /api/v1/external-operations/{operation_id}
```

## 17.3 External Operation手動解決

```http
POST /api/v1/external-operations/{operation_id}/resolve
```

Request:

```json
{
  "resolution": "mark_succeeded|mark_failed|mark_canceled",
  "external_id": "...",
  "note": "Gmail側で送信済みを確認"
}
```

仕様:

- `unknown` 状態は自動再実行しない。
- Gmail送信のunknownは、ユーザーがGmail側を確認して手動解決する。

## 17.4 External Operation再試行

```http
POST /api/v1/external-operations/{operation_id}/retry
```

仕様:

- `failed` のうち副作用が発生していないことが明確なもののみ。
- `unknown` は不可。
- `idempotency_key` を使う。

---

# 18. Audit / Log API

## 18.1 Audit Log一覧

```http
GET /api/v1/audit-logs
```

Query:

```text
from=...
to=...
action_type=...
target_type=...
case_id=...
contact_id=...
mail_id=...
file_id=...
session_id=...
error_only=0|1
limit=100
cursor=...
```

## 18.2 Audit Log詳細

```http
GET /api/v1/audit-logs/{audit_log_id}
```

## 18.3 Exposure Batch一覧

```http
GET /api/v1/audit-exposure-batches
```

## 18.4 Exposure Batch詳細

```http
GET /api/v1/audit-exposure-batches/{batch_id}
```

## 18.5 System Log一覧

```http
GET /api/v1/system-logs
```

## 18.6 Event Log一覧

```http
GET /api/v1/events
```

Query:

```text
case_id=...
target_type=...
target_id=...
limit=100
cursor=...
```

---

# 19. Certificate / Maintenance API

## 19.1 クライアント証明書一覧

```http
GET /api/v1/client-certificates
```

## 19.2 クライアント証明書発行

```http
POST /api/v1/client-certificates
```

Request:

```json
{
  "device_name": "iPad",
  "expires_at": "..."
}
```

仕様:

- 有効期限は原則6か月。
- 期限7日前にシステムメンテナンスCase配下へ更新Taskを作成する。

## 19.3 クライアント証明書失効

```http
POST /api/v1/client-certificates/{certificate_id}/revoke
```

仕様:

- 重要操作確認対象。
- 関連セッションを無効化する。

## 19.4 保守状態取得

```http
GET /api/v1/maintenance/status
```

Response:

```json
{
  "job_accepting": true,
  "running_jobs": 2,
  "pending_write_requests": 0,
  "external_unknown_count": 0,
  "backup_status": "not_configured"
}
```

## 19.5 Graceful Shutdown開始

```http
POST /api/v1/maintenance/graceful-shutdown
```

手順:

1. 新規Job受付停止
2. 実行中Job完了待ち
3. pending Write Request反映
4. Worker停止
5. DB Writer停止
6. サービス停止可能状態へ

## 19.6 Job受付再開

```http
POST /api/v1/maintenance/resume-jobs
```

---

# 20. Backup / Restore API

バックアップ・復旧は実装優先度を下げるが、API設計上の入口は定義しておく。

## 20.1 バックアップ一覧

```http
GET /api/v1/backups
```

## 20.2 バックアップ実行

```http
POST /api/v1/backups/run
```

Request:

```json
{
  "backup_type": "incremental|full",
  "confirm": true
}
```

仕様:

- backup jobを作成する。
- 外付けHDD/SSDを想定。
- 暗号化バックアップを前提とする。

## 20.3 復元計画作成

```http
POST /api/v1/backups/{backup_id}/prepare-restore
```

仕様:

- すぐ復元しない。
- 復元対象、影響、external_operations確認項目を表示する。

## 20.4 復元実行

```http
POST /api/v1/backups/{backup_id}/restore
```

仕様:

- 重要操作確認対象。
- 復元直後は外部API Jobを自動再開しない。
- `external_operations` の pending/running/unknown は手動確認対象。

---

# 21. Settings API

## 21.1 設定取得

```http
GET /api/v1/settings
```

## 21.2 設定更新

```http
PATCH /api/v1/settings
```

対象例:

```json
{
  "llm_cost_limit_daily": 5.0,
  "llm_cost_limit_monthly": 50.0,
  "default_follow_up_days": 7,
  "gmail_star_on_high": true,
  "worker_min": 1,
  "worker_max": 4
}
```

仕様:

- 設定変更は監査ログに記録する。
- セキュリティ・外部副作用に関わる設定は確認対象にする。
- LLM追加指示ルールはRule APIで管理する。
- Prompt VersionはLLM APIで管理する。

---

# 22. APIと画面ボタン対応

## 22.1 メール詳細画面

必須ボタンとAPI:

```text
返信草案                  POST /mails/{id}/draft-reply
送信                      POST /drafts/{id}/send
タスク化                  POST /mails/{id}/create-task
予定化                    POST /mails/{id}/create-calendar-event
予定候補抽出              POST /mails/{id}/extract-calendar-candidates
Caseへ入れる              POST /cases/{case_id}/mails
別Caseにコピー            POST /cases/{case_id}/mails link_role=copy
新規Case作成              POST /cases
Contact解決               POST /contacts
Contact自動Fill           POST /contacts/unresolved-from-addresses/{email}/generate-prefill
処理済み                  POST /mails/{id}/process
不要として処理済み        POST /mails/{id}/process reason=ignored
重要度変更                POST /mails/{id}/importance
フィルタ作成              POST /mail-importance-rules
Gmailで開く               Read link only / audit log
```

## 22.2 Case詳細画面

```text
Case編集                  PATCH /cases/{id}
Closedにする              POST /cases/{id}/close
再オープン                POST /cases/{id}/reopen
アーカイブ                POST /cases/{id}/archive
メール一覧                GET /cases/{id}/mails
Task作成                  POST /tasks
ファイルアップロード      POST /cases/{id}/files
Context更新               POST /cases/{id}/update-context
引継ぎログ生成            後続: POST /cases/{id}/handover-report
```

## 22.3 Task画面

```text
Task作成                  POST /tasks
Task編集                  PATCH /tasks/{id}
完了                      POST /tasks/{id}/complete
キャンセル                POST /tasks/{id}/cancel
削除                      POST /tasks/{id}/delete
復元                      POST /tasks/{id}/restore
サブタスク候補生成        POST /tasks/{id}/suggest-subtasks
作業ブロック化            POST /tasks/{id}/schedule-work-block
```

---

# 23. 初期実装優先API

MVPという概念は使わないが、実装順序上の初期優先APIを定義する。

## 23.1 最初に必要

```text
Auth:
  POST /auth/login
  POST /auth/logout
  GET /auth/session

Case:
  GET /cases
  GET /cases/{id}
  POST /cases
  PATCH /cases/{id}
  POST /cases/{id}/close
  POST /cases/{id}/reopen

Contact:
  GET /contacts
  POST /contacts
  GET /contacts/unresolved-from-addresses
  POST /contacts/unresolved-from-addresses/{email}/generate-prefill

Mail:
  GET /mails
  GET /mails/{id}
  POST /gmail/sync
  POST /mails/{id}/importance
  POST /mails/{id}/process
  POST /cases/{case_id}/mails

Task:
  GET /tasks
  POST /tasks
  PATCH /tasks/{id}
  POST /tasks/{id}/complete
  POST /tasks/{id}/cancel
  POST /tasks/{id}/delete

Draft:
  POST /mails/{id}/draft-reply
  PATCH /drafts/{id}
  POST /drafts/{id}/send

Jobs/External:
  GET /jobs
  GET /external-operations
```

## 23.2 次に必要

```text
Calendar:
  GET /calendar/events
  POST /mails/{id}/extract-calendar-candidates
  POST /mails/{id}/create-calendar-event

Rules:
  GET /mail-importance-rules
  POST /mail-importance-rules

Files:
  GET /cases/{id}/files
  POST /cases/{id}/files
  GET /files/{id}/download

Maintenance:
  GET /maintenance/status
  POST /maintenance/graceful-shutdown
```

## 23.3 後続でよい

```text
Google Tasks export
Pomodoro timer
Handover report export
Advanced file search
Advanced backup/restore UI
GitHub / Overleaf integration
Case内RAG
```

---

# 24. 未確定・実装時判断事項

以下は、APIの入口だけ定義し、詳細は実装時に調整する。

- Calendar予定変更とリンク解除のUI分離
- Gmail APIの差分同期方式
- 送信済みメールの即時DB反映方法
- 添付ファイル実体取得のタイミング
- LLM cost計算の厳密性
- ファイルプレビューAPI
- Handover report生成API
- Google Tasks export API
- Mobile向け軽量APIの分離
- WebSocket / SSE によるJob進捗通知

---

# 25. 設計上の最重要原則

API実装時に迷った場合は、以下を優先する。

```text
1. ユーザー操作を待たせない。
2. ユーザー操作をLLMや自動処理で上書きしない。
3. 業務DB更新はSingle DB Writer経由にする。
4. 外部副作用はexternal_operations経由にする。
5. Gmail送信などの外部副作用は二重実行しない。
6. unknown状態は自動再実行しない。
7. Contact未登録FromはPendingにする。
8. Address単独Skipは存在させない。
9. Caseは関連メール集合を持つ。
10. Taskは物理削除せず論理削除する。
11. Caseは削除しない。
12. Caseの完了はClosed、Taskの完了はCompletedと呼ぶ。
13. PinnedはGmailスターと無関係に扱う。
14. Lowは自動要約・自動Case判定しない。
15. LLM入力全文はログに保存しない。
```


---

# 22. v0.2で確定した事項

本版では、読み合わせ結果を踏まえて以下を確定した。

1. **Case関連メール操作はCase側API中心とする。**

```http
POST /api/v1/cases/{case_id}/mails
GET /api/v1/cases/{case_id}/mails
DELETE /api/v1/cases/{case_id}/mails/{message_id}
```

UI表現としては「このCaseにメールを入れる」「別Caseにコピー」とする。

2. **メールからTaskを作成した場合、メールは原則Processedにする。**

`POST /api/v1/mails/{message_id}/create-task` は、Task作成と同時に `processed_status = processed` を設定するWrite Requestを作成する。

3. **Contact未登録Fromの処理は独立画面/APIで扱う。**

```http
GET /api/v1/contacts/unresolved-from-addresses
POST /api/v1/contacts/unresolved-from-addresses/{encoded_email}/generate-prefill
```

初期運用ではPendingが多く出ることを想定し、メール詳細画面内だけでなく、まとめて処理できる独立画面を用意する。
