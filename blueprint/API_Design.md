# CaseClosed API詳細設計書

Version: 0.3  
作成日: 2026-05-22  
対象: 個人用案件管理Webアプリ CaseClosed  
関連文書: `CaseClosed_Overview_Design_v0.4.md`, `CaseClosed_Detailed_Design_v0.4.md`, `CaseClosed_DB_Design_v0.3.md`

---

## 0. 本書の位置づけ

本書は、CaseClosed のAPI詳細設計書である。

概要設計・詳細設計・DB詳細設計で定義した概念を、Web UI、Worker、Audit Log Writer、External Operation が利用するAPIとして具体化する。

現行実装では、通常の業務DB更新はAPI/WorkerがリクエストまたはJob単位のトランザクション内で直接反映する。`write_requests` / Single DB Writer は将来の同時書き込み負荷対策として残る設計候補であり、現行APIの必須経路ではない。

本書は以下を目的とする。

- 画面実装者が必要なAPIを把握できること
- DB更新がユーザー確定値を不用意に上書きしないこと
- 外部副作用を二重実行しないこと
- ユーザー操作由来の状態とLLM/System由来の状態を混同しないこと
- 必要なボタン・操作に対応するAPIを欠落させないこと

本書はOpenAPI定義を完全固定するものではない。実装時には型定義、JSON Schema、バリデーション、認可チェック、エラーコードを追加・調整してよい。

---

# 1. API設計基本方針

## 1.1 基本原則

1. API名は英語で統一する。
2. Read API は原則としてSQLiteを直接読む。
3. 業務DB更新は、現行実装ではAPI/WorkerがDBトランザクション内で直接反映する。
4. Audit Log は Audit Log Writer へ送る。
5. 外部副作用は `external_operations` 経由で実行する。
6. 単純な属性編集は `PATCH` を使う。
7. 業務上意味を持つ操作は `POST action` を使う。
8. 物理削除は通常APIからは提供しない。ただし、誤作成Case削除のように明示確認付きの例外操作は許可する。
9. 軽量な操作は `optimistic_state` を返してUIに即時反映させる。
10. 競合時はユーザー値を守る。
11. LLM/System由来のAPI・Jobは `user_*` を上書きしてはならない。

## 1.2 APIの種類

```text
Read API:
  画面表示・検索・詳細取得

Command API:
  ユーザー操作をDB Transaction / Job / External Operationへ変換

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
  -> Validate / authorize / conflict check
  -> business tables UPDATE/INSERT in one DB transaction
```

SQLiteの書き込み競合が実運用上問題になる場合は、同じCommand API境界を保ったまま `write_requests` / Single DB Writer に置き換えられるようにする。

### LLM処理

```text
Browser UI or System Trigger
  -> jobs INSERT
  -> Orchestrator
  -> LLM Worker
  -> llm_runs INSERT
  -> business tables UPDATE/INSERT in one DB transaction
```

### Gmail送信 / Gmailスター / Calendar作成

```text
Browser UI
  -> Web/API Process
  -> external_operations INSERT
  -> External Operation Worker
  -> Gmail / Calendar API
  -> local reflection in DB transaction
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

Timestamp fields use ISO-8601 JST with the `+09:00` offset.

Canonical datetime representation:

```text
YYYY-MM-DDTHH:mm:ss+09:00
```

Calendar command APIs SHOULD send `start` / `end` in this canonical form. For
compatibility with browser `datetime-local` controls, the API MAY accept
offset-less `YYYY-MM-DDTHH:mm` or `YYYY-MM-DDTHH:mm:ss` and interpret it as the
request `time_zone` local time. When an offset is present, the API treats the
value as an absolute instant and normalizes it to the requested `time_zone`
before sending it to Google Calendar. Date-only all-day values remain
`YYYY-MM-DD`.

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

更新APIは現在versionと比較し、競合時は安全側に倒す。

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
    "session_expires_at": "2026-05-23T10:00:00+09:00"
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
- Phase 7 Fix時点では、手動Assign / 明示Auto Assign Ruleで作成された関連メールThreadを返す。
- ファイルカード表示を含む場合はファイル exposure log を記録する。

## 6.2.1 Case Auto Assign Rules

```http
GET /api/v1/cases/{case_id}/auto-assign-rules
POST /api/v1/cases/{case_id}/auto-assign-rules
DELETE /api/v1/cases/{case_id}/auto-assign-rules/{rule_id}
```

POST request:

```json
{
  "sender_email": "papers@example.com"
}
```

仕様:

- Phase 7 Fix時点では `sender_email` 条件のみ扱う。
- メール受信時、Archivedになっていない全Caseの有効Ruleを参照する。
- Completed Caseは判定対象に含む。
- メール側はSPAM判定されていない全メールを対象とする。
- Skip扱いの送信者も対象に含み、Contact `spam` および件名 `[SPAM]` 判定は対象外とする。
- 条件一致時は対象CaseへThread単位で関連メールを追加する。
- 既存リンクがある場合は重複作成しない。
- LLM Case判定とは別の明示ルールであり、LLMコストは発生しない。

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
- `completed` / `canceled` TaskのみならCompleted可能。
- `closed_at` を設定する。
- system case のうち Inbox / システムメンテナンスはCompleted不可。

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

## 6.8.1 Caseを削除する

```http
DELETE /api/v1/cases/{case_id}
```

用途:

- 誤って作成したCase
- 案件として扱う必要がなくなった未完了Case
- Archiveではなく通常画面から完全に消したいノイズCase

仕様:

- 通常の完了処理には使わない。完了したCaseはClosed後にArchiveする。
- System Caseは削除不可。
- UI導線は目立たせず、確認を必須にする。
- 関連Taskは `deleted_at` による論理削除にする。
- 関連メールリンク、Stakeholder、Tool Link、File Linkは解除または削除済み扱いにする。
- Case専用Storage Directoryは通常ディレクトリへ戻すなど、保存済みファイルを失わない扱いにする。
- 監査ログそのものは削除しない。

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

## 7.0 疑似メール投入API

Phase 4初期は外部Gmail APIに接続せず、疑似メール投入APIでDB保存・Pending判定・後続Job作成を固定する。

```http
POST /api/v1/mails/mock-ingest
```

Request:

```json
{
  "gmail_message_id": "gmail_...",
  "gmail_thread_id": "thread_...",
  "message_id_header": "<...>",
  "subject": "...",
  "from_address": "...",
  "sender_address": "...",
  "reply_to_address": "...",
  "to_addresses": ["..."],
  "cc_addresses": ["..."],
  "bcc_addresses": ["..."],
  "list_id": "...",
  "received_at": "2026-05-23T10:00:00+09:00",
  "body_text": "...",
  "external_starred": false
}
```

Response:

```json
{
  "ok": true,
  "data": {
    "message_id": "mail_...",
    "gmail_message_id": "gmail_...",
    "pending": true,
    "pending_address": "unknown@example.com",
    "pending_reason": "unresolved_from_contact",
    "queued_job_id": null
  }
}
```

このAPIは開発・テスト用の固定点であり、外部サービス副作用を持たない。

疑似メールで作られたPending Contactを通常のContact登録導線で解決した場合、`contact_resolution_followup` Jobにより該当メールのPending状態を解除し、skippedでなければ重要度判定Jobへ戻す。

## 7.1 メール一覧

```http
GET /api/v1/mails
```

Query:

```text
folder=inbox|sent|all
tab=all|pending|unprocessed|processed|skip
processed=0|1|all
importance=Pinned|High|Middle|Low|Skip|Pending|all
case_id=...
contact_status=pending|resolved|all
read=all|read|unread
q=...
date_from=...
date_to=...
limit=50
cursor=...
```

Phase 4 initial implementation scope:

- `tab`: `all` / `pending` / `unprocessed` / `processed` / `skip`. This maps directly to the main mail UI tabs.
- `processed`: `all` / `0` / `1` / `unprocessed` / `processed`
- `importance`: `all` / `Pinned` / `High` / `Middle` / `Low` / `Skip` / `Pending` / `Unclassified`
- `contact_status`: `all` / `pending` / `resolved`
- `read`: `all` / `read` / `unread`. This is CaseClosed app read state, not necessarily Gmail read state.
- `q`: whitespace-separated AND search. Each token is matched against subject, From, From name, Sender, Reply-To, address JSON fields, Message-ID, List-ID, snippet, and body text.
- `date_from` / `date_to`: inclusive JST ISO string range over `received_at`.
- `limit`: 1-100. Values above 100 are clamped to 100.
- `cursor`: opaque cursor returned as `next_cursor`; ordering is `received_at DESC, id ASC`.
- List items include `received_date`, `read_status`, `read_at`, and `importance_rank` so the frontend can group by received day and sort the visible page by priority without changing cursor semantics.
- For the daily mail UI, the frontend should use `tab` and date range filters for date masks. For search UI, it should use `q` with `limit/cursor`; sorting such as "newest first" vs "priority first" is applied to the currently visible N results.
- Phase 4 send requests are included only while they are pre-send/cancelable.
  A send-only request with no reply target is exposed as a provisional outgoing
  list item in the processed/Done tab for its `scheduled_at` date. It uses
  `effective_importance = sent`, `processed_status = processed`, and
  `read_status = read`.
- Normal `Send` is intentionally modeled as scheduled send at
  `now(JST) + 1 minute`; explicit `Schedule Send` uses the user-selected
  `scheduled_at`.

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
  "received_date": "2026-05-23",
  "processed_status": "unprocessed",
  "read_status": "unread",
  "effective_importance": "Pending",
  "importance_rank": 5,
  "initial_is_starred": false,
  "external_importance": null,
  "summary_status": "not_started",
  "primary_case": null,
  "copy_cases": [],
  "has_attachments": true
}
```

Phase 4初期では、本文、主要ヘッダ、同一スレッド内メール、`mail_user_state`、`mail_auto_state`、空のsummary/case/attachment/draft配列、利用可能操作を返すところまでを固定する。

監査ログ:

- 表示されたメールIDを exposure batch として記録する。

## 7.2 メール詳細

現行仕様補足:

- メールをCaseへ手動Assignした場合、そのThread内メールの送信者は対象CaseのStakeholder候補として扱う。
- 既存Contactに解決でき、まだ対象CaseのStakeholderでない送信者は、`role = mail_sender` のStakeholderとして追加する。
- 明示Auto Assign RuleでCaseリンクが作られた場合も同じ同期を行う。
- 既存リンク全体を同期する保守APIとして `POST /api/v1/cases/sync-mail-sender-stakeholders` を持ち、戻り値は `{ added_count }` とする。


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
  "task_links": [],
  "calendar_event_links": [],
  "attachments": [],
  "drafts": [],
  "available_actions": []
}
```

現行実装では、メール詳細は関連Caseに加えて、同一Thread内メールを起点に作られたTaskと、同一Thread内メールにリンクされたCalendar Eventを返す。Taskは `tasks.source_type = mail` / `source_id in thread_message_ids`、Calendar Eventは `calendar_event_links.linked_type in (mail, gmail_message)` / `linked_id in thread_message_ids` で抽出する。削除済みTask、missing同期Event、Google側cancelled Eventは表示対象外とする。

Phase 4 send-request detail:

- `{message_id}` may be a `mail_send_requests.id` for a send-only pre-send
  request.
- The response shape stays the same as mail detail.
- `message` is synthesized from the send request.
- `thread_messages` is empty for send-only requests.
- `scheduled_send_requests` contains the visible request.
- Reply send requests are shown inside the reply target thread.

### 7.2.1 Mail send requests

External Gmail send is not active in Phase 4 mock mode. The app uses
`mail_send_requests` to represent cancelable pre-send requests.

```http
POST /api/v1/mails/send
POST /api/v1/mails/send-requests/{send_request_id}/send-now
PATCH /api/v1/mails/send-requests/{send_request_id}/schedule
POST /api/v1/mails/send-requests/{send_request_id}/cancel
GET /api/v1/mails/send-requests
```

Status values:

```text
scheduled_mock
queued_mock
sending_mock
sent_mock
canceled
```

Rules:

- `POST /send` always creates a scheduled request in current Phase 4 behavior.
- If `scheduled_at` is omitted, the API sets it to `now(JST) + 1 minute`.
- `send-now` changes the request to immediate queue execution.
- `schedule` changes the scheduled time.
- `cancel` marks the request canceled and removes it from normal mail UI.
- After real Gmail send succeeds, normal UI should rely on Gmail sync for the
  authoritative sent message and avoid showing both the internal request and the
  synced SENT message.

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
- Phase 7 Fix時点では自動Case判定Jobを発火しない。手動Assign運用を優先し、必要になった場合に候補提示または自動判定を追加する。

Phase 4初期の外部接続前実装では、Gmailスター付与などの外部副作用はまだ作らず、`mail_user_state.user_importance` と `mail_auto_state.effective_importance` の更新だけを行う。

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
- Phase 4初期では `mail_user_state.processed_status` / `processed_at` の更新を固定する。Case/Task/Event側の副作用は後続Phaseで追加する。

## 7.6 メール未処理へ戻す

```http
POST /api/v1/mails/{message_id}/unprocess
```

## 7.6.1 Mail read state

```http
POST /api/v1/mails/{message_id}/read
POST /api/v1/mails/{message_id}/unread
```

Phase 4 initial implementation:

- Newly ingested mail starts as `read_status = unread`.
- `read` sets `read_status = read` and `read_at = now(JST)`.
- `unread` sets `read_status = unread` and clears `read_at`.
- This state is an app-side visual state for the mail UI. It is separate from Gmail read/unread labels and from `processed_status`.

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

Response:

```json
{
  "contact": {},
  "related_cases": []
}
```

仕様:

- `related_cases` は `contact_case_links` を起点に、このContactが関係するCaseを参照表示するための一覧である。
- Contact詳細では関連Caseを閲覧できるが、関連付けの主たる作成・編集導線はCase側に置く。
- Contact側の関連Case一覧は「この人が今どの案件に関係しているか」を確認するための補助ビューである。

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
  "latest_from_name": "...",
  "latest_from_address": "...",
  "latest_reply_to_address": "...",
  "latest_received_at": "2026-05-24T10:00:00+09:00",
  "latest_body_preview": "...",
  "inferred_display_name": "...",
  "inferred_kind": "person|mailing_list",
  "inferred_sender_resolution": "self|reply_to",
  "suggestion_status": "not_started|running|succeeded|failed",
  "suggestion": {}
}
```

仕様:

- Fromに出現したContact未登録メールアドレスを表示する。
- To/Cc/Bccの未知アドレスはPending対象ではない。
- `inferred_display_name` はFrom表示名があればそれを使い、なければメールアドレスのlocal partから生成する。
- 原則としてFromとReply-Toが異なる場合は `inferred_kind = mailing_list` / `inferred_sender_resolution = reply_to` とする。
- ただし、既知Mailing Listの `reply_to` 解決によりReply-To側がPendingになった場合、そのPending対象は実送信者候補なので `person` / `self` と推定する。
- Pending Contact UIではActive/Skipを明示選択させる。Active選択時にContact Prefill Jobを補助的にキュー投入してよいが、LLM Prefill完了はPending解決の必須条件ではない。

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
  "user_memo": "...",
  "ai_memo": "...",
  "status": "active|skipped",
  "kind": "person|mailing_list",
  "sender_resolution_mode": "self|reply_to",
  "mailing_list_recipient_expression": "{...}",
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
- `source_suggestion_id` が指定された場合、採用元の `contact_registration_suggestions.status` を `adopted` または `edited_and_adopted` に更新する。
- Pending Contact画面からPrefill候補を採用してContactを作成する場合は、UI/APIとも `source_suggestion_id` を渡す。これにより候補採用履歴、`contact_resolution_followup`、`mail_importance_classification` までの導線を1本の状態遷移として追跡できる。
- `kind` 未指定時は `person` とする。
- 同一display_nameのContactを新規作成または更新しようとした場合、保存時に `_2`, `_3` のようなsuffixを付けて一意化する。
- `sender_resolution_mode` 未指定時は `self` とする。
- `person` は `sender_resolution_mode = self` のみ許可する。
- `mailing_list` は `sender_resolution_mode = self|reply_to` を許可する。
- `mailing_list + self` はNeuromail等、FromのML Contact自体を送信者として扱えばよいケースで使う。
- `mailing_list + reply_to` は学内委員会ML等、`Reply-To` を実送信者候補として再解決したいケースで使う。
- `mailing_list` は1 Contact = 1メールアドレスとする。
- `mailing_list` はContact tagsを持たない。`tags` は空配列にする。
- `mailing-list` は予約タグとして使用不可。
- `mailing_list_recipient_expression` は将来の宛先置き換え用タグ式であり、Phase 3では保存・表示のみ行う。

## 8.5.1 Contact統合

```http
POST /api/v1/contacts/{source_contact_id}/merge
```

Request:

```json
{
  "target_contact_id": "contact_..."
}
```

仕様:

- 通常Person Contact同士を統合する。
- Source ContactのメールアドレスをTarget Contactへ移動する。
- Source/TargetのContact tagsは和集合にする。
- Target Contactの表示名、statusはTarget側を維持する。
- memoは作成日時が古いContactのmemoを採用する。ただし古いContactのmemoが空の場合は新しいContactのmemoを採用する。
- Source Contactは削除扱いにする。
- Mailing List Contactは統合対象外とする。
- Pending Contact解決画面では既存Contact追加を行わず、誤って分かれたContactはこの統合機能で後から解消する。

## 8.6 Contact更新

```http
PATCH /api/v1/contacts/{contact_id}
```

更新可能項目:

```json
{
  "display_name": "...",
  "avatar_url": "...",
  "user_memo": "...",
  "ai_memo": "...",
  "status": "active|skipped|archived",
  "kind": "person|mailing_list",
  "sender_resolution_mode": "self|reply_to",
  "mailing_list_recipient_expression": "{...}",
  "tags": ["..."]
}
```

制約:

- `person` は `sender_resolution_mode = self` のみ許可する。
- `mailing_list` は `sender_resolution_mode = self|reply_to` を許可する。
- `mailing_list` の `tags` は空配列にする。

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

制約:

- `kind = mailing_list` のContactには2件目のメールアドレスを追加できない。
- メールアドレス移動でも、`mailing_list` Contactに2件目のメールアドレスを持たせることはできない。
- `kind = mailing_list` のメールアドレスは常にActive/Primaryであり、Remove/Deactivate/Set Primary操作を許可しない。

## 8.10 Contact削除

```http
DELETE /api/v1/contacts/{contact_id}
```

仕様:

- 紐づく全メールアドレスの `has_inbound_message_history = 0` の場合のみ削除できる。
- 削除時はメールアドレスを物理削除し、Contact本体は `deleted_at` を設定する。
- 1件でも `has_inbound_message_history = 1` のメールアドレスがある場合は `409 CONFLICT` を返す。

## 8.10 Contactからメールアドレスを外す

```http
DELETE /api/v1/contacts/{contact_id}/email-addresses/{email_address_id}
```

仕様:

- DB内にそのアドレス由来のメールが存在しない場合は、typo等の誤登録として物理削除してよい。
- `contact_email_addresses.has_inbound_message_history = 1` の場合は、物理削除せず `contact_email_addresses.status = inactive` にする。
- `inactive` のメールアドレスもFrom Contact解決には使う。過去メールや新規受信メールが「該当Contactなし」にならないようにする。
- `inactive` のメールアドレスは送信先候補、返信先候補、Primary指定の対象にしない。
- 同じアドレスが別Contactへ追加された場合は、新しい行を作らず既存の `contact_email_addresses` を再利用し、`active` / `inactive` 状態を維持したままContactを付け替える。
- `has_inbound_message_history` はGmail Sync等でFromとして観測した時点で `1` にする。削除時にメールテーブルを全走査しない。
- UIでは `has_inbound_message_history = 1` のアドレスに対して、単純な `Remove` ではなく `Deactivate` 等の履歴を残す操作だと分かる表現を使う。

## 8.11 Contactメールアドレスを再有効化する

```http
POST /api/v1/contacts/{contact_id}/email-addresses/{email_address_id}/activate
```

仕様:

- `inactive` のメールアドレスを同じContact内で `active` に戻す。
- Contactにactiveアドレスがない場合、再有効化したアドレスをPrimaryにする。
- Contactに他のactiveアドレスがある場合、再有効化したアドレスはPrimaryにしない。

## 8.12 Contact間でメールアドレスを移動する

```http
POST /api/v1/contacts/{contact_id}/email-addresses/{email_address_id}/move
```

Request:

```json
{
  "target_contact_id": "contact_..."
}
```

仕様:

- `contact_id` は移動元Contactである。
- 移動後も、対象メールアドレスの `active` / `inactive` 状態は維持する。
- 移動元ContactでPrimaryだった場合、移動元に他のactiveアドレスがあればPrimaryを付け替える。
- 移動先Contactにactiveアドレスがなく、移動したアドレスが `active` の場合、移動したアドレスをPrimaryにする。
- `has_inbound_message_history` は維持する。
- `inactive` アドレスも移動可能であり、移動先でも `inactive` のまま保持する。

## 8.13 Contact Merge

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

## 11.1.1 Calendar時刻表現

Calendar予定作成・変更系APIの `start` / `end` は、原則として以下の
offset付きISO-8601文字列を用いる。

```text
2026-06-10T10:00:00+09:00
```

互換入力として、ブラウザの `datetime-local` 由来の
`2026-06-10T10:00` / `2026-06-10T10:00:00` も受け付ける。この場合は
`time_zone` のローカル時刻として扱う。

Google Calendarへ送る時は、`dateTime` をoffset付きISO文字列へ正規化し、
同時に `timeZone` を設定する。これによりアプリ内部・APIテスト・外部API
送信の表現を揃える。

週次または隔週の繰り返し予定で `RRULE:FREQ=WEEKLY;BYDAY=...` が指定され、入力された開始日が選択曜日と一致しない場合、作成APIは開始・終了日時を最初に到来する選択曜日へ同じ日数だけ前方シフトしてからGoogle Calendarへ送る。これにより、繰り返し初日ではない入力日へ単発の余計な予定が作られることを防ぐ。

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

# 12. Follow-up Candidate API

現行仕様では、返信待ちを永続的なWatchとしてユーザーが管理するのではなく、
ルールベースで「確認した方がよい送信メール候補」を作る。
検出誤りのコストは高くないため、初期実装ではLLMを使わず、本文中の定型表現を
もとに候補化し、ユーザーは候補を `resolved` または `dismissed` にする。

AutoBody / quoted reply 等の自動引用領域は候補検出の対象外とする。

## 12.1 Follow-up候補一覧

```http
GET /api/v1/follow-ups
```

Query:

```text
status=pending|resolved|dismissed
```

仕様:

- 初期候補はルールベースで作成する。
- 例: 「ご確認」「ご査収」等が含まれる送信メールを、送信から約1週間後の確認候補にする。
- 候補はMail画面右ガジェットから遷移するFollow Upページで確認する。
- Topページには常設しない。

## 12.2 Follow-up候補のDismiss

```http
POST /api/v1/follow-ups/{follow_up_id}/dismiss
```

仕様:

- Dismiss時に理由入力は求めない。
- 将来、Dismissされた候補をサンプルとしてルール改善またはLLM判定に利用できる。

## 12.3 Follow-up候補のResolve

```http
POST /api/v1/follow-ups/{follow_up_id}/resolve
```

仕様:

- ユーザーが対応済みと判断した候補を閉じる。

## 12.4 Follow-up候補のSnooze

```http
POST /api/v1/follow-ups/{follow_up_id}/snooze
```

仕様:

- 候補の確認日を後日に送る。

---

# 13. File / Storage API

現行実装は、`files` テーブルを分けず `storage_objects` をファイル系列として扱う。Case専用Storage Directoryを維持しつつ、複数Case / 通常Storageから同一ファイルを参照する場合は `file_links` を使う。

## 13.1 Storage一覧

```http
GET /api/v1/storage/objects
```

Query:

```text
directory_id
limit
```

仕様:

- `scope = managed` かつ `status = active` のStorage objectを返す。
- Storage一覧からのダウンロードは常に最新版を対象とする。

フロントルート:

```http
GET /files
```

## 13.2 Storage詳細

```http
GET /api/v1/storage/objects/{storage_object_id}
```

仕様:

- 添付元メールがあれば `source_mail` を返す。
- `url` / `download_url` は最新版を指す。

フロントルート:

```http
GET /files/{storage_object_id}
```

## 13.2.1 Case file links

```http
GET /api/v1/cases/{case_id}/files
POST /api/v1/cases/{case_id}/files/{storage_object_id}/link
DELETE /api/v1/cases/{case_id}/files/{storage_object_id}/link
```

仕様:

- `GET` は、Case専用Storage Directory配下のactive Storage objectと、`file_links.linked_type = case` / `linked_id = case_id` / `status = active` のStorage objectを合わせて返す。
- `POST` は、既存Storage objectをCaseへリンクする。Storage object本体の `directory_id` は変更しない。
- `DELETE` は、そのCaseから対象Storage objectを除外する。対象がCase専用Storage Directory配下に実体所属している場合はStorage rootへ戻す。
- ファイル本体の削除は通常の `DELETE /api/v1/storage/objects/{storage_object_id}` を使う。この場合、当該ファイルのCaseリンクもすべて削除扱いになる。

## 13.3 ファイルアップロード

```http
POST /api/v1/storage/objects/upload
Content-Type: multipart/form-data
```

仕様:

- `storage_objects` を作成する。
- 物理保存パスはID/hashベースとし、元ファイル名とは分離する。
- 操作履歴に `uploaded` を残す。

## 13.4 Storage object作成

```http
POST /api/v1/storage/objects
```

仕様:

- 内部処理からStorage objectを作成する場合のAPI。

## 13.5 内容表示・ダウンロード

```http
GET /api/v1/storage/objects/{storage_object_id}/content
GET /api/v1/storage/objects/{storage_object_id}/download
```

仕様:

- `content` はプレビュー用inline表示。
- `download` はattachment表示。
- managed Storage objectの表示・ダウンロードは `storage_operation_history` に `viewed` / `downloaded` として記録する。
- `scope != managed` の補助画像ファイルはプレビュー時に `Cache-Control: private, max-age=604800, immutable` を返し、表示履歴を記録しない。
- managed Storage objectのcontentは引き続き `Cache-Control: no-store` を返す。

## 13.6 バージョン一覧・旧版表示

```http
GET /api/v1/storage/objects/{storage_object_id}/versions
GET /api/v1/storage/objects/{storage_object_id}/versions/{version_id}/content
GET /api/v1/storage/objects/{storage_object_id}/versions/{version_id}/download
```

仕様:

- `storage_object_versions` をversion_number降順で返す。
- 旧版content/downloadは選択バージョンの物理ファイルを返す。

## 13.7 ファイル更新

```http
POST /api/v1/storage/objects/{storage_object_id}/versions/upload
Content-Type: multipart/form-data
```

仕様:

- Storage詳細画面のドラッグ&ドロップ更新で利用する。
- 更新前の最新版を `storage_object_versions` に退避し、`storage_objects` を新しい最新版に更新する。
- 拡張子が異なる場合はフロント側で確認を挟む。
- sha256とサイズが同一の場合は更新せず `update_skipped` を履歴に残す。
- 更新時にLLMなしで抽出テキスト差分を作成し、`file_version_diffs` に保存する。

## 13.8 LLM input許可変更

```http
PATCH /api/v1/storage/objects/{storage_object_id}/llm-input
```

Request:

```json
{
  "llm_input_allowed": true
}
```

仕様:

- `llm_input_allowed = false` のファイルは後続File LLM入力対象から除外する。
- 変更は `llm_input_updated` として操作履歴に残す。

## 13.9 ディレクトリ

```http
GET /api/v1/storage/directories
POST /api/v1/storage/directories
DELETE /api/v1/storage/directories/{directory_id}
PATCH /api/v1/storage/objects/{storage_object_id}/directory
```

仕様:

- 通常ディレクトリを作成・削除する。
- Storage objectをディレクトリへ移動できる。

## 13.10 検索

```http
GET /api/v1/storage/search/objects
```

Query:

```text
query
directory_id
recursive
sort=created_desc|created_asc|name
extension
limit
```

## 13.11 ファイル削除

```http
DELETE /api/v1/storage/objects/{storage_object_id}
```

仕様:

- 現時点では物理削除を正とする。
- 最新版と旧版の物理ファイルを削除する。
- `storage_objects.status = deleted` としてDBメタ情報は残す。
- `deleted` を操作履歴に残す。

## 13.12 選択版以前の削除

```http
DELETE /api/v1/storage/objects/{storage_object_id}/versions/{version_id}/older
```

仕様:

- 選択した旧版を含め、それ以前のバージョンを物理削除する。
- 削除後は最新版表示へ戻る。

## 13.13 LLM Digest

```http
GET /api/v1/storage/objects/{storage_object_id}/llm-digest
POST /api/v1/storage/objects/{storage_object_id}/llm-digest
```

仕様:

- `version_id` queryまたはbodyで対象バージョンを指定できる。
- GETは対象版のDigest、旧Digest由来のstale表示情報、Version Differenceを返す。
- POSTは対象版のDigestを生成する。
- 対象版のDigestがなく、過去版にDigestがある場合は、最新の過去Digestと差分チェーンから増分Digestを生成する。
- 対象版に既にDigestがあり、ユーザーが明示的に再生成する場合は全文抽出から再生成する。
- LLM入力ログには全文を保存しない。

## 13.14 メール添付取得・Storage移動

```http
GET /api/v1/mails/attachments/{attachment_id}/download
POST /api/v1/mails/attachments/{attachment_id}/fetch-job
POST /api/v1/mails/attachments/{attachment_id}/move-to-storage
```

仕様:

- メール取得時は添付メタ情報を保存する。
- 添付実体取得はJob化し、`jobs.job_type = mail_attachment_fetch` で扱う。
- Storage移動時は添付元メール参照をStorage objectに保持する。

## 13.15 Maintenance / Storage

```http
GET /api/v1/maintenance/storage-operation-history
```

仕様:

- Storage操作履歴を直近順で表示する。
- Storage logは `data/storage/managed` に対応するmanaged Storage objectの操作を対象にする。
- IconやContact Imageなど、managed Storage以外の補助ファイルはLog画面のStorage種別に集約しすぎない。

## 13.16 Settings / Google diagnostics

```http
POST /api/v1/maintenance/google-speed-test
```

仕様:

- Google接続が遅い場合に、ユーザーが明示実行して診断する。
- OAuth token、Gmail profile、Calendar list、Calendar events取得を段階ごとに測定する。
- 常時Logに流すものではなく、SettingsのGoogle Connection近傍に表示する。
- Calendar events測定はCalendar自動同期設定の取得範囲を使い、対象Calendarが多い場合は上限件数で打ち切る。

## 13.17 Settings API

設定系UIはMaintenance / Debugから分離し、Settingsページに集約する。

現行Settingsタブ:

- Google: Google接続、Gmail自動取り込み、Calendar自動同期、Google Speed Test
- LLM: 機能別LLM profile割当、LLM block filter、Blocked mail一覧
- Budget: LLM monthly budget、使用量、残量

Maintenance / Debugに残すもの:

- 一時的・復旧支援用のDebug機能
- 現行ではプレビュー可能拡張子の確認

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
POST /api/v1/cases/{case_id}/current-situation
```

Phase 7 Fix時点では、Case Current Situationの手動生成APIとして扱う。
ユーザーがCase詳細でRefreshした時のみ実行し、`case_context_versions` に結果を保存する。

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
Auto Assign Rule         GET/POST/DELETE /cases/{id}/auto-assign-rules
Task作成                  POST /tasks
ファイル連携              GET/POST/DELETE /cases/{id}/files...
Context更新               POST /cases/{id}/current-situation
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
  GET /api/v1/storage/objects
  POST /api/v1/storage/objects/upload
  GET /api/v1/storage/objects/{id}/download
  GET /api/v1/storage/objects/{id}/llm-digest

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
3. 業務DB更新はAPI/WorkerのDBトランザクション内で反映し、ユーザー確定値を自動処理で上書きしない。
4. 外部副作用はexternal_operations経由にする。
5. Gmail送信などの外部副作用は二重実行しない。
6. unknown状態は自動再実行しない。
7. Contact未登録FromはPendingにする。
8. Address単独Skipは存在させない。
9. Caseは関連メール集合を持つ。
10. Taskは物理削除せず論理削除する。
11. Caseは原則削除しない。完了CaseはArchiveし、誤作成などの例外のみ明示Deleteを許可する。
12. Caseの完了はClosed、Taskの完了はCompletedと呼ぶ。
13. PinnedはGmailスターと無関係に扱う。
14. Lowは自動要約・LLM自動Case判定しない。明示Auto Assign Ruleはユーザー設定として別扱い。
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
# Phase 4 Contact Memo Split Note

Contact memo fields are split into two API fields.

- `user_memo`: user-owned memo edited from the Contact UI.
- `ai_memo`: AI-owned memo updated by future Contact context update workers.
- Legacy `memo` payloads may be accepted only as compatibility input and are treated as `user_memo`.
- Ordinary Contact edit/save operations must not overwrite `ai_memo`.

# Phase 4 Mail LLM Block API Note

Sensitive mails can be excluded from all LLM body submission.

```http
POST /api/v1/mails/llm-block-filter
GET  /api/v1/mails/llm-blocked
```

`POST /api/v1/mails/llm-block-filter` accepts a space-separated query and a reason. Matching mail instances are marked with `llm_blocked = true`.
Workers must treat this flag as authoritative and skip importance classification, summary, translation, and future Contact AI memo updates for the mail body.
