# CaseClosed Worker / Job / External Operation設計書

Version: 0.1  
作成日: 2026-05-22  
対象: 個人用案件管理Webアプリ CaseClosed  
関連文書: `CaseClosed_Overview_Design_v0.4.md`, `CaseClosed_Detailed_Design_v0.4.md`, `CaseClosed_DB_Design_v0.3.md`, `CaseClosed_API_Design_v0.2.md`

---

## 0. 本書の位置づけ

本書は、CaseClosed における非同期処理、Worker、Job、Write Request、External Operation の詳細設計書である。

CaseClosed では、Gmail同期、LLM処理、Google Calendar連携、Gmail送信、ファイル取得、Context更新など、ユーザー操作に比べて時間がかかる処理が多数存在する。これらをWeb/API Processで直接実行すると、画面応答が重くなり、またSQLite書き込み衝突や外部API副作用の二重実行が発生しやすくなる。

そのため、本書では以下を定義する。

- Job Queue の設計
- Orchestrator の責務
- Dynamic Worker Pool の設計
- Single DB Writer の設計
- Audit Log Writer の設計
- External Operation の設計
- リトライ、失敗、unknown状態の扱い
- Graceful Shutdown
- System Maintenance Caseとの連動

本書は、実装上の詳細なクラス構成を完全固定するものではない。ただし、DB更新経路、外部副作用、LLM処理の責務分離については、本書の方針を原則とする。

---

# 1. 全体方針

## 1.1 基本原則

1. ユーザー操作を待たせない。
2. 業務DB更新は Single DB Writer に集約する。
3. Web/API Process と Worker は業務テーブルへ直接writeしない。
4. Audit Log は Audit Log Writer に分離する。
5. 外部副作用は External Operation として管理する。
6. Gmail送信、Gmailスター付与、Google Calendar作成などは二重実行しない。
7. LLM/System由来の処理は `user_*` 値を上書きしない。
8. Pending Contact状態では、重要度判定・Case判定・自動要約を止める。
9. Contact登録画面のLLM自動Fillは、Pending中でも例外的に実行可能とする。
10. Cost Limit超過などの運用上の問題は、System Maintenance Case配下にTaskを作る。

## 1.2 処理経路

### ユーザー操作由来DB更新

```text
Browser UI
  -> Web/API Process
  -> write_requests
  -> Single DB Writer
  -> Business Tables
```

### ユーザー操作由来LLM処理

```text
Browser UI
  -> Web/API Process
  -> jobs
  -> Orchestrator
  -> LLM Worker
  -> llm_runs
  -> write_requests
  -> Single DB Writer
```

### システム自動処理

```text
Scheduler / TimeEvent / Gmail Sync
  -> jobs
  -> Orchestrator
  -> Worker
  -> write_requests / jobs / external_operations
```

### 外部副作用

```text
Browser UI or Worker
  -> external_operations
  -> External Operation Worker
  -> Gmail / Google Calendar / Google Tasks
  -> write_requests for local reflection
```

### 監査ログ

```text
Browser UI / Web/API Process
  -> Audit Log Request
  -> Audit Log Writer
  -> audit_logs / audit_exposure_batches / audit_exposure_items
```

---

# 2. 主要コンポーネント

## 2.1 Web/API Process

### 責務

- UIからのリクエスト受付
- Read APIの提供
- 軽量バリデーション
- `write_requests` 作成
- `jobs` 作成
- `external_operations` 作成
- Audit Log Request作成
- `optimistic_state` 返却

### 禁止事項

- 業務テーブルへの直接UPDATE
- Gmail送信の直接実行
- Google Calendar作成の直接実行
- 重いLLM処理の直接実行
- ファイル本文抽出など長時間処理の直接実行

## 2.2 Orchestrator

### 責務

- Job Queue監視
- Job優先度制御
- Workerへの割当
- 通常失敗時のリトライ制御
- stale job検出
- Graceful Shutdown制御
- TimeEvent / Recurring Task発火
- Cost Limit監視

Orchestrator は業務DBへ直接writeしない。必要な更新は `write_requests` を作成する。

## 2.3 Dynamic Worker Pool

### 責務

- Job種別に応じた処理実行
- Worker数の動的調整
- rate limit / cost limit遵守
- 処理結果の `llm_runs`, `write_requests`, `external_operations` への記録

### Worker種別

```text
Gmail Sync Worker
LLM Worker
Case Decision Worker
Calendar Worker
File Worker
Context Update Worker
Recurring Task Worker
Report / Handover Worker
Maintenance Worker
External Operation Worker
```

## 2.4 Single DB Writer

### 責務

- `write_requests` を順次処理
- 業務DB更新の一元化
- `base_version` による競合検出
- `user_*` 値の保護
- 関連イベントの生成
- 処理結果の記録

### 原則

- ユーザー操作由来Write Requestを最優先する。
- LLM/System由来Write Requestは `user_*` を更新してはならない。
- 競合時はユーザー値を守る。
- DB transactionは短く保つ。

## 2.5 Audit Log Writer

### 責務

- 高頻度ログの処理
- メール一覧表示ログ
- ファイルカード表示ログ
- メール本文表示ログ
- 重要操作ログ

Single DB Writerとは分離する。

理由は、メール一覧表示などで大量の接触ログが発生しても、業務DB更新を詰まらせないためである。

## 2.6 External Operation Worker

### 責務

- Gmail送信
- Gmailスター付与
- Google Calendar予定作成・変更
- Google Tasksエクスポート
- 外部副作用の結果反映
- `unknown` 状態の検出

外部副作用は `idempotency_key` を必ず持つ。

---

# 3. Job設計

## 3.1 Jobの役割

Jobは、非同期に実行される内部処理を表す。

例:

- Gmail同期
- メール重要度判定
- Case判定
- 和訳要約
- 返信草案生成
- Contact登録画面のLLM自動Fill
- Case Context更新
- Contact Context更新
- 添付ファイル取得
- ファイル機密度判定
- Recurring Task生成
- バックアップ

## 3.2 Job状態

```text
pending
running
succeeded
failed
canceled
stale
```

### pending

実行待ち。

### running

Workerが処理中。

### succeeded

正常終了。

### failed

リトライ上限を超えた、または再実行しても意味がない失敗。

### canceled

ユーザーまたはシステムによりキャンセル。

### stale

プロセス停止・サーバーダウンなどにより、runningのまま放置された可能性がある状態。

MVPという概念は使わないが、初期実装では stale job の自動再実行は行わず、保守画面で確認・手動再実行する。

## 3.3 Job優先度

```text
Priority 0:
  ユーザー操作由来DB更新
  ※ 実体はwrite_requests。jobsではなくSingle DB Writer優先度として扱う。

Priority 10:
  ユーザー操作由来LLM処理
  - 返信草案生成
  - 新規メール草案生成
  - メールからタスク候補生成
  - メールから予定候補抽出
  - Contact登録画面のLLM自動Fill

Priority 20:
  外部副作用後のローカル反映
  - Gmail送信後UI反映
  - Gmailスター付与後反映
  - Calendar作成後反映

Priority 50:
  Gmail同期
  重要度判定
  Case判定
  High/Middle和訳要約

Priority 70:
  スレッド要約
  Case Context更新
  Contact Context更新

Priority 100:
  添付取得
  ファイル機密度判定
  ファイル本文抽出

Priority 150:
  Recurring Task生成
  Handover Report生成

Priority 200:
  バックアップ
  アーカイブ
  クリーンアップ
  ログ圧縮
```

## 3.4 Job種別

```text
gmail_sync
mail_importance_classification
mail_summary_translation
case_candidate_extraction
llm_case_decision
contact_registration_prefill
reply_draft_generation
new_mail_draft_generation
mail_task_extraction
mail_calendar_candidate_extraction
preparation_task_suggestion
follow_up_check
case_context_update
contact_context_update
thread_summary_generation
attachment_fetch
file_security_classification
file_text_extraction
recurring_task_generation
backup_incremental
backup_full
restore_check
cleanup
handover_report_generation
```

## 3.5 Job依存関係

Jobは必要に応じて依存関係を持つ。

例:

```text
gmail_sync
  -> contact resolution check
  -> mail_importance_classification
  -> mail_summary_translation if High/Middle
  -> llm_case_decision if High/Middle
  -> attachment_fetch if High/Middle and Case is determined
```

ただし、Pending Contactの場合は以下を止める。

```text
mail_importance_classification
mail_summary_translation
llm_case_decision
attachment_fetch by Case decision
```

例外として、以下は実行可能。

```text
contact_registration_prefill
```

## 3.6 Job作成者

```text
user
system
llm
rule
scheduler
external_operation
```

Job作成者は監査・デバッグ用に保存する。

---

# 4. Write Request設計

## 4.1 Write Requestの役割

Write Requestは、業務DB更新の要求である。

Web/API Process、Worker、External Operation Worker は業務テーブルを直接更新せず、Write Requestを作成する。

## 4.2 Write Request状態

```text
pending
processing
applied
discarded
failed
canceled
```

### pending

処理待ち。

### processing

Single DB Writerが処理中。

### applied

DB反映済み。

### discarded

競合または無効化により反映しなかった。

例:

- LLMが古い状態をもとにCase判定したが、ユーザーが既にCaseを変更していた
- base_version不一致
- 対象がdeleted/archivedになっていた

### failed

DB制約違反や実装エラー等により失敗。

### canceled

ユーザーまたはシステムが反映前にキャンセル。

## 4.3 Write Request source

```text
user
llm
system
rule
external
migration
```

## 4.4 更新権限ルール

### user source

- `user_*` カラム更新可
- 通常カラム更新可
- `auto_*` を直接更新しないことを推奨

### llm source

- `auto_*` カラム更新可
- 候補テーブル更新可
- `user_*` カラム更新不可

### system source

- system状態更新可
- `user_*` カラム更新不可

### external source

- 外部API結果の反映用
- `external_*` カラム更新可
- `user_*` カラム更新不可

## 4.5 base_version競合

更新対象テーブルには、必要に応じて `version` を持たせる。

Write Requestには、作成時点の `base_version` を保存する。

Single DB Writer処理時に現在versionと異なる場合、以下の原則に従う。

```text
user source:
  可能なら現在値に対して再適用
  危険ならfailedまたはconflict表示

llm/system source:
  原則discarded

external source:
  外部副作用結果なので慎重に反映
  二重実行防止情報は残す
```

## 4.6 optimistic_stateとの関係

APIは軽量操作に対して `optimistic_state` を返す。

UIは即時反映するが、最終的な正本はSingle DB Writer反映後のDB状態である。

推奨仕様:

```text
1. APIがwrite_request_idとoptimistic_stateを返す
2. UIは即時反映し、該当行をpending表示にする
3. 30秒以内を目安にRead APIで再同期する
4. appliedならpending表示を解除
5. discarded/failedならUIに失敗表示し、DB状態へ戻す
```

30秒は初期値であり、実装時に調整可能とする。

---

# 5. External Operation設計

## 5.1 External Operationの役割

External Operationは、外部サービスに副作用を与える操作を表す。

対象:

- Gmail送信
- Gmailスター付与
- Google Calendar予定作成
- Google Calendar予定変更
- Google Calendar予定削除
- Google Tasksエクスポート

## 5.2 External Operation状態

```text
pending
running
succeeded
failed
unknown
canceled
manual_resolution_required
```

### pending

外部実行待ち。

### running

外部API呼び出し中。

### succeeded

外部副作用が成功した。

### failed

外部副作用が発生していないことが明確な失敗。

### unknown

通信断などにより、外部副作用が発生したか不明。

### canceled

実行前にキャンセル。

### manual_resolution_required

自動判断できず、ユーザー確認が必要。

## 5.3 idempotency_key

すべてのExternal Operationは `idempotency_key` を持つ。

例:

```text
gmail_send:{draft_id}:{draft_version}
gmail_star:{message_id}:high:{source_write_request_id}
calendar_create:{mail_id}:{candidate_id}:{user_confirmed_at}
google_tasks_export:{task_id}:{task_version}
```

同じ `idempotency_key` のExternal Operationは二重作成しない。

## 5.4 unknown時の扱い

`unknown` は外部副作用が起きたか分からない危険状態である。

原則:

```text
unknownになったExternal Operationは自動再実行しない。
```

特にGmail送信では二重送信を避けるため、自動再実行禁止とする。

unknown時は以下を行う。

1. `manual_resolution_required` に遷移、またはunknownのまま保守画面に表示。
2. System Maintenance Case配下に確認Taskを作成する。
3. ユーザーがGmail/Calendar側を確認する。
4. 結果に応じて `succeeded` / `failed` / `canceled` として手動解決する。

## 5.5 Gmail送信

### 処理経路

```text
POST /drafts/{draft_id}/send
  -> external_operations(gmail_send)作成
  -> External Operation Worker
  -> Gmail API send
  -> succeededならwrite_requests作成
     - mail_drafts.sent_at更新
     - 関連メールprocessed化
     - 送信済みメールのローカル反映
```

### 二重送信防止

- `idempotency_key` 必須
- `draft_version` を含める
- `running` / `succeeded` が既にある場合は新規作成しない
- `unknown` は自動再実行しない

## 5.6 Gmailスター付与

### 発火条件

- LLMがHigh判定した
- ユーザーがアプリ上でHighにした
- ルールがHighを付与した

### 注意

- PinnedはGmailスターと無関係
- Gmail側でスター解除されてもアプリ側の重要度は下げない
- 一度読み込んだメールのスター状態は再監視しない

## 5.7 Google Calendar予定作成

### 処理経路

```text
メール詳細
  -> 予定候補抽出
  -> ユーザー確認・編集
  -> external_operations(calendar_create)
  -> Google Calendar API
  -> calendar_event_links作成
  -> メールprocessed化
```

### unknown時

Calendar側に予定が作られたか不明な場合、自動再作成しない。

System Maintenance Caseに確認Taskを作る。

---

# 6. Worker別設計

## 6.1 Gmail Sync Worker

### 責務

- 初回過去7日取得
- 通常差分取得
- 受信トレイ取得
- 送信済み直近分取得
- Gmail本文のDB保存
- 添付メタ情報保存
- 初回スター状態保存
- From Contact解決状態チェック

### 注意

一度DBに読み込んだメールは、Gmail側のスター解除や状態変化を再監視しない。

ただし、同一Gmail message IDの重複登録は防止する。

### 生成する後続処理

FromがContacts未登録:

```text
mail_auto_state.pending_reason = unresolved_from_contact
contact_registration_prefill job may be created
```

Fromが解決済み:

```text
mail_importance_classification job
```

## 6.2 LLM Worker

### 共通責務

- prompt_version取得
- input_source_json生成
- input_hash生成
- input_diagnostic_json生成
- LLM API呼び出し
- JSON Schema検証
- llm_runs保存
- 必要なwrite_requests作成

### JSON不正時

JSON不正、必須フィールド欠落、enum違反などはシステム連携失敗とみなす。

対応:

```text
1回目失敗:
  自動リトライ

2回目以降:
  JSON修正を強めたプロンプトに変更してリトライ

上限到達:
  job failed
  System Maintenance Caseに確認Taskを作成してよい
```

初期リトライ上限は3回とする。

### 人間が見て微妙な出力

以下は失敗扱いしない。

- 要約が少し不自然
- 返信草案の文体が好みと違う
- Case判定が微妙
- Contact候補の所属推定が曖昧

理由は、ユーザーが手動修正できるためである。

## 6.3 Mail Importance Worker

### 入力

- gmail_messages
- gmail_threads
- contacts
- contact tags
- mail_importance_rules
- prompt_versions

### 出力

```text
Pinnedは出力不可
High
Middle
Low
```

LLMは `Pinned`, `Skip`, `Pending` を出力してはならない。

### Lowの扱い

Lowは自動要約・自動Case判定の対象外。

## 6.4 Case Decision Worker

### 実行条件

```text
effective_importance in {High, Middle}
From Contact resolved
```

### 出力

```text
existing_case
inbox_required
no_case_needed
new_case_candidate
uncertain
```

### 反映

- `existing_case`: `case_mail_links` に primary追加
- `inbox_required`: Inbox Caseに primary追加
- `no_case_needed`: Caseリンクなし
- `new_case_candidate`: 候補として保存。原則ユーザー確認
- `uncertain`: Inboxまたは確認待ち。実装時にUIと調整

## 6.5 Contact Registration Prefill Worker

### 実行条件

From Contact未登録でPending状態のメール。

### 例外扱い

Pending中でもこのLLM処理だけは実行可能。

### 入力

- Fromアドレス
- メール件名
- メール本文
- 署名らしき部分
- To/Cc
- 過去の同Fromメールがあればその一部

### 出力

```text
suggested_display_name
suggested_organization
suggested_role
suggested_tags_json
suggested_memo
suggested_skip_reason
confidence
```

正式Contactには反映しない。ユーザーがContact登録画面で採用・編集・破棄する。

## 6.6 Summary Worker

### 実行条件

```text
effective_importance in {High, Middle}
From Contact resolved
```

### 出力

- 概要 3〜5行
- 要対応
- 期限
- 次アクション
- key_points

Lowは自動要約しない。

## 6.7 Draft Worker

### 種別

- reply_draft_generation
- new_mail_draft_generation
- reminder_mail_generation

### 方針

- Gmail Draftにはしない
- アプリ内 `mail_drafts` に保存
- 再生成時は既存草案を入力に含める
- 追加プロンプトを反映する

## 6.8 Calendar Worker

### 責務

- Google Calendar予定候補抽出
- 空き時間候補取得
- 作業ブロック候補生成
- Calendar作成External Operationの補助

Google Calendarへの実際の書き込みは External Operation Worker が行う。

## 6.9 File Worker

### 責務

- 添付ファイル取得
- storage_objects保存
- file record作成
- file_security_classification
- file_text_extraction

### LLM Policy

```text
allowed:
  自動LLM処理可

confirm_required:
  ユーザー確認後にLLM処理可

forbidden:
  手動でポリシー変更しない限りLLM処理不可
```

## 6.10 Context Update Worker

### 対象

- Case Context
- Contact Context

### 方針

- イベント、メール要約、Task履歴、予定、メモをもとに更新
- 過去versionを保持
- user memoやuser確定値を上書きしない

## 6.11 Recurring Task Worker

### 責務

- recurring_task_templates の発火判定
- generated_recurring_tasks による重複防止
- Task作成Write Request生成

## 6.12 Maintenance Worker

### 責務

- Cost Limit監視
- 証明書期限確認
- バックアップ予定確認
- 復旧テスト予定確認
- stale job検出
- unknown external_operation検出
- System Maintenance CaseへのTask生成

---

# 7. Cost Limit設計

## 7.1 基本方針

LLM利用にはcost limitを設定可能にする。

Cost Limitに近づいた、または超過しそうな場合、無理に処理を続けず、System Maintenance Case配下にTaskを作る。

## 7.2 Cost状態

```text
normal
approaching_limit
limit_reached
blocked
```

## 7.3 発生時の挙動

### approaching_limit

- System Maintenance Caseに確認Taskを作成してよい
- 自動LLM処理の優先度を下げる

### limit_reached

- 自動LLM処理を停止
- 手動LLM処理は確認後に許可してもよい
- System Maintenance CaseにTaskを作成

### blocked

- LLM処理を実行しない
- UIに理由を表示

## 7.4 作成されるTask例

```text
LLM利用量が上限に近づいているため設定を確認する
LLM Cost Limitに達したため自動処理を再開するか判断する
LLMモデル・利用上限設定を見直す
```

---

# 8. System Maintenance Case

## 8.1 基本方針

CaseClosed自身の運用に関する作業を扱う特殊Caseを、初期データとして作成する。

```text
Case name: システムメンテナンス
system_case_type: system_maintenance
```

## 8.2 性質

- 削除不可
- archived不可
- closed不可、またはclosedしても自動再open可能
- 通常Case一覧では専用枠に表示してよい

## 8.3 自動生成されるTask

- クライアント証明書更新
- 証明書失効確認
- バックアップ確認
- 復旧テスト
- LLM Cost Limit確認
- stale job確認
- unknown external operation確認
- 外部API token期限確認

---

# 9. Graceful Shutdown

## 9.1 基本方針

保守・運用画面からGraceful Shutdownを実行可能にする。

## 9.2 手順

```text
1. 新規Job受付停止
2. 新規External Operation受付停止
3. 実行中Jobの完了待ち
4. 実行中External Operationの完了待ち
5. pending Write Request反映
6. Audit Log Writer flush
7. Worker停止
8. Single DB Writer停止
9. サービス停止可能状態へ
```

## 9.3 タイムアウト

各段階にタイムアウトを設ける。

タイムアウトしたJobは `stale` 候補として記録する。

Gmail送信など外部副作用中の処理は、状態を慎重に扱い、必要なら `unknown` にする。

---

# 10. stale job / 復旧方針

## 10.1 通常失敗とstaleの区別

### 通常失敗

Workerがエラーを捕捉できた失敗。

例:

- LLM JSON不正
- API rate limit
- DB制約違反
- ファイル取得失敗

通常失敗は retry policy に従って自動リトライ可能。

### stale

プロセス停止・サーバーダウン等で、Jobがrunningのまま残った状態。

初期実装では自動再実行しない。

## 10.2 stale検出

Orchestrator起動時または定期チェックで、以下を検出する。

```text
status = running
and locked_at < now - stale_threshold
```

## 10.3 stale発見時

- `stale` に遷移
- 保守画面に表示
- System Maintenance Caseに確認Taskを作成してよい
- ユーザーが手動で再実行・キャンセル・成功扱いを選ぶ

---

# 11. Retry Policy

## 11.1 基本方針

リトライは失敗種別ごとに扱う。

## 11.2 リトライ可能

```text
LLM JSON不正
LLM一時エラー
外部API rate limit
ネットワーク一時エラー
ファイル一時取得失敗
SQLite busy
```

## 11.3 リトライ不可

```text
ユーザー権限不足
認証token失効
forbidden fileへのLLM投入
存在しないCase/Task
base_version競合によるLLM結果discard
Gmail送信unknown
Calendar作成unknown
```

## 11.4 Backoff

初期値:

```text
1回目: 10秒後
2回目: 1分後
3回目: 5分後
以降: 手動確認
```

LLM JSON不正の場合は、backoffよりもプロンプト修正リトライを優先してよい。

---

# 12. Rate Limit / Concurrency

## 12.1 基本方針

Worker数は動的可変とする。

設定例:

```text
min_workers = 1
max_workers = 4
llm_max_concurrent = 2
gmail_max_concurrent = 1
calendar_max_concurrent = 1
file_max_concurrent = 2
```

## 12.2 SQLite制約

SQLite writeはSingle DB Writerのみが行う。

複数Workerはread可能だが、writeはWrite Requestに変換する。

## 12.3 LLM制約

- providerごとのrate limitを守る
- cost limitを守る
- 自動LLM処理よりユーザー操作由来LLMを優先する

---

# 13. TimeEvent / Scheduler

## 13.1 定期処理

```text
Gmail差分同期
Follow-up Watch確認
Recurring Task生成
証明書期限確認
バックアップ予定確認
Cost Limit確認
stale job確認
unknown external operation確認
```

## 13.2 発火間隔初期案

```text
Gmail差分同期:
  5〜15分ごと。実装時調整。

Follow-up Watch確認:
  1日1回。

Recurring Task生成:
  1日1回。

証明書期限確認:
  1日1回。

Cost Limit確認:
  LLM実行ごと + 1日1回。

stale job確認:
  起動時 + 1時間ごと。

unknown external operation確認:
  起動時 + 1時間ごと。
```

---

# 14. 監査・ログ

## 14.1 System Log

Worker内部の技術ログ。

例:

- Job開始
- Job終了
- retry
- external API error
- JSON parse error
- stale検出

## 14.2 Event Log

CaseやTaskなど業務対象に関するイベント。

例:

- メール受信
- Caseにメール追加
- Task作成
- Task完了
- Calendar予定作成

## 14.3 Audit Log

ユーザー接触・重要操作のログ。

Worker処理そのものは通常Audit LogではなくSystem Log / Event Logに記録する。

ただし、外部送信やファイルLLM投入など、重要操作に関わるものはAudit Log対象になりうる。

---

# 15. 実装順序案

本書の範囲は大きいため、以下の順で実装する。

## Phase A: 最小非同期基盤

1. jobs
2. write_requests
3. QueueInterface
4. SQLiteQueue
5. Single DB Writer
6. Job polling Orchestrator
7. Worker基底クラス
8. Job状態画面の最小版

## Phase B: Mail / Contact / LLM

1. Gmail Sync Worker
2. Pending Contact判定
3. Contact Registration Prefill Worker
4. Mail Importance Worker
5. Summary Worker
6. Case Decision Worker

## Phase C: External Operation

1. external_operations
2. External Operation Worker
3. Gmailスター付与
4. Gmail送信
5. Calendar作成
6. unknown手動解決画面

## Phase D: Maintenance

1. System Maintenance Case初期生成
2. Cost Limit監視
3. stale job検出
4. unknown external operation検出
5. Graceful Shutdown

## Phase E: 拡張

1. File Worker
2. Context Update Worker
3. Recurring Task Worker
4. Backup Worker
5. Handover Report Worker

---

# 16. 未確定・実装時判断事項

以下は実装中に調整する。

- Worker数初期値
- Gmail同期頻度
- LLMリトライ回数
- JSON修正プロンプトの具体文面
- Cost Limit金額・期間
- stale threshold
- Graceful Shutdown timeout
- File Workerの本文抽出方式
- バックアップWorkerの実装方式
- Handover Report Workerの初期対応範囲

---

# 17. 最重要確認事項

実装時に迷った場合は以下を優先する。

```text
1. Gmail送信を二重実行しない。
2. Calendar予定を二重作成しない。
3. ユーザー操作をLLM/Systemで上書きしない。
4. 業務DB更新はSingle DB Writerを通す。
5. Pending Contact中は重要度判定・Case判定・自動要約を止める。
6. Contact登録画面のLLM自動FillだけはPending中でも許可する。
7. unknown external operationは自動再実行しない。
8. stale jobは初期実装では手動確認する。
9. Cost Limit超過は黙って失敗せず、System Maintenance CaseにTaskを作る。
10. ユーザー操作への応答性を優先する。
```
