# CaseClosed DB詳細設計書

Version: 0.4  
作成日: 2026-05-22  
対象: 個人用案件管理Webアプリ CaseClosed  
関連文書: `CaseClosed_Overview_Design_v0.4.md`, `CaseClosed_Detailed_Design_v0.4.md`, `CaseClosed_LLM_Prompt_Design_v0.1.md`

---

## 0. 本書の位置づけ

本書は、CaseClosed のDB詳細設計書である。

概要設計・詳細設計で定義した概念を、SQLite上のテーブル、主要カラム、制約、削除方針、状態値、更新ルールとして具体化する。

本書は、初期migration、ORMモデル、Repository層、Single DB Writer、Job Worker、API設計の前提となる。

ただし、本書はDDLを完全固定するものではない。実装中に必要な補助カラム、index、履歴テーブルはmigrationで追加してよい。

---

# 1. DB設計基本方針

## 1.1 使用DB

初期実装では SQLite を用いる。

理由:

- 本人専用アプリであり、同時利用者数が少ない。
- ローカルファイルストレージとの相性がよい。
- バックアップ対象を単純化しやすい。
- Single DB Writer方針により、SQLiteの書き込み制約を吸収できる。

## 1.2 書き込み方針

業務テーブルへの更新は、原則として `write_requests` を経由し、Single DB Writer が実行する。

例外:

- `audit_logs` は Audit Log Writer が直接INSERTする。
- `system_logs` はシステム内部から直接INSERTしてよい。
- migration処理は直接DBを変更する。
- 初期セットアップ処理は直接DBを変更してよい。

## 1.3 読み込み方針

Read API はSQLiteを直接読む。

ただし、ユーザー操作直後には `write_requests` が未反映の場合があるため、APIレスポンスには必要に応じて `optimistic_state` を返し、UI側で即時反映する。

## 1.4 一次情報と解釈情報の分離

外部サービス由来の一次情報は、アプリ内の解釈・処理状態・LLM結果と混ぜない。

代表例:

```text
gmail_messages        Gmail由来の一次情報
mail_user_state       ユーザーが確定したメール状態
mail_auto_state       LLM/Systemが推定したメール状態
mail_summaries        LLM要約
```

## 1.5 ユーザー値と自動推定値の分離

ユーザーが明示的に設定した値は `user_*` またはユーザー状態テーブルに保存する。

LLM/Systemが推定した値は `auto_*`, `llm_*`, `system_*` または自動状態テーブルに保存する。

LLM/System由来のWrite Requestは、ユーザー確定値を上書きしてはならない。

## 1.6 effective値

effective値は原則としてDBに永続化しない。

Repository層またはVIEWで計算する。

例:

```text
effective_importance =
  user_importance
  > Contact skipped
  > rule_importance
  > external_importance
  > llm_importance
  > Pending
```

ただし、検索・表示性能上必要な場合は、将来的にキャッシュカラムを追加してよい。

## 1.7 論理削除方針

重要な業務データは原則として物理削除しない。

以下は `deleted_at` による論理削除とする。

- tasks
- mail_drafts
- contacts
- files
- file_links
- rules
- generated documents

Caseは削除しない。  
Caseは `closed_at` と `archived_at` で状態を表現する。

物理削除は、保守・運用画面から明示的に実行する場合のみ許可する。ただし、audit/event等から参照されるデータは原則として物理削除不可とする。

---

# 2. 命名・型・共通カラム

## 2.1 命名規則

- テーブル名は英語のsnake_case複数形。
- 主キーは `id`。
- 外部キーは `{entity}_id`。
- 日時は `_at` suffix。
- booleanは `is_*` または `has_*`。
- ユーザー確定値は `user_*`。
- 自動推定値は `auto_*`, `llm_*`, `rule_*`, `external_*`。

## 2.2 SQLite型方針

SQLite上では以下を基本とする。

```text
ID          TEXT    UUID/ULID推奨
Datetime    TEXT    ISO-8601 JST (`+09:00`)
Enum        TEXT
Boolean     INTEGER 0/1
JSON        TEXT    JSON文字列
Integer     INTEGER
Float       REAL
Hash        TEXT
```

## 2.3 共通カラム

多くの業務テーブルに以下を持たせる。

```text
id              TEXT PRIMARY KEY
created_at      TEXT NOT NULL
updated_at      TEXT NOT NULL
created_by      TEXT NULL   -- user/system/llm/import 等
updated_by      TEXT NULL
version         INTEGER NOT NULL DEFAULT 1
```

論理削除対象テーブルは以下を持つ。

```text
deleted_at      TEXT NULL
deleted_reason  TEXT NULL
deleted_by      TEXT NULL
```

## 2.4 versionカラム

`version` は楽観的競合制御に用いる。

- Write Request作成時に `base_version` を保存する。
- Single DB Writer実行時に現在versionと比較する。
- 競合時は安全側に倒し、原則として自動上書きしない。
- ユーザー操作由来の競合はUIに通知する。
- LLM/System由来の競合はdiscardまたは再計算Jobへ回す。

---

# 3. 状態値enum一覧

## 3.1 Case

```text
case_progress_status:
  not_started
  in_progress
  closed

case_ball_status:
  none
  user
  other
  date_wait
  stalled
```

Caseの削除状態は持たない。  
Caseの通常表示対象は `archived_at IS NULL` で判定する。

```text
open active case:
  closed_at IS NULL AND archived_at IS NULL

closed visible case:
  closed_at IS NOT NULL AND archived_at IS NULL

archived case:
  archived_at IS NOT NULL
```

## 3.2 Task

```text
task_status:
  not_started
  in_progress
  completed
  canceled
```

`completed` と `canceled` は閉じた状態とみなす。

## 3.3 Mail importance

```text
mail_importance:
  Pinned
  High
  Middle
  Low
  Skip
  Pending
```

内部保存値では小文字snake_caseにしてもよい。

```text
pinned
high
middle
low
skip
pending
```

ただしUI表示では `Pinned / High / Middle / Low / Skip / Pending` を用いる。

## 3.4 Mail process status

```text
mail_process_status:
  unprocessed
  processed
```

Skipはprocessedとは別概念である。

## 3.5 Contact

```text
contact_status:
  active
  skipped
  archived
```

```text
contact_kind:
  person
  mailing_list
```

```text
sender_resolution_mode:
  self
  reply_to
```

注意:

- `skipped` はContact単位のSkipである。
- Email Address単位のSkip状態は持たない。
- 「メールアドレス単独Skip」という概念は持たない。
- Fromだけを理由にSkipしたい場合は、そのメールアドレスをContactに登録し、Contact自体を `skipped` にする。
- `mail_importance_rules` は件名・本文・添付・Gmailラベル等を含むメール条件フィルタであり、アドレス単独Skipの代替としては使わない。
- `mailing_list` は特殊なContactとして扱う。
- `sender_resolution_mode = self` は、FromのML Contact自体を送信者として扱う。
- `sender_resolution_mode = reply_to` は、FromがML Contactだった場合に `Reply-To` を実送信者候補として扱う。
- `person` は `sender_resolution_mode = self` のみ許可する。

## 3.6 Email address resolution

```text
email_address_resolution_status:
  unresolved
  linked
```

Fromアドレスが `unresolved` の場合、当該メールはPending候補となる。

## 3.7 LLM policy

```text
llm_policy:
  allowed
  confirm_required
  forbidden
```

## 3.8 Job

```text
job_status:
  pending
  running
  succeeded
  failed
  canceled
  discarded
```

Stale running jobの自動復旧は初期実装では行わない。

## 3.9 Write Request

```text
write_request_status:
  pending
  applied
  discarded
  failed
```

## 3.10 External Operation

```text
external_operation_status:
  pending
  running
  succeeded
  failed
  unknown
  canceled
  manual_resolution_required
```

`unknown` は外部副作用が発生したか判断できない状態である。自動再実行してはならない。

---

# 4. Core / Case系テーブル

## 4.1 cases

案件本体を表す。

Caseは削除しない。完了は `closed_at`、通常一覧からの除外は `archived_at` で表現する。

### 主なカラム

```text
id                      TEXT PRIMARY KEY
name                    TEXT NOT NULL
description             TEXT NULL
progress_status          TEXT NOT NULL DEFAULT 'not_started'
ball_status              TEXT NOT NULL DEFAULT 'none'
closed_at                TEXT NULL
archived_at              TEXT NULL
is_system_case           INTEGER NOT NULL DEFAULT 0
system_case_key          TEXT NULL UNIQUE
created_at               TEXT NOT NULL
updated_at               TEXT NOT NULL
version                  INTEGER NOT NULL DEFAULT 1
```

### system_case_key

特殊Caseに用いる。

```text
inbox
system_maintenance
```

初期作成する特殊Case:

```text
Inbox / なんでも箱
システムメンテナンス
```

### 制約

- `closed_at` が入っていても `archived_at` はNULLでよい。
- `is_system_case = 1` のCaseは削除不可。
- `system_case_key = inbox` はClosed不可・Archive不可。
- `system_case_key = system_maintenance` は原則Archive不可。ただし将来変更可。

### Case期限について

Case本体には期限を持たせない。

Caseの期限表示・期限接近・期限超過は、配下Taskの未完了締切からRepository層またはVIEWで計算する。

例:

```text
case_effective_due_at =
  未完了Taskの due_at の最小値
```

## 4.2 case_tags

Caseに付与される自由タグ。

```text
id              TEXT PRIMARY KEY
case_id         TEXT NOT NULL REFERENCES cases(id)
tag             TEXT NOT NULL
created_at      TEXT NOT NULL
```

### 制約

```text
UNIQUE(case_id, tag)
```

## 4.3 case_events

Case内で起きた重要イベントを保存する。

将来のCase Context更新、引継ぎログ生成、RAG化の素材となる。

```text
id              TEXT PRIMARY KEY
case_id         TEXT NOT NULL REFERENCES cases(id)
event_type      TEXT NOT NULL
title           TEXT NOT NULL
summary         TEXT NULL
source_type     TEXT NULL   -- mail/task/calendar/file/manual/system/llm
source_id       TEXT NULL
occurred_at     TEXT NOT NULL
created_at      TEXT NOT NULL
metadata_json   TEXT NULL
```

### event_type例

```text
mail_received
mail_processed
mail_sent
task_created
task_completed
task_canceled
calendar_event_created
file_saved
case_context_updated
handover_generated
manual_note_added
```

## 4.4 case_context_versions

Case Contextの版管理。

```text
id                      TEXT PRIMARY KEY
case_id                 TEXT NOT NULL REFERENCES cases(id)
version_no              INTEGER NOT NULL
context_markdown         TEXT NOT NULL
source_event_until_at    TEXT NULL
llm_run_id               TEXT NULL REFERENCES llm_runs(id)
created_at               TEXT NOT NULL
created_by               TEXT NOT NULL
```

### 制約

```text
UNIQUE(case_id, version_no)
```

---

# 5. Task系テーブル

## 5.1 tasks

Task本体。

Taskは必ず1つのCaseに属する。Taskは論理削除する。

```text
id                      TEXT PRIMARY KEY
case_id                 TEXT NOT NULL REFERENCES cases(id)
parent_task_id           TEXT NULL REFERENCES tasks(id)
title                   TEXT NOT NULL
description             TEXT NULL
status                  TEXT NOT NULL DEFAULT 'not_started'
due_at                  TEXT NULL
estimate_minutes         INTEGER NULL
scheduled_minutes        INTEGER NOT NULL DEFAULT 0
worked_minutes           INTEGER NOT NULL DEFAULT 0
source_type              TEXT NULL   -- manual/mail/llm/recurring/system
source_id                TEXT NULL
completed_at             TEXT NULL
canceled_at              TEXT NULL
canceled_reason          TEXT NULL
deleted_at               TEXT NULL
deleted_reason           TEXT NULL
created_at               TEXT NOT NULL
updated_at               TEXT NOT NULL
version                  INTEGER NOT NULL DEFAULT 1
```

### 状態制約

- `status = completed` の場合、`completed_at` を持つ。
- `status = canceled` の場合、`canceled_at` を持つ。
- `completed` と `canceled` は閉じた状態。
- `deleted_at IS NOT NULL` のTaskは通常一覧に表示しない。

### 親Task完了制約

未完了の子Taskが存在する場合、親Taskは `completed` にできない。

未完了とは以下を指す。

```text
status NOT IN ('completed', 'canceled')
AND deleted_at IS NULL
```

### Case Closed制約

CaseをClosedにするには、当該Case配下の全Taskが以下を満たす必要がある。

```text
status IN ('completed', 'canceled')
OR deleted_at IS NOT NULL
```

ただし、削除済みTaskをClosed判定から除外するかどうかはRepository層で明確に実装する。推奨は、削除済みTaskは誤作成扱いとしてClosed判定から除外する。

## 5.2 task_links

Taskと他エンティティの関連。

```text
id              TEXT PRIMARY KEY
task_id         TEXT NOT NULL REFERENCES tasks(id)
linked_type     TEXT NOT NULL  -- mail/calendar_event/file/contact/external_url
linked_id       TEXT NULL
url             TEXT NULL
label           TEXT NULL
created_at      TEXT NOT NULL
```

## 5.3 task_suggestions

LLMが生成したTask候補。

正式Taskではない。

```text
id                  TEXT PRIMARY KEY
case_id             TEXT NULL REFERENCES cases(id)
source_type          TEXT NOT NULL   -- mail/case/task/manual
source_id            TEXT NOT NULL
suggested_title      TEXT NOT NULL
suggested_detail     TEXT NULL
suggested_due_at     TEXT NULL
suggested_estimate_minutes INTEGER NULL
suggested_priority_hint TEXT NULL
suggestion_kind      TEXT NOT NULL DEFAULT 'task'  -- task/subtask/preparation/reminder
parent_task_id       TEXT NULL REFERENCES tasks(id)
llm_run_id           TEXT NULL REFERENCES llm_runs(id)
status               TEXT NOT NULL DEFAULT 'pending'
accepted_task_id     TEXT NULL REFERENCES tasks(id)
created_at           TEXT NOT NULL
updated_at           TEXT NOT NULL
```

### status

```text
pending
accepted
rejected
edited_and_accepted
```

## 5.4 task_work_blocks

Google Calendar上に配置した作業ブロックとの対応。

```text
id                          TEXT PRIMARY KEY
task_id                     TEXT NOT NULL REFERENCES tasks(id)
calendar_event_link_id       TEXT NULL REFERENCES calendar_event_links(id)
planned_minutes              INTEGER NOT NULL
actual_minutes               INTEGER NULL
started_at                   TEXT NULL
ended_at                     TEXT NULL
created_at                   TEXT NOT NULL
```

ポモドーロタイマーとの連携は後続拡張扱いとするが、将来ここに作業セッションを関連づけられるようにする。

---

# 6. Gmail / Mail系テーブル

## 6.1 gmail_threads

Gmail threadの一次情報。

```text
id                          TEXT PRIMARY KEY
gmail_thread_id              TEXT NOT NULL UNIQUE
history_id                   TEXT NULL
subject_latest               TEXT NULL
first_message_at             TEXT NULL
last_message_at              TEXT NULL
created_at                   TEXT NOT NULL
updated_at                   TEXT NOT NULL
```

## 6.2 gmail_messages

Gmail messageの一次情報。

一度読み込んだメールは、原則として再取得・再監視しない。  
そのため、Gmailスター等の外部状態も読み込み時点の値として保存する。

```text
id                          TEXT PRIMARY KEY
gmail_message_id              TEXT NOT NULL UNIQUE
gmail_thread_id               TEXT NOT NULL
thread_id                     TEXT NOT NULL REFERENCES gmail_threads(id)
direction                     TEXT NOT NULL   -- inbound/outbound
from_address                  TEXT NULL
from_name                     TEXT NULL
sender_address                TEXT NULL
reply_to_json                 TEXT NULL
to_json                       TEXT NULL
cc_json                       TEXT NULL
bcc_json                      TEXT NULL
list_id                       TEXT NULL
message_id_header             TEXT NULL
in_reply_to_header            TEXT NULL
references_json               TEXT NULL
address_headers_json          TEXT NULL
subject                       TEXT NULL
snippet                       TEXT NULL
body_text                     TEXT NULL
body_html                     TEXT NULL
internal_date                 TEXT NULL
received_at                   TEXT NULL
sent_at                       TEXT NULL
gmail_link                    TEXT NULL
gmail_labels_json             TEXT NULL
initial_is_starred            INTEGER NOT NULL DEFAULT 0
initial_is_unread             INTEGER NULL
has_attachments               INTEGER NOT NULL DEFAULT 0
raw_size_bytes                INTEGER NULL
created_at                    TEXT NOT NULL
updated_at                    TEXT NOT NULL
```

### 注意

- Gmail本文はアプリ内表示・LLM処理のためDBに保存してよい。
- ただし `llm_runs` には入力全文を保存しない。
- Gmail既読/未読は変更しない。
- Gmailスター解除は監視しない。
- `initial_is_starred = 1` なら `external_importance = high` の根拠となる。

### メール識別子・送信者ヘッダ

- アプリ内の主キーは `gmail_messages.id` とする。
- Gmail由来の `gmail_message_id` は外部サービス上の不変IDとして `UNIQUE` 制約を持つ。
- RFC 5322上の `Message-ID` ヘッダは `message_id_header` に保存し、Gmail API上の `gmail_message_id` とは別物として扱う。
- `gmail_thread_id` / `thread_id` はスレッド集約用であり、メール単体の主キーとして使わない。

送信者・返信先の特定は `from_address` だけで確定しない。メーリングリスト、代理送信、`Reply-To` 変更、Reply All時の参加者増加に備え、Gmailから取得できる住所系ヘッダは一次情報として保存する。

- `from_address` / `from_name`
- `sender_address`
- `reply_to_json`
- `to_json` / `cc_json` / `bcc_json`
- `list_id`
- `message_id_header` / `in_reply_to_header` / `references_json`
- `address_headers_json`

Phase 4 v1のPending判定は従来どおり `from_address` を対象とする。ただし、後続Phaseで `effective_sender_address` やReply All候補を推定できるよう、上記ヘッダは破棄しない。

`list_id` が存在する場合、そのメールはメーリングリスト由来である可能性が高い。Phase 4 v1では `list_id` の存在だけでPendingを回避しないが、後続PhaseでContact/Tag/Case推定の補助情報として使う。

## 6.3 gmail_attachments_meta

Gmail添付メタ情報。

```text
id                          TEXT PRIMARY KEY
message_id                   TEXT NOT NULL REFERENCES gmail_messages(id)
gmail_attachment_id           TEXT NULL
filename                     TEXT NOT NULL
mime_type                    TEXT NULL
size_bytes                   INTEGER NULL
is_downloaded                INTEGER NOT NULL DEFAULT 0
file_id                      TEXT NULL REFERENCES files(id)
created_at                   TEXT NOT NULL
updated_at                   TEXT NOT NULL
```

添付実体は、条件を満たした場合のみ取得する。

取得条件:

- High / Middleメールの添付
- Caseが推定できたメールの添付
- ユーザーが明示的に取得した添付

## 6.4 mail_user_state

メールに対するユーザー確定状態。

```text
id                          TEXT PRIMARY KEY
message_id                   TEXT NOT NULL UNIQUE REFERENCES gmail_messages(id)
user_importance              TEXT NULL
process_status               TEXT NOT NULL DEFAULT 'unprocessed'
processed_at                 TEXT NULL
processed_reason             TEXT NULL
primary_case_id              TEXT NULL REFERENCES cases(id)
manual_case_set_at            TEXT NULL
user_note                    TEXT NULL
created_at                   TEXT NOT NULL
updated_at                   TEXT NOT NULL
version                      INTEGER NOT NULL DEFAULT 1
```

### user_importance

ユーザーが明示的に指定した重要度。

```text
pinned
high
middle
low
skip
```

ユーザーは `pending` を指定しない。

### process_status

`processed` になる操作:

- Gmail送信
- タスク化
- 予定化
- 手動で処理済み
- 不要として処理済み

`processed` にならない操作:

- 要約を読む
- 本文を開く
- 返信草案を作る
- 案件に紐づける
- 新規案件を作る
- Contact確認

## 6.5 mail_auto_state

メールに対する外部・ルール・LLM・System推定状態。

```text
id                          TEXT PRIMARY KEY
message_id                   TEXT NOT NULL UNIQUE REFERENCES gmail_messages(id)
external_importance           TEXT NULL
rule_importance               TEXT NULL
rule_id                       TEXT NULL REFERENCES mail_importance_rules(id)
llm_importance                TEXT NULL
llm_importance_run_id          TEXT NULL REFERENCES llm_runs(id)
system_importance             TEXT NULL
pending_reason                TEXT NULL
pending_from_address_id        TEXT NULL REFERENCES contact_email_addresses(id)
auto_case_decision             TEXT NULL
auto_case_id                  TEXT NULL REFERENCES cases(id)
auto_case_run_id               TEXT NULL REFERENCES llm_runs(id)
created_at                    TEXT NOT NULL
updated_at                    TEXT NOT NULL
version                       INTEGER NOT NULL DEFAULT 1
```

### external_importance

Gmail読み込み時にスターが付いていた場合に `high` とする。

```text
initial_is_starred = 1 -> external_importance = high
```

Gmail側で後からスター解除されても、アプリ内の `external_importance` は下げない。

### Pending条件

PendingはFromアドレスのみを対象とする。

条件:

```text
from_address が Contactsに未登録
```

Pending中は以下を止める。

- LLM重要度判定
- Case候補抽出
- LLM Case判定
- 自動要約

メーリングリスト、no-replyもContactsに情報がなければPending扱いとする。不要な送信元であっても、Fromアドレス単独Skipではなく、Contact登録後にContactを `skipped` にする。

Pending中であっても、Contact登録画面の自動Fillを目的とするLLM処理 `contact_registration_prefill` は例外的に実行可能とする。

### effective_importance計算

```text
user_importance
> Contact skipped
> rule_importance
> external_importance
> llm_importance
> system_importance
> Pending
```

ただし `Pinned` はユーザーまたは重要度フィルタのみが付与可能。LLMは出力不可。

## 6.6 case_mail_links

Caseが保持するメール集合を表現する関連テーブル。

概念上は「メールが案件に紐づく」ではなく、「Caseが関連メールを持つ」と捉える。Gmail本文・スレッド等の一次情報は `gmail_messages` / `gmail_threads` に保持し、Case側から参照する。

自動判定では、1メールにつき主Caseを1つ作る。ユーザー手動操作では、同じメールを別Caseのメール集合へコピー表示できるようにする。

```text
id                  TEXT PRIMARY KEY
case_id              TEXT NOT NULL REFERENCES cases(id)
message_id           TEXT NOT NULL REFERENCES gmail_messages(id)
link_role            TEXT NOT NULL   -- primary/copy
source               TEXT NOT NULL   -- user/llm/rule/system
created_at           TEXT NOT NULL
created_by           TEXT NOT NULL
```

### 制約

- `link_role = primary` は1メールにつき1つまで。
- `link_role = copy` は複数可。
- 1つのCaseは複数のメールを持てる。
- `Pinned` メールはCase候補抽出・Case判定対象外。ただしユーザー手動リンクは可。

## 6.7 mail_summaries

メール単位のLLM要約。

```text
id                  TEXT PRIMARY KEY
message_id           TEXT NOT NULL REFERENCES gmail_messages(id)
summary_text          TEXT NOT NULL
action_required       TEXT NULL
deadline_text         TEXT NULL
next_action           TEXT NULL
key_points_json       TEXT NULL
language              TEXT NOT NULL DEFAULT 'ja'
llm_run_id            TEXT NULL REFERENCES llm_runs(id)
created_at            TEXT NOT NULL
```

High / Middleメールのみ自動生成する。

Lowは自動要約しない。手動要約は可。

## 6.8 mail_thread_summaries

Case入りしたスレッド全体の要約。

```text
id                  TEXT PRIMARY KEY
thread_id            TEXT NOT NULL REFERENCES gmail_threads(id)
case_id              TEXT NULL REFERENCES cases(id)
summary_text          TEXT NOT NULL
llm_run_id            TEXT NULL REFERENCES llm_runs(id)
created_at            TEXT NOT NULL
```

## 6.9 mail_drafts

アプリ内メール草案。

Gmail Draftではない。

```text
id                      TEXT PRIMARY KEY
draft_type               TEXT NOT NULL   -- reply/new_mail
source_message_id         TEXT NULL REFERENCES gmail_messages(id)
case_id                  TEXT NULL REFERENCES cases(id)
to_json                  TEXT NULL
cc_json                  TEXT NULL
bcc_json                 TEXT NULL
subject                 TEXT NOT NULL
body_text                TEXT NOT NULL
status                  TEXT NOT NULL DEFAULT 'draft'
llm_run_id               TEXT NULL REFERENCES llm_runs(id)
external_operation_id     TEXT NULL REFERENCES external_operations(id)
deleted_at               TEXT NULL
created_at               TEXT NOT NULL
updated_at               TEXT NOT NULL
version                  INTEGER NOT NULL DEFAULT 1
```

### status

```text
draft
sent
discarded
failed
```

Gmail送信中の不明状態はDraftではなく `external_operations.status = unknown` で扱う。

---

# 7. Contact系テーブル

## 7.1 contacts

人物管理。

Google Contactsとは完全分離する。

```text
id                  TEXT PRIMARY KEY
display_name         TEXT NOT NULL
memo                 TEXT NULL
status              TEXT NOT NULL DEFAULT 'active'
kind                TEXT NOT NULL DEFAULT 'person'
sender_resolution_mode TEXT NOT NULL DEFAULT 'self'
mailing_list_recipient_expression TEXT NULL
deleted_at           TEXT NULL
created_at           TEXT NOT NULL
updated_at           TEXT NOT NULL
version              INTEGER NOT NULL DEFAULT 1
```

### status

```text
active
skipped
archived
```

`skipped` Contactから来たメールは重要度判定前にSkip扱いとする。  
ただし、個別メールの `user_importance` がある場合はユーザー指定を優先する。

### kind

```text
person
mailing_list
```

`mailing_list` はメーリングリスト、ニュース配信、システム通知など、人物ではなく配送経路・発信元枠として扱う特殊Contactである。

UI・運用上は通常Contactと混ぜない。通常Contact一覧、通常Contact用カスタムタブ、通常Contact向けLLMメモ/Context更新の対象からは除外し、Mailing List専用タブ・専用詳細で扱う。

Mailing List Contactは以下の制約を持つ。

- 1 Contact = 1メールアドレス。
- メールアドレスは常に `active` / `primary` とし、個別のRemove/Deactivate/Set Primary操作は持たない。
- Contact tagsは持たない。
- `mailing-list` は予約語として通常Contactタグにも使わない。
- 必要に応じて `mailing_list_recipient_expression` に、送信先アドレス設定時の置き換え対象となるタグ式を保存する。
- memoは持てる。ただしLLMによる自動更新対象にはしない。
- 関連Caseは持てる。

### sender_resolution_mode

```text
self
reply_to
```

- `self`: FromのContact自体を送信者として扱う。Neuromail等、誰が内部送信者かを追わず「この送信元から来た」と分かればよいケースで使う。
- `reply_to`: FromがML Contactだった場合、`Reply-To` を実送信者候補として扱う。学内委員会ML等、実際の送信者を把握して対応したいケースで使う。

`person` Contactは `self` のみ許可する。`mailing_list` Contactは `self` / `reply_to` のどちらも選択できる。

### mailing_list_recipient_expression

Mailing Listアドレスを宛先として使う場合に、将来そのアドレスを特定タグ条件のContact群へ置き換えるためのタグ式。

例:

```text
{筑波大学&学生&!KDE}
```

Phase 3時点では保存・表示のみでよい。実際の宛先展開はメール送信機能実装時に扱う。

## 7.2 contact_email_addresses

Contactとメールアドレスの対応、および未解決Fromアドレスを保存する。

```text
id                      TEXT PRIMARY KEY
contact_id               TEXT NULL REFERENCES contacts(id)
email_address            TEXT NOT NULL
normalized_email_address  TEXT NOT NULL UNIQUE
resolution_status         TEXT NOT NULL DEFAULT 'unresolved'
status                    TEXT NOT NULL DEFAULT 'active'
has_inbound_message_history INTEGER NOT NULL DEFAULT 0
is_primary               INTEGER NOT NULL DEFAULT 0
source                   TEXT NULL   -- gmail/manual/import
first_seen_at             TEXT NULL
last_seen_at              TEXT NULL
deactivated_at            TEXT NULL
deleted_at                TEXT NULL
created_at               TEXT NOT NULL
updated_at               TEXT NOT NULL
version                  INTEGER NOT NULL DEFAULT 1
```

### resolution_status

```text
unresolved
linked
```

### status

```text
active
inactive
deleted
```

注意:

- `skipped_address` は用意しない。
- メールアドレス単独Skipという概念自体を持たない。
- Fromだけを理由にSkipしたい場合は、そのメールアドレスをContactに紐づけ、Contact側を `skipped` にする。
- `resolution_status = linked` の場合、`contact_id` はNOT NULLであるべき。
- `contact_email_addresses` は正規化メールアドレスごとのcanonical rowとして扱う。
- `status = active` は現在そのContactで使用中のメールアドレスである。
- `status = inactive` は現在は送信先として使わないが、過去メール・新規受信メールのFrom Contact解決には使うメールアドレスである。
- `has_inbound_message_history = 1` は、このメールアドレスがFromとしてDB内メールに一度でも登場したことを示す。
- Gmail Sync等でFromアドレスを観測した時点で `has_inbound_message_history = 1` にする。削除時にメールテーブルを全走査しない。
- `has_inbound_message_history = 1` の場合、通常操作では物理削除せず `status = inactive`, `is_primary = 0`, `deactivated_at = now` とする。
- `has_inbound_message_history = 0` の場合は、typo等の誤登録として物理削除してよい。
- `inactive` アドレスが別Contactへ追加・移動された場合は、新規rowを作らず、同じ `normalized_email_address` のrowを再利用して `contact_id` を付け替える。`active` / `inactive` 状態と `deactivated_at` は維持する。
- `inactive` アドレスは送信先候補、返信先候補、Primary指定の対象にしない。
- `kind = mailing_list` のContactに紐づくメールアドレスは、常に `active` / `is_primary = 1` とし、個別のRemove/Deactivate/Set Primary操作を許可しない。

### Contact削除

Contactは、紐づく全メールアドレスが物理削除可能な場合のみ削除できる。

- 全メールアドレスの `has_inbound_message_history = 0` なら、メールアドレスを削除し、Contact本体は `deleted_at` を設定して通常一覧から除外する。
- 1件でも `has_inbound_message_history = 1` があれば、Contact本体削除は不可とする。

## 7.3 contact_registration_suggestions

未解決FromアドレスのContact登録画面を自動FillするためのLLM候補を保存する。

Pending中は通常の重要度判定・Case判定・自動要約を止めるが、Contact登録支援だけは例外的に実行可能とする。これは初期運用時にPendingが大量発生する負担を下げるためである。

```text
id                      TEXT PRIMARY KEY
email_address_id        TEXT NOT NULL REFERENCES contact_email_addresses(id)
source_message_id       TEXT NULL REFERENCES gmail_messages(id)
suggested_display_name  TEXT NULL
suggested_organization  TEXT NULL
suggested_role          TEXT NULL
suggested_tags_json     TEXT NULL
suggested_memo          TEXT NULL
suggested_skip_reason   TEXT NULL
confidence              REAL NULL
llm_run_id              TEXT NULL REFERENCES llm_runs(id)
status                  TEXT NOT NULL DEFAULT 'suggested'
created_at              TEXT NOT NULL
updated_at              TEXT NOT NULL
```

### status

```text
suggested
adopted
edited_and_adopted
rejected
superseded
```

### 入力に使う情報

- From表示名
- Fromメールアドレス
- メール件名
- メール本文
- 署名らしき部分
- To/Cc
- 既存Contactタグ一覧

### 用途

Contact登録画面で以下を事前入力する。

- 表示名
- 所属・役割のメモ
- 候補タグ
- skippedにすべき可能性の説明

ただし、LLM候補は正式Contactではない。ユーザーが採用・編集・破棄するまで `contacts` には反映しない。

採用時:

- Contact作成時に `source_suggestion_id` が指定された場合、この候補を採用済みにする。
- 候補値をそのまま採用した場合は `adopted`、ユーザー編集後に採用した場合は `edited_and_adopted` とする。

## 7.4 contact_tags

Contactに付与される自由タグ。

```text
id              TEXT PRIMARY KEY
contact_id       TEXT NOT NULL REFERENCES contacts(id)
tag             TEXT NOT NULL
created_at      TEXT NOT NULL
```

### 制約

```text
UNIQUE(contact_id, tag)
```

制約:

- `mailing-list` は予約語として使用不可。
- `kind = mailing_list` のContactにはタグを付与しない。Mailing Listの宛先置き換え条件は `contacts.mailing_list_recipient_expression` に保存する。

## 7.5 contact_case_links

ContactとCaseの関連。

```text
id              TEXT PRIMARY KEY
contact_id       TEXT NOT NULL REFERENCES contacts(id)
case_id          TEXT NOT NULL REFERENCES cases(id)
relation_type    TEXT NULL
source           TEXT NOT NULL   -- user/system/llm
created_at       TEXT NOT NULL
```

## 7.6 contact_context_versions

Contact Contextの版管理。

```text
id                      TEXT PRIMARY KEY
contact_id               TEXT NOT NULL REFERENCES contacts(id)
version_no               INTEGER NOT NULL
context_markdown          TEXT NOT NULL
llm_run_id                TEXT NULL REFERENCES llm_runs(id)
created_at               TEXT NOT NULL
created_by               TEXT NOT NULL
```

## 7.7 contact_group_aliases

タグAND指定などの宛先グループエイリアス。

```text
id                      TEXT PRIMARY KEY
alias_name               TEXT NOT NULL UNIQUE
tag_expression           TEXT NOT NULL
expanded_preview_json     TEXT NULL
memo                     TEXT NULL
created_at               TEXT NOT NULL
updated_at               TEXT NOT NULL
```

例:

```text
KDE&秘書
CCS&委員会
```

## 7.8 contact_merge_history

Contact統合履歴。

```text
id                  TEXT PRIMARY KEY
source_contact_id    TEXT NOT NULL
target_contact_id    TEXT NOT NULL REFERENCES contacts(id)
merged_at            TEXT NOT NULL
merged_by            TEXT NOT NULL
snapshot_json        TEXT NULL
```

---

# 8. Calendar系テーブル

## 8.1 calendar_event_links

Google Calendar予定とCase/Task/Mailの対応。

予定の正本はGoogle Calendarであり、アプリ側にはIDと関連情報を持つ。

```text
id                          TEXT PRIMARY KEY
google_calendar_id           TEXT NULL
google_event_id              TEXT NOT NULL
case_id                      TEXT NULL REFERENCES cases(id)
task_id                      TEXT NULL REFERENCES tasks(id)
source_message_id             TEXT NULL REFERENCES gmail_messages(id)
title_snapshot               TEXT NULL
start_at_snapshot             TEXT NULL
end_at_snapshot               TEXT NULL
location_snapshot             TEXT NULL
description_snapshot          TEXT NULL
external_operation_id          TEXT NULL REFERENCES external_operations(id)
created_at                   TEXT NOT NULL
updated_at                   TEXT NOT NULL
```

### 注意

Google Calendarの予定本文には以下を記載する。

- Case名
- Task名
- 元メール件名
- 元メールのGmailリンク

アプリ内リンクは入れない。

## 8.2 calendar_event_candidates

メール本文等からLLMが抽出したGoogle Calendar登録前の予定候補。

予定候補は、ユーザーが確認・編集・承認するまでGoogle Calendarへ登録しない。

```text
id                          TEXT PRIMARY KEY
source_message_id             TEXT NULL REFERENCES gmail_messages(id)
case_id                      TEXT NULL REFERENCES cases(id)
task_id                      TEXT NULL REFERENCES tasks(id)
title                       TEXT NOT NULL
start_at                    TEXT NULL
end_at                      TEXT NULL
timezone                    TEXT NULL DEFAULT 'Asia/Tokyo'
location                    TEXT NULL
description                 TEXT NULL
source_text                 TEXT NULL
confidence                  REAL NULL
llm_run_id                  TEXT NULL REFERENCES llm_runs(id)
status                      TEXT NOT NULL DEFAULT 'pending'
created_at                  TEXT NOT NULL
updated_at                  TEXT NOT NULL
```

### status

```text
pending
accepted
edited_and_accepted
rejected
superseded
```

承認後、Google Calendar作成 `external_operations` を作成し、成功後に `calendar_event_links` を作成する。

---

# 9. File / Storage系テーブル

## 9.1 storage_objects

物理保存オブジェクト。

```text
id                      TEXT PRIMARY KEY
storage_path             TEXT NOT NULL UNIQUE
sha256                   TEXT NULL
size_bytes               INTEGER NULL
mime_type                TEXT NULL
created_at               TEXT NOT NULL
```

物理配置はIDベースとする。

例:

```text
storage/objects/ab/cd/{storage_object_id}
```

## 9.2 files

UI上のファイル概念。

```text
id                      TEXT PRIMARY KEY
current_storage_object_id TEXT NULL REFERENCES storage_objects(id)
original_filename        TEXT NOT NULL
display_filename         TEXT NULL
origin                  TEXT NOT NULL   -- mail/upload/generated/external_link
origin_message_id         TEXT NULL REFERENCES gmail_messages(id)
external_url             TEXT NULL
llm_policy               TEXT NOT NULL DEFAULT 'confirm_required'
trashed_at               TEXT NULL
purged_at                TEXT NULL
created_at               TEXT NOT NULL
updated_at               TEXT NOT NULL
version                  INTEGER NOT NULL DEFAULT 1
```

### origin

```text
mail
upload
generated
external_link
```

### 削除

- 通常削除は `trashed_at` を入れる。
- 物理削除は `purged_at` を入れる。
- 物理削除後もDBメタ情報は残す。

## 9.3 file_versions

ファイルのバージョン履歴。

```text
id                      TEXT PRIMARY KEY
file_id                  TEXT NOT NULL REFERENCES files(id)
storage_object_id         TEXT NOT NULL REFERENCES storage_objects(id)
version_no               INTEGER NOT NULL
created_at               TEXT NOT NULL
created_by               TEXT NOT NULL
note                     TEXT NULL
```

### 制約

```text
UNIQUE(file_id, version_no)
```

## 9.4 file_links

ファイルとCase/Task/Mail等の関連。

```text
id                  TEXT PRIMARY KEY
file_id              TEXT NOT NULL REFERENCES files(id)
linked_type          TEXT NOT NULL   -- case/task/mail/contact
linked_id            TEXT NOT NULL
link_source          TEXT NOT NULL   -- user/system/mail_attachment/generated
created_at           TEXT NOT NULL
deleted_at           TEXT NULL
```

メール添付由来ファイルは、添付元メールのCaseリンクに応じて表示Caseが変わる。  
そのため、メール添付ファイルについては `file_links` を固定所属として使うのではなく、メールリンク経由の表示も許す。

## 9.5 file_security_rules

ファイル名・送信者・Caseタグ等に基づくLLM policy判定ルール。

```text
id                      TEXT PRIMARY KEY
name                    TEXT NOT NULL
condition_json           TEXT NOT NULL
llm_policy               TEXT NOT NULL
priority                 INTEGER NOT NULL
is_enabled               INTEGER NOT NULL DEFAULT 1
created_at               TEXT NOT NULL
updated_at               TEXT NOT NULL
```

## 9.6 file_summaries

ファイル本文をLLMに投入して生成した要約。

`llm_policy` により実行可否を制御する。

```text
id                      TEXT PRIMARY KEY
file_id                  TEXT NOT NULL REFERENCES files(id)
summary_text             TEXT NOT NULL
key_points_json          TEXT NULL
action_items_json        TEXT NULL
sensitive_content_warning INTEGER NOT NULL DEFAULT 0
llm_run_id               TEXT NULL REFERENCES llm_runs(id)
created_at               TEXT NOT NULL
```

---

# 10. LLM系テーブル

## 10.1 prompt_versions

LLMプロンプトと出力schemaの版管理。

プロンプト本文の最終形は実装中に調整してよいが、function_typeごとにversion管理する。

```text
id                          TEXT PRIMARY KEY
function_type                TEXT NOT NULL
version_no                   INTEGER NOT NULL
system_prompt_template        TEXT NULL
user_prompt_template          TEXT NULL
retry_prompt_template         TEXT NULL
output_schema_json            TEXT NULL
default_model_name            TEXT NULL
default_provider_name         TEXT NULL
temperature                   REAL NULL
is_active                    INTEGER NOT NULL DEFAULT 1
memo                         TEXT NULL
created_at                   TEXT NOT NULL
updated_at                   TEXT NOT NULL
```

### 制約

```text
UNIQUE(function_type, version_no)
```

### function_type例

```text
mail_importance_classification
contact_registration_prefill
mail_summary_ja
mail_case_selection
mail_thread_summary
reply_draft_generation
new_mail_draft_generation
mail_task_suggestion
subtask_suggestion
calendar_candidate_extraction
preparation_task_suggestion
reminder_mail_generation
case_context_update
contact_context_update
file_security_meta_classification
file_summary
handover_log_generation
```

## 10.2 llm_instruction_rules

ユーザーが登録するLLM追加指示。

送信者、Contactタグ、Caseタグ、件名、本文キーワード等に応じて、各LLM機能へ追加指示を適用する。

```text
id                      TEXT PRIMARY KEY
name                    TEXT NOT NULL
condition_json           TEXT NOT NULL
instruction_text         TEXT NOT NULL
function_types_json      TEXT NULL
priority_order           INTEGER NOT NULL DEFAULT 100
is_enabled               INTEGER NOT NULL DEFAULT 1
created_at               TEXT NOT NULL
updated_at               TEXT NOT NULL
deleted_at               TEXT NULL
version                  INTEGER NOT NULL DEFAULT 1
```

### condition_json例

```json
{
  "contact_tags_any": ["学生"],
  "subject_contains": ["相談", "確認"],
  "case_tags_any": ["授業"]
}
```

### function_types_json例

```json
[
  "mail_summary_ja",
  "reply_draft_generation",
  "mail_task_suggestion"
]
```

複数ルールが一致する場合、`priority_order` の小さい順に適用する。

## 10.3 llm_runs

全LLM実行履歴。

プロンプトエンジニアリング、失敗解析、コスト管理のために保存する。  
ただし、メール本文全文・ファイル本文全文・LLM入力全文は保存しない。

```text
id                          TEXT PRIMARY KEY
function_type                TEXT NOT NULL
provider_name                TEXT NOT NULL
model_name                   TEXT NOT NULL
prompt_version_id             TEXT NULL REFERENCES prompt_versions(id)
input_hash                   TEXT NULL
input_source_json             TEXT NOT NULL
input_diagnostic_json         TEXT NULL
applied_instruction_rule_ids_json TEXT NULL
output_json                  TEXT NULL
output_text_preview           TEXT NULL
status                       TEXT NOT NULL
error_type                   TEXT NULL
error_message                TEXT NULL
retry_count                  INTEGER NOT NULL DEFAULT 0
max_retry_count               INTEGER NOT NULL DEFAULT 3
prompt_tokens                INTEGER NULL
completion_tokens            INTEGER NULL
total_tokens                 INTEGER NULL
estimated_cost               REAL NULL
started_at                   TEXT NULL
finished_at                  TEXT NULL
created_at                   TEXT NOT NULL
```

### status

```text
pending
running
succeeded
failed
canceled
```

### input_source_json

入力全文ではなく、入力を再構成するための参照情報を保存する。

例:

```json
{
  "message_ids": ["..."],
  "case_id": "...",
  "case_context_version_id": "...",
  "contact_context_version_id": "...",
  "file_ids": [],
  "user_additional_prompt_hash": "..."
}
```

### input_diagnostic_json

プロンプトエンジニアリングに必要な範囲で、全文ではない診断情報を保存する。

例:

```json
{
  "mail_count": 1,
  "has_thread_context": true,
  "included_fields": ["subject", "from", "body_text", "attachments_meta"],
  "input_character_count": 12000,
  "body_char_count": 9500,
  "truncated": false,
  "schema_name": "mail_importance_v2",
  "normalization_version": "2026-05-22",
  "instruction_profile": ["student_mail", "concise_reply"]
}
```

### input_hash

`input_hash` は、LLMに渡した入力を正規化したうえで算出する。

正規化対象:

- system prompt
- user prompt
- prompt_version
- user追加プロンプト
- 入力本文・Context・候補リスト
- 出力schema

ハッシュ算出後、入力全文は保存しない。

### リトライ方針

JSON不正、schema不一致、必須フィールド欠落、enum違反など機械的失敗はリトライする。

リトライ時には、`retry_prompt_template` を用いて「必ず指定JSON schemaに従う」等の修正を加えてよい。

人間が見て品質が低いLLM出力は、原則として失敗扱いしない。  
ユーザーが手動修正できる形で提示する。

### Cost Limit超過時

LLMコスト上限を超過しそうな場合、以下を行う。

1. 対象LLM処理を停止または延期する。
2. `system_maintenance` Case配下に確認Taskを自動生成する。
3. system_logsに記録する。

## 10.4 handover_logs

LLMにより生成されたCase引継ぎログの編集前・確定前メタ情報。

確定版はGenerated Fileとして `files` に保存する。

```text
id                          TEXT PRIMARY KEY
case_id                      TEXT NOT NULL REFERENCES cases(id)
title                       TEXT NOT NULL
markdown_body                TEXT NOT NULL
contains_sensitive_information INTEGER NOT NULL DEFAULT 0
sensitivity_notes_json        TEXT NULL
unresolved_items_json         TEXT NULL
llm_run_id                   TEXT NULL REFERENCES llm_runs(id)
status                       TEXT NOT NULL DEFAULT 'draft'
generated_file_id             TEXT NULL REFERENCES files(id)
created_at                   TEXT NOT NULL
updated_at                   TEXT NOT NULL
```

### status

```text
draft
confirmed
rejected
superseded
```

---

# 11. Jobs / Queue / Writer系テーブル

## 11.1 jobs

非同期処理Job。

```text
id                      TEXT PRIMARY KEY
job_type                 TEXT NOT NULL
priority                 INTEGER NOT NULL DEFAULT 100
status                  TEXT NOT NULL DEFAULT 'pending'
payload_json             TEXT NOT NULL
result_json              TEXT NULL
error_type               TEXT NULL
error_message            TEXT NULL
retry_count              INTEGER NOT NULL DEFAULT 0
max_retries              INTEGER NOT NULL DEFAULT 3
locked_by                TEXT NULL
locked_at                TEXT NULL
heartbeat_at             TEXT NULL
available_at             TEXT NULL
started_at               TEXT NULL
finished_at              TEXT NULL
created_at               TEXT NOT NULL
updated_at               TEXT NOT NULL
```

### 通常失敗とstale job

通常失敗:

- `max_retries` まで自動リトライしてよい。

サーバーダウン等で `running` のまま残ったstale job:

- 初期実装では自動再実行しない。
- 保守・運用画面で確認対象とする。

## 11.2 write_requests

業務DB更新要求。

```text
id                      TEXT PRIMARY KEY
source                  TEXT NOT NULL   -- user/llm/system/worker
priority                INTEGER NOT NULL DEFAULT 50
operation_type           TEXT NOT NULL
entity_type              TEXT NOT NULL
entity_id                TEXT NULL
base_version             INTEGER NULL
payload_json             TEXT NOT NULL
status                  TEXT NOT NULL DEFAULT 'pending'
error_type               TEXT NULL
error_message            TEXT NULL
created_at               TEXT NOT NULL
applied_at               TEXT NULL
```

### source別ルール

```text
user:
  user_* カラム更新可
  最優先

llm/system/worker:
  user_* カラム更新不可
  base_version競合時はdiscardまたは再計算
```

## 11.3 external_operations

外部副作用を伴う操作。

対象:

- Gmail送信
- Gmailスター付与
- Google Calendar予定作成
- Google Calendar予定変更
- Google Tasksエクスポート

```text
id                          TEXT PRIMARY KEY
operation_type               TEXT NOT NULL
status                       TEXT NOT NULL DEFAULT 'pending'
idempotency_key              TEXT NOT NULL UNIQUE
request_payload_hash          TEXT NOT NULL
request_payload_json          TEXT NOT NULL
external_service              TEXT NOT NULL
external_id                  TEXT NULL
attempt_count                INTEGER NOT NULL DEFAULT 0
last_attempt_at              TEXT NULL
succeeded_at                 TEXT NULL
failed_at                    TEXT NULL
unknown_at                   TEXT NULL
unknown_reason               TEXT NULL
manual_resolution_required    INTEGER NOT NULL DEFAULT 0
created_at                   TEXT NOT NULL
updated_at                   TEXT NOT NULL
```

### idempotency_key

二重実行防止のため必須。

例:

```text
gmail_send:{draft_id}:{draft_version}
gmail_star:{message_id}
gcal_create:{source_message_id}:{candidate_hash}
gtasks_export:{task_id}:{task_version}
```

### unknown状態

通信断等で外部副作用が起きたか不明な場合、`unknown` にする。

`unknown` は自動再実行禁止。  
保守・運用画面または対象画面でユーザー確認を求める。

---

# 12. Rules / Settings系テーブル

## 12.1 app_settings

アプリ全体設定。

```text
id              TEXT PRIMARY KEY
key             TEXT NOT NULL UNIQUE
value_json       TEXT NOT NULL
updated_at      TEXT NOT NULL
```

例:

```text
llm_cost_limit_daily
llm_cost_limit_monthly
default_follow_up_days
worker_min_count
worker_max_count
```

## 12.2 mail_importance_rules

メール重要度フィルタ。

```text
id                          TEXT PRIMARY KEY
name                        TEXT NOT NULL
priority                    INTEGER NOT NULL
condition_json               TEXT NOT NULL
output_importance            TEXT NOT NULL
additional_llm_prompt         TEXT NULL
is_enabled                   INTEGER NOT NULL DEFAULT 1
deleted_at                   TEXT NULL
created_at                   TEXT NOT NULL
updated_at                   TEXT NOT NULL
```

### condition_json例

```json
{
  "all": [
    {"field": "from", "op": "contains", "value": "newsletter@example.com"},
    {"field": "subject", "op": "contains", "value": "newsletter"}
  ]
}
```

### 出力可能値

```text
pinned
high
middle
low
skip
```

メールアドレス単独のSkipは、このルールでも表現しない。Fromだけを理由にSkipしたい場合は、Contactを作成し、Contact自体を `skipped` にする。

## 12.3 case_candidate_rules

Case候補抽出ルール。

```text
id                      TEXT PRIMARY KEY
case_id                 TEXT NOT NULL REFERENCES cases(id)
name                    TEXT NOT NULL
priority                INTEGER NOT NULL
condition_json           TEXT NOT NULL
exclude_condition_json    TEXT NULL
is_enabled              INTEGER NOT NULL DEFAULT 1
deleted_at              TEXT NULL
created_at              TEXT NOT NULL
updated_at              TEXT NOT NULL
```

---

# 13. Auth / Session系テーブル

## 13.1 client_certificates

クライアント証明書管理。

mTLS自体はリバースプロキシで行い、アプリには検証済みfingerprintを渡す想定。

```text
id                          TEXT PRIMARY KEY
device_name                  TEXT NOT NULL
certificate_fingerprint       TEXT NOT NULL UNIQUE
issued_at                    TEXT NOT NULL
expires_at                   TEXT NOT NULL
revoked_at                   TEXT NULL
revoked_reason               TEXT NULL
last_seen_at                 TEXT NULL
created_at                   TEXT NOT NULL
updated_at                   TEXT NOT NULL
```

証明書期限7日前に、`system_maintenance` Case配下へ更新Taskを自動生成する。

## 13.2 sessions

アプリ内パスワード認証後のセッション。

```text
id                          TEXT PRIMARY KEY
client_certificate_id         TEXT NULL REFERENCES client_certificates(id)
session_token_hash            TEXT NOT NULL UNIQUE
user_agent                    TEXT NULL
ip_address                    TEXT NULL
login_at                      TEXT NOT NULL
expires_at                    TEXT NOT NULL
logout_at                     TEXT NULL
locked_reason                 TEXT NULL
created_at                    TEXT NOT NULL
updated_at                    TEXT NOT NULL
```

### セッション仕様

- ログイン後24時間で自動失効。
- 24時間延長はしない。
- 失効後は再ログイン。
- 証明書失効時には関連セッションを無効化する。

## 13.3 auth_login_attempts

ログイン試行履歴。

```text
id                  TEXT PRIMARY KEY
client_fingerprint   TEXT NULL
ip_address           TEXT NULL
user_agent           TEXT NULL
success              INTEGER NOT NULL
failure_reason       TEXT NULL
attempted_at         TEXT NOT NULL
```

### ロック仕様

- 5回連続失敗でログインロック。
- ロック解除はサーバーへの物理アクセスを前提とする。
- DB上は `app_settings` または専用ロックファイルで管理してよい。

---

# 14. Logs / Audit系テーブル

## 14.1 audit_logs

ユーザーがどの情報に接触した可能性があるかを記録する。

```text
id                  TEXT PRIMARY KEY
session_id           TEXT NULL REFERENCES sessions(id)
action_type          TEXT NOT NULL
target_type          TEXT NOT NULL
target_id            TEXT NULL
case_id              TEXT NULL REFERENCES cases(id)
contact_id           TEXT NULL REFERENCES contacts(id)
metadata_json        TEXT NULL
occurred_at          TEXT NOT NULL
created_at           TEXT NOT NULL
```

### action_type例

```text
mail_list_exposed
mail_body_opened
file_card_exposed
file_downloaded
gmail_sent
task_completed
case_link_changed
certificate_revoked
backup_started
backup_restored
```

## 14.2 audit_exposure_batches

メール一覧表示など、大量の対象をまとめて記録するためのbatch。

```text
id                  TEXT PRIMARY KEY
session_id           TEXT NULL REFERENCES sessions(id)
exposure_type        TEXT NOT NULL   -- mail_list/file_list/task_list
screen_name          TEXT NULL
occurred_at          TEXT NOT NULL
metadata_json        TEXT NULL
created_at           TEXT NOT NULL
```

## 14.3 audit_exposure_items

batchに含まれた対象。

```text
id                  TEXT PRIMARY KEY
batch_id             TEXT NOT NULL REFERENCES audit_exposure_batches(id)
target_type          TEXT NOT NULL
target_id            TEXT NOT NULL
created_at           TEXT NOT NULL
```

メール一覧に含まれたメールIDをすべて記録する場合、こちらを使う。

## 14.4 system_logs

システム内部ログ。

```text
id                  TEXT PRIMARY KEY
level               TEXT NOT NULL   -- debug/info/warning/error/critical
component           TEXT NOT NULL
message             TEXT NOT NULL
metadata_json        TEXT NULL
occurred_at          TEXT NOT NULL
created_at           TEXT NOT NULL
```

## 14.5 events

アプリ全体のイベントログ。

`case_events` より広いシステムイベントを扱う。

```text
id                  TEXT PRIMARY KEY
event_type          TEXT NOT NULL
source_type         TEXT NULL
source_id           TEXT NULL
summary             TEXT NULL
metadata_json        TEXT NULL
occurred_at          TEXT NOT NULL
created_at           TEXT NOT NULL
```

---

# 15. Recurring系テーブル

## 15.1 recurring_task_templates

Recurring Caseが持つ定期Taskテンプレート。

```text
id                      TEXT PRIMARY KEY
case_id                 TEXT NOT NULL REFERENCES cases(id)
title_template           TEXT NOT NULL
description_template     TEXT NULL
schedule_rule_json        TEXT NOT NULL
default_due_rule_json     TEXT NULL
is_enabled              INTEGER NOT NULL DEFAULT 1
deleted_at              TEXT NULL
created_at              TEXT NOT NULL
updated_at              TEXT NOT NULL
```

## 15.2 generated_recurring_tasks

重複生成防止。

```text
id                          TEXT PRIMARY KEY
recurring_task_template_id    TEXT NOT NULL REFERENCES recurring_task_templates(id)
generated_for_period          TEXT NOT NULL
task_id                      TEXT NOT NULL REFERENCES tasks(id)
generated_at                 TEXT NOT NULL
```

### 制約

```text
UNIQUE(recurring_task_template_id, generated_for_period)
```

---

# 16. Backup / Restore系テーブル

バックアップ・復旧は実装優先度を下げるが、DB設計上の受け皿は用意する。

## 16.1 backup_runs

バックアップ実行履歴。

```text
id                  TEXT PRIMARY KEY
backup_type          TEXT NOT NULL   -- incremental/full/manual/restore_test
status              TEXT NOT NULL   -- running/succeeded/failed/canceled
started_at           TEXT NOT NULL
finished_at          TEXT NULL
backup_target        TEXT NULL
backup_manifest_json TEXT NULL
error_message        TEXT NULL
created_at           TEXT NOT NULL
```

## 16.2 restore_runs

復元実行履歴。

```text
id                  TEXT PRIMARY KEY
backup_run_id        TEXT NULL REFERENCES backup_runs(id)
status              TEXT NOT NULL
started_at           TEXT NOT NULL
finished_at          TEXT NULL
restore_mode         TEXT NULL
notes                TEXT NULL
error_message        TEXT NULL
created_at           TEXT NOT NULL
```

復元操作は重要操作であり、確認ダイアログ対象とする。

復元後は `external_operations` の自動再実行を停止し、必要に応じて手動確認する。

---

# 17. optimistic_state設計素案

## 17.1 目的

Single DB Writer経由の更新では、ユーザー操作から実DB反映まで短い遅延が発生する。

そのため、軽い操作ではAPIレスポンスに `optimistic_state` を返し、UIを即時更新する。

## 17.2 対象操作

- メール処理済み化
- Task完了
- Taskキャンセル
- Case紐づけ変更
- 重要度変更
- Draft保存

## 17.3 レスポンス例

```json
{
  "write_request_id": "wr_...",
  "optimistic_state": {
    "entity_type": "mail",
    "entity_id": "mail_...",
    "patch": {
      "process_status": "processed",
      "processed_at": "2026-05-22T10:00:00+09:00"
    }
  }
}
```

## 17.4 UI側ルール

- optimistic_state適用中の項目には内部的に `pending_write_request_id` を保持する。
- 実DB反映が成功したらpending表示を解除する。
- 失敗したらUIを再取得し、必要に応じてエラー表示する。
- 複数タブで競合した場合は、DB再取得を優先する。

## 17.5 base_version競合

- ユーザー操作由来で競合した場合、UIに「更新前に別の変更がありました」と表示する。
- LLM/System由来で競合した場合、原則discardまたは再計算Jobへ回す。

---

# 18. 主要index方針

初期実装で必要なindex候補。

## Case / Task

```text
cases(archived_at, closed_at)
cases(system_case_key)
tasks(case_id, status, deleted_at)
tasks(parent_task_id)
tasks(due_at)
```

## Mail

```text
gmail_messages(gmail_message_id)
gmail_messages(thread_id)
gmail_messages(received_at)
gmail_messages(from_address)
mail_user_state(message_id)
mail_user_state(process_status)
mail_auto_state(message_id)
mail_auto_state(llm_importance)
case_mail_links(message_id)
case_mail_links(case_id)
```

## Contact

```text
contact_email_addresses(normalized_email_address)
contact_email_addresses(contact_id)
contact_tags(tag)
```

## Job / Writer

```text
jobs(status, priority, available_at)
write_requests(status, priority, created_at)
external_operations(idempotency_key)
external_operations(status)
```

## Audit

```text
audit_logs(occurred_at)
audit_logs(target_type, target_id)
audit_logs(session_id)
audit_exposure_items(target_type, target_id)
```

---

# 19. 初期データ

初期セットアップ時に以下を作成する。

## 19.1 System Cases

```text
Inbox / なんでも箱
  is_system_case = 1
  system_case_key = inbox

システムメンテナンス
  is_system_case = 1
  system_case_key = system_maintenance
```

## 19.2 app_settings初期値

```text
default_follow_up_days = 7
session_lifetime_hours = 24
login_failure_limit = 5
llm_cost_limit_daily = null
llm_cost_limit_monthly = null
worker_min_count = 1
worker_max_count = 4
```

## 19.3 prompt_versions

実装時に、各LLM機能の初期プロンプトを登録する。

例:

```text
mail_importance_classification
contact_registration_prefill
mail_summary_ja
mail_case_selection
reply_draft_generation
new_mail_draft_generation
mail_task_suggestion
calendar_candidate_extraction
case_context_update
contact_context_update
file_security_meta_classification
handover_log_generation
```

---

# 20. 実装時に特に守るべきDBルール

1. Caseは削除しない。
2. Caseの完了は `closed_at` で表現する。
3. Taskの完了は `completed`、Taskの削除は `deleted_at` で表現する。
4. Taskは物理削除しない。
5. Email Addressに `skipped_address` 状態は作らない。
6. メールアドレス単独Skipという概念は持たない。Fromだけを理由にSkipしたい場合はContactを `skipped` にする。
7. Gmailスターは読み込み時点の `external_importance` として扱う。
8. Gmail側スター解除は再監視しない。
9. ユーザーがHighにした場合、Gmailスター付与の `external_operations` を作る。
10. LLMがHighにした場合も、Gmailスター付与の `external_operations` を作る。
11. Pending判定はFromアドレスのみを対象とする。
12. Pending中は重要度判定・Case判定・自動要約を止める。
13. Lowは自動要約しない。
14. 自動Case判定は1メール1案件。
15. 手動で別Caseへのコピーリンクを許す。
16. `no_case_needed` はCaseリンクなし。
17. `inbox_required` はInboxへ自動紐づけ。
18. `external_operations.unknown` は自動再実行しない。
19. LLM入力全文は `llm_runs` に保存しない。
20. LLM追加指示は `llm_instruction_rules` として版・優先順位つきで管理する。
21. LLM出力schemaは `prompt_versions.output_schema_json` で管理し、schema変更時はversionを上げる。
20. Cost Limit超過時は `system_maintenance` Case配下にTaskを作る。

---

# 21. 後続検討事項

以下は本DB設計v0.1では確定しない。

- 各テーブルの完全DDL
- ORM上の正確な型定義
- full-text search導入有無
- メール本文の圧縮保存
- 古い監査ログのアーカイブテーブル分離
- Google Tasksエクスポート詳細
- ポモドーロタイマー専用作業セッションテーブル
- 複数ユーザー対応
- Redis/RQ/Celery移行時のQueueテーブル縮退
- RAG用embeddingテーブル
- ファイル全文抽出結果テーブル

---

# 22. 次に作るべき文書

本書の次は、以下の順で設計を切る。

1. API詳細設計書
2. 画面別操作仕様書
3. 状態遷移詳細設計書
4. Worker / Job詳細設計書
5. 認証・運用詳細設計書

ただし、状態遷移のうちDB制約に関わる部分は本書に取り込んでいる。

