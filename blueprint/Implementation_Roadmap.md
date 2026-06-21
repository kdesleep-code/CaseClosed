# CaseClosed 実装ロードマップ

Version: 0.1  
作成日: 2026-05-22  
対象: 個人用案件管理Webアプリ CaseClosed  
想定実装支援: Codex / LLM coding agent

---

## 0. 本書の位置づけ

本書は、CaseClosedを段階的に実装するためのロードマップである。

既存設計書:

- CaseClosed 概要設計書
- CaseClosed 詳細設計書
- CaseClosed DB設計書
- CaseClosed API設計書
- CaseClosed Worker / Job / External Operation設計書
- CaseClosed 画面仕様書
- CaseClosed 状態遷移設計書
- CaseClosed LLM / Prompt設計書
- CaseClosed セキュリティ / 認証 / 運用保守設計書

本書では、各Phaseで作る対象、完了条件、レビュー観点、Codexへの依頼単位を定義する。

---

# 1. 実装方針

## 1.1 基本方針

CaseClosedは、自分用の業務支援Webアプリである。  
そのため、一般公開サービスのような「MVPリリース」は想定しない。

ただし、実装順序上は、壊れにくい土台から順に積み上げる。

優先する価値:

```text
1. 安全にログインできる
2. DBとmigrationが壊れない
3. Gmailを読み込める
4. Pending Contactを解消できる
5. メール一覧を見て処理できる
6. LLMで重要度・要約・返信生成を支援できる
7. File / Storage基盤でメール添付と生成物を保存できる
8. Caseにメール・File・Task・予定・Contactを集約できる
9. Worker / Job / External Operationが安全に動く
10. 運用保守できる
```

## 1.2 Codexへの依頼単位

Codexには、巨大な一括実装を投げない。  
1回の依頼は、以下の単位にする。

```text
1. 1〜3テーブル + migration + unit test
2. 1画面 + 対応API + 最小テスト
3. 1Worker + job定義 + mock test
4. 1つのLLM機能 + schema validation + mock test
5. 1つの外部副作用 + external_operations + idempotency test
```

## 1.3 レビュー方針

ユーザーは、最初から詳細に実装指示を出しすぎるより、まず動くものを作らせてから、

```text
これは気に入らない
この操作が遠い
このボタンが足りない
この表示順が違う
この概念の扱いが違う
```

という形でレビューする方が向いている。

ただし、以下は最初から厳密にレビューする。

- ユーザー確定値をLLM/Systemが上書きしていないか
- Gmail送信やCalendar作成が二重実行されないか
- Pending Contactの扱いが仕様通りか
- Task削除が論理削除になっているか
- Case削除が通常導線に露出していないか、誤作成向けの例外操作に限定されているか
- Email Address単独Skipが作られていないか
- External Operation unknownが自動再実行されないか
- LLM入力全文がllm_runsに保存されていないか

画面レイアウトは後から変えてよい。  
データモデル・副作用・状態遷移の破綻は後から直しにくいので、早めに確認する。

---

## 1.4 Test-first開発方針

CaseClosedでは、各Phase・各機能の実装前に、設計書を読んでテストを作成する。

基本順序:

```text
設計書確認
-> テスト作成
-> 実装
-> テスト通過
-> ユーザーレビュー
-> UI/操作感の調整
```

一度作成したテストは原則として削除・弱体化しない。  
環境変化や設計変更によりテスト修正が必要な場合は、Codexが勝手に変更せず、ユーザーに理由を提示して確認を取る。

詳細は `CaseClosed_Test_Strategy_v0.1.md` に従う。


# 2. Phase構成

## Phase 0: 技術スタック確定・リポジトリ準備

### 目的

プロジェクトの土台を作る。

### 実装対象

- リポジトリ初期化
- ディレクトリ構成
- Python環境
- Web framework
- DB migration tool
- test framework
- lint / format
- `.env` 分離
- development / staging / production 設定分離
- systemd想定の起動方式メモ

### 推奨スタック案

候補:

```text
Backend:
  Python + FastAPI

DB:
  SQLite

ORM:
  SQLAlchemy 2.x

Migration:
  Alembic

Template/UI:
  Jinja2 + HTMX
  または FastAPI + React
```

初期実装では、画面変更が多いことを考えると、Jinja2 + HTMX の方が軽い可能性がある。  
ただし、将来的に複雑なUIを作るならReactでもよい。

### 完了条件

- 開発サーバーが起動する
- `/health` が応答する
- SQLiteへ接続できる
- migrationを実行できる
- pytestが動く

### レビュー観点

- ディレクトリ構成が見通しやすいか
- 設定ファイルに本番secretが混ざらないか
- テストがすぐ実行できるか

---

## Phase 1: 認証・セッション・保守Caseの最小実装

### 目的

安全にアプリへ入れる土台を作る。

### 実装対象

DB:

- app_settings
- client_certificates
- sessions
- audit_logs
- system_logs
- cases
- case_events

初期データ:

- Inbox Case
- システムメンテナンス Case

API:

- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/session`
- `GET /maintenance/status`

画面:

- Login
- Top最小版
- Maintenance最小版

機能:

- アプリ内パスワード
- 5回失敗ロック
- 24時間セッション
- session cookie
- certificate fingerprint受け取りの仮実装
- System Maintenance Case作成

### 完了条件

- ログインできる
- 24時間セッションが作られる
- 5回失敗でロックされる
- Inbox / システムメンテナンス Caseが存在する
- System Caseを削除できない
- Case削除が通常導線ではなく、誤作成向けの例外操作として扱われる

### レビュー観点

- ログインの面倒さが許容範囲か
- ロック解除手順が分かるか
- Maintenance画面に最低限の情報が出るか
- System Caseが通常Caseと混ざりすぎていないか

---

## Phase 2: DB Core / Write Request / Job基盤

### 目的

以後の実装が壊れないよう、DB更新と非同期処理の土台を作る。

### 実装対象

DB:

- jobs
- write_requests
- external_operations
- prompt_versions
- llm_runs
- llm_instruction_rules
- schema_versions

サービス:

- QueueInterface
- SQLiteQueue
- Single DB Writer
- Audit Log Writer
- Orchestrator最小
- Worker heartbeat
- stale job検出

API:

- `GET /jobs`
- `POST /jobs/{id}/retry`
- `GET /external-operations`
- `POST /external-operations/{id}/resolve`

画面:

- Maintenance Job一覧
- External Operation一覧

### 完了条件

- write_requestがSingle DB Writer経由で反映される
- Jobがpending -> running -> succeeded/failedへ遷移する
- stale jobを検出できる
- external_operationのunknownを手動解決できる
- audit logが業務DB writeを詰まらせない

### レビュー観点

- 状態遷移が設計通りか
- unknown external operationが自動再実行されないか
- write_request失敗が見えるか
- UIが「何が詰まっているか」を把握できるか

---

## Phase 3: Contact / Pending Contact基盤

### 目的

Contact未登録FromをPendingにし、初期運用の負荷を下げる。

### 実装対象

DB:

- contacts
- contact_email_addresses
- contact_tags
- contact_context_versions
- contact_registration_suggestions
- contact_merge_history

API:

- `GET /contacts`
- `POST /contacts`
- `PATCH /contacts/{id}`
- `POST /contacts/{id}/skip`
- `POST /contacts/{id}/activate`
- `POST /contacts/{id}/email-addresses`
- `GET /contacts/unresolved-from-addresses`
- `POST /contacts/unresolved-from-addresses/{email}/generate-prefill`

画面:

- Contact一覧
- Contact詳細
- Pending Contact処理画面

LLM:

- contact_registration_prefill

### 完了条件

- 未登録FromがPendingとして表示される
- LLM自動Fill候補が出る
- 新規Contact作成できる
- 既存Contactにメールアドレス追加できる
- Contact skippedにできる
- Email Address単独Skipが存在しない

### レビュー観点

- Pending処理画面が使いやすいか
- Contact登録が少ない手数でできるか
- no-replyやMLをskipped化しやすいか
- LLM自動Fillが邪魔ではないか
- 「Address Skip」が混入していないか
- メールアドレス解除後、既存メールが古いContactに残って見えないか
- skipped Contact解決時に重要度判定へ進まずSkip扱いになるか

### Phase 4開始前の持ち越しメモ

- `source_suggestion_id` が指定されたContact作成では、採用元候補のstatusを更新する。
- Contactからメールアドレスを外す処理は、`has_inbound_message_history = 0` なら物理削除、`1` なら `inactive` 化する。削除時にメールテーブルを全走査しない。
- `inactive` は受信時のContact解決には使い、送信先・Primary候補には使わない。
- Phase 4のGmail Syncでは、Fromとして観測したアドレスの `has_inbound_message_history` を必ず `1` にする。
- From履歴があるメールアドレスのUI操作は `Remove` ではなく `Deactivate` 等、履歴を残す操作だと分かる表現にする。
- `inactive` メールアドレスは `Activate` 操作で再有効化できる。
- Contact間でメールアドレスを明示的に移動できるAPI/UIを持つ。Moveは所属Contactの変更であり、`active` / `inactive` 状態は維持する。
- 押せないボタンは待機カーソルではなく、hover時に押せない理由を説明する。
- フロントエンドの表示文言は文言キー経由にし、`window.CASECLOSED_LANGUAGE_PATCH` / HTML内JSON / localStorageで言語パッチを当てられるようにする。既存画面は主要文言から順次移行する。
- フロントエンドの見た目はDesign Set / Theme Presetとして切替可能にする。Settings UIは後続でよいが、`window.CASECLOSED_THEME` / localStorage / `data-theme` / CSS custom propertiesで切替可能な土台を維持する。
- Gmail messageの識別は、アプリ内主キー `gmail_messages.id`、Gmail API由来の一意キー `gmail_message_id`、RFC 5322の `Message-ID` ヘッダを区別する。
- Phase 4では `From` だけで送信者を確定したことにしない。`Sender` / `Reply-To` / `List-Id` / `To` / `Cc` / `Bcc` / `In-Reply-To` / `References` など、後で送信者推定・Reply All候補抽出に使うヘッダを保存する。
- Pending判定は当面 `from_address` ベースでよい。ただし、メーリングリストや代理送信の可能性をUI/API上で説明できるよう、保存ヘッダから「推定根拠」を出せる余地を残す。
- Contactには `kind = person / mailing_list` と `sender_resolution_mode = self / reply_to` を持たせる。Fromが `mailing_list` Contactで `reply_to` 指定の場合、Phase 4では `Reply-To` を実送信者候補として扱い、既知/未知判定へ戻す。
- `sender_resolution_mode = self` のMLは、Neuromail等「誰が内部送信者かは追わず、この発信元から来たことが分かればよい」ケースに使う。
- `mailing_list` は通常Contact一覧・通常Contact用カスタムタブ・通常Contact向け詳細/LLMメモ更新とは混ぜず、Mailing List専用タブと専用詳細で扱う。
- Mailing Listは1 Contact = 1メールアドレスとし、Contact tagsを持たない。`mailing-list` は予約タグとして使用不可。
- Mailing Listのメールアドレスは常にActive/Primaryとし、Remove/Deactivate/Set Primary操作を持たない。
- Contact本体削除は、紐づく全メールアドレスが物理削除可能な場合のみ許可する。
- New Contact導線は常に通常Contactを作成する。作成フォームではmemoを入力させず、作成後に `All` タブへ移動して対象ContactのDetail Editを開く。Mailing List登録はメール画面/Pending Contact解決からのみ行う。
- 既存Contactの `kind` は変更不可とする。PersonからMailing Listへの移行、Mailing ListからPersonへの戻しは通常編集では行わない。
- Mailing Listには `mailing_list_recipient_expression` を持たせ、将来メール宛先設定時にタグ式から宛先展開できる土台を用意する。
- Mailing Listはmemoと関連Caseを持てる。ただしLLMによるmemo/Context自動更新対象にはしない。
- LLM呼び出しはOpenAI API直結にせず、`LLMProvider` 相当の差し替え境界を用意する。Phase 4/5初期は `mock` / deterministic providerでテストし、その後OpenAI providerを追加する。

---

## Phase 4: Gmail同期・メール保存・まとめーる風メール一覧

### 目的

メール入口を作る。  
初期UIはまとめーるに寄せる。

### 実装対象

DB:

- gmail_threads
- gmail_messages
- gmail_attachments_meta
- mail_user_state
- mail_auto_state
- mail_summaries
- case_mail_links

API:

- `POST /gmail/sync`
- `GET /mails`
- `GET /mails/by-loaded-date`
- `GET /mails/search`
- `GET /mails/{id}`
- `GET /mails/{id}/thread`
- `POST /mails/{id}/process`
- `POST /mails/{id}/importance`
- `POST /mails/{id}/pin`

画面:

- Mail一覧
- Mail詳細
- 日別メール一覧
- 未処理メール一覧
- 検索結果一覧
- 受け取ったメール / 対応済み / Skipタブ

機能:

- Gmail初回7日取得
- 差分取得
- 本文DB保存
- 読み込み日別表示
- 全メール検索
- Gmailリンク
- 添付メタ表示
- Pending判定
- Gmailスター読み込み時点のexternal_importance
- Gmail message ID / RFC Message-ID / thread IDを区別して保存
- From / Sender / Reply-To / List-Id等の住所系ヘッダ保存
- 初期固定では外部Gmail APIへ接続せず、`POST /api/v1/mails/mock-ingest` で疑似メールを投入してDB保存・Pending判定・後続Job作成を検証する。
- Fromが `mailing_list` かつ `sender_resolution_mode = reply_to` の場合は、疑似メールでも `Reply-To` を実送信者候補として再解決する。
- Pending Contactが解決されたら `contact_resolution_followup` Jobで該当メールの `pending_reason` / `pending_from_address_id` を解除し、通常の重要度判定Jobへ戻す。
- `mail_importance_classification` は初期段階では外部LLMへ接続せず、deterministic mock providerで `high` / `middle` / `low` を返してDB更新の流れを固定する。
- LLM処理は `LlmProvider` 相当の境界を通し、mock providerでも `llm_runs` に provider/model/output と最小の input source を保存する。メール本文全文は `llm_runs.input_source_json` に保存しない。
- `contact_registration_prefill` も同じprovider境界を通し、mock providerで候補を作成しつつ `contact_registration_suggestions.llm_run_id` と `llm_runs` を残す。
- `GET /api/v1/mails` は初期段階から `tab` / `processed` / `importance` / `contact_status` / `read` / `date_from` / `date_to` / `q` / `limit` / `cursor` の一覧フィルタを持つ。`q` は空白区切りAND検索とする。
- Mail UIは受信日ごとの日別表示、`pending` / `unprocessed` / `processed` / `skip` タブ、アプリ内 `read_status`、検索時のフラット一覧を前提にする。検索結果の優先度順並べ替えは、APIが返す `importance_rank` を使って表示中N件の範囲で行う。
- `GET /api/v1/mails/{message_id}` は、本文、主要ヘッダ、thread messages、user/auto state、available actionsを返す。
- `POST /api/v1/mails/{message_id}/importance` / `process` / `unprocess` は、外部副作用なしでDB状態更新のみを先に固定する。

### 完了条件

- 外部サービスなしの疑似メール投入で、メール一次情報と `mail_user_state` / `mail_auto_state` を保存できる
- Contact未登録FromまたはML Reply-ToはPendingになり、既知Contactは重要度判定Jobに進む
- Pending Contact解決後、止まっていたメールが重要度判定Jobへ進む
- mock重要度判定Jobが `mail_auto_state.suggested_importance` / `effective_importance` を更新できる
- mock重要度判定Jobが `llm_runs` を作成し、`mail_auto_state.llm_run_id` から追跡できる
- Contact Prefill Jobが `llm_runs` を作成し、suggestionから追跡できる
- Pending ContactをPrefill候補から作成する場合、`source_suggestion_id` を渡して候補を `adopted` / `edited_and_adopted` に更新し、`contact_resolution_followup` から `mail_importance_classification` まで詰まらず進む
- メール詳細APIで本文・ヘッダ・状態・利用可能操作を取得できる
- メール一覧APIで重要度、処理状態、検索語による基本フィルタが動く
- メール重要度変更、処理済み化、未処理戻しがDB上で動く
- Gmailからメールを取得できる
- 本文をDBに保存できる
- Contact未登録FromはPendingになる
- 送信者推定に必要な主要ヘッダをDBに保存できる
- 読み込み日別に表示できる
- 未処理メール一覧がある
- 3タブ表示がある
- 検索が全メール対象で動く
- Gmailスター初期状態がHigh相当になる
- Gmail側のスター解除を再監視しない

### レビュー観点

- まとめーるに近い操作感になっているか
- 日別表示が気持ちよいか
- 未処理一覧が見やすいか
- タブの意味が自然か
- 検索が「絞り込み」ではなく「全メール検索」になっているか
- メールカードの情報量が多すぎ/少なすぎないか

---

## Phase 5: Mail Intelligence安定化

### 目的

実メール運用に必要なメールAI処理を安定させる。

このPhaseでは、Case自動判定は扱わない。Case連携はStorage基盤を作った後に実装する。

### 実装対象

LLM:

- mail_importance_classification
- mail_summary
- mail_thread_summary
- reply_draft_generation
- new_mail_draft_generation
- contact_registration_prefill
- contact_ai_memo_update

DB:

- mail_summaries
- prompt_versions
- llm_runs
- llm_instruction_rules
- mail_drafts
- app_settings

API:

- `GET /llm-runs`
- `GET /llm-runs/{id}`
- `GET /mail-importance-rules`
- `POST /mail-importance-rules`
- `POST /mails/{id}/run-importance`
- `POST /mails/{id}/summarize`
- `POST /mails/{id}/summarize-thread`
- `POST /mails/generate-draft`
- `GET /mail-drafts`
- `POST /mail-drafts`

画面:

- Mail一覧で要約表示
- Mail詳細でLLM結果表示
- LLM実行履歴
- LLM追加指示設定
- 重要度ルール設定
- メール作成画面の署名・Draft・LLM Generationガジェット

機能:

- High / Middle / Low判定
- High / Middleのみ自動要約
- Lowは自動要約なし
- Pinnedは自動要約なし
- LLMはPinned/Skip/Pendingを出力不可
- JSON schema validation
- JSON不正リトライ
- スレッド要約
- 返信引用部分の折りたたみ
- HTMLメール表示
- 返信生成時の言語制御
- 送信先Contacts情報を使った本文生成

### 完了条件

- Pending中はLLM重要度判定されない
- Contact解決後に重要度判定が走る
- Lowは要約されない
- Pinnedは要約されない
- High / Middleのメール・スレッド要約が作られる
- 要約失敗・LLM失敗がMaintenanceで見える
- メール生成でInstruction / Standard Prompt / Contact memo / 返信元本文を参照できる
- 英語メールへの返信は英語、日本語メールへの返信は日本語になるよう簡易チェックされる
- HTMLメール本文が実用上読める
- 返信引用部分を折りたためる

### レビュー観点

- 重要度判定が実用上大きくズレないか
- 要約が一覧で役に立つか
- LLM失敗時の表示が分かりやすいか
- 追加指示を変えたくなる場所が見えているか
- メール作成支援がユーザーの邪魔をしていないか
- 実メールのHTML/引用/長文が破綻しないか

---

## Phase 6: File / Storage基盤

### 目的

メール添付・手元ファイル・生成物を安全に保存し、後続のCase連携で使えるようにする。

### 実装対象

DB:

- storage_objects
- storage_locations
- storage_directories
- gmail_message_attachments
- storage_operation_history
- storage_object_versions
- file_version_diffs
- file_links（Phase 7でCase-Fileの明示的な多対多参照として実装）
- file_security_rules（LLM Policy本格化時に拡張）
- file_summaries
- attachment_fetch_jobs（専用テーブルは未採用。現状は `jobs.job_type = mail_attachment_fetch` で実装）

API:

- `GET /files`（フロントルート。APIは `/api/v1/storage/objects`）
- `GET /files/{id}`（フロントルート。APIは `/api/v1/storage/objects/{id}`）
- `POST /api/v1/storage/objects/upload`
- `POST /api/v1/storage/objects`
- `GET /api/v1/storage/objects/{id}/content`
- `GET /api/v1/storage/objects/{id}/versions`
- `POST /api/v1/storage/objects/{id}/versions/upload`
- `PATCH /api/v1/storage/objects/{id}/llm-input`
- `PATCH /api/v1/storage/objects/{id}/directory`
- `DELETE /api/v1/storage/objects/{id}`
- `GET /api/v1/storage/directories`
- `POST /api/v1/storage/directories`
- `DELETE /api/v1/storage/directories/{id}`
- `GET /api/v1/storage/search/objects`
- `GET /api/v1/mails/attachments/{id}/download`
- `POST /api/v1/mails/attachments/{id}/move-to-storage`
- `POST /api/v1/mails/attachments/{id}/fetch-job`
- `GET /api/v1/maintenance/storage-operation-history`
- `GET /api/v1/storage/objects/{id}/llm-digest`
- `POST /api/v1/storage/objects/{id}/llm-digest`

画面:

- Storage一覧
- Storage詳細
- Storage検索・拡張子フィルタ・ディレクトリ操作
- Mail添付カード
- Mail添付のバックグラウンド取得メニュー
- 添付元メールカード
- Maintenance / Debug のStorage操作履歴
- Storage設定（Maintenance上の表示のみ。本格UIはPhase 9で対応）
- LLM input許可/ブロック切替
- Storage詳細でのドラッグ&ドロップ更新、バージョン選択表示、選択バージョンのダウンロード
- Storage詳細でのLLM Digest生成・表示
- Storage詳細でのVersion Difference折りたたみ表示

LLM:

- file_security_meta_classification（保留）
- file_summary（Storage詳細の Prepare LLM Digest として実装）

### 現在仕様

- ファイル削除は、現時点では物理ファイル削除を正とする。
- 削除後も `storage_objects` のDBメタ情報は `status = deleted` として残す。
- `trash / restore / purge` の3段階モデルは採用しない。必要になった時点で再検討する。
- 物理削除・アップロード・移動・ダウンロード・LLM input設定変更などの操作履歴を `storage_operation_history` に保存する。
- 操作履歴は当面 Maintenance / Debug に直近履歴として表示する。
- Storage詳細画面へファイルをドロップすると、同じ `storage_objects.id` のまま現在ファイルを更新する。
- 更新前の物理ファイルとメタ情報は `storage_object_versions` に保存する。
- ドロップ更新時に拡張子が異なる場合は、フロント側で確認を挟む。
- ドロップ更新時に内容hashが同一の場合は更新をスキップし、履歴に `update_skipped` を残す。
- Storage詳細ではプルダウンで現在版/旧版を切り替え、選択したバージョンをプレビュー・ダウンロードする。
- Storage一覧からのダウンロードは常に最新版を対象とする。
- ファイル本文の保存時刻は `storage_objects.file_updated_at` で管理し、LLM input設定変更などのメタ情報更新時刻とは分離する。
- 旧版を選択中は、選択版を含めてそれ以前のバージョンを削除でき、削除後は最新版表示へ戻る。
- Prepare LLM Digestは、ファイル本文を後続LLMへ再投入するための圧縮済み中間表現を作る機能として扱う。
- LLM Digestは、人間向けの1行説明・最大5項目の要約・後続LLM用の `llm_digest` / `structured_digest_json` / `coverage_json` を保存する。
- LLM Digestの本文抽出は拡張子/形式ごとの抽出ブロックを通す。現状はテキスト、ZIP構造、PDF本文、DOCX本文（依存ライブラリ利用時）を扱い、未対応形式は `coverage_json` に制約を残す。
- ファイル更新後、対象版のDigestが未生成で過去版のDigestが存在する場合は、最新の過去Digestとそこから対象版までの差分チェーンをLLM入力にして増分Digestを生成する。
- 対象版に既にDigestがある状態でユーザーが明示的に再生成する場合は、対象版の本文抽出結果から全文ベースで再生成する。
- ファイル更新時はLLMを使わずに前後の抽出テキスト差分を `file_version_diffs` に保存する。
- Storage詳細のVersion Differenceは、表示中バージョンに至る差分をデフォルト折りたたみで表示し、展開時は変更行の前後だけを残して長い無変更部分を省略する。

### 完了条件

- ファイルをローカル保存できる
- 物理保存はIDベースで、元ファイル名とは分離される
- メール添付を必要時に取得・保存できる
- メール添付取得をJob化でき、失敗時はMaintenanceのJob一覧で確認できる
- 添付元メールを辿れる
- LLM input可否を設定できる
- `llm_input_allowed = false` のファイルは、後続のFile LLM入力対象から除外する
- 削除時に物理ファイルは削除される
- 削除後もDBメタ情報と操作履歴は残る
- Storage操作履歴がMaintenance / Debugで確認できる
- Storage詳細からファイルを更新でき、旧版を選択して表示・ダウンロードできる
- Storage詳細からLLM Digestを生成し、ファイル説明と短い要約を確認できる
- Storage詳細で更新差分を確認でき、長いファイルでも差分周辺だけを確認できる
- 保存失敗・取得失敗がMaintenanceで見える（未実装。attachment_fetch_jobs導入時に強化）

### レビュー観点

- ファイルがどこに保存されたか理解できるか
- メール添付の保存操作が自然か
- LLM input許可/ブロックの扱いが怖くないか
- 物理削除前の確認が十分か
- ファイル更新時に別ファイルを誤って差し替えるリスクが十分に抑えられているか
- 削除・移動・取得などの操作履歴が追跡できるか
- 後続のCase連携に必要なメタ情報が足りているか

---

## Phase 7: Case連携

Status: Fixed（2026-06-07時点）

### 目的

Mail / Contact / FileをCaseへ手動で流し込み、Case詳細を「案件の基地」として使えるようにする。

初期運用ではLLMによる自動Case判定を行わない。まず手動Assignで運用し、手間が大きくなった段階で候補提示またはLLM自動判定を追加する。

ただし、ユーザーが明示した「この送信者からのメールはこのCaseへ入れる」という単純ルールはPhase 7に含める。これはLLM判定ではなく、手動Assignを補助する明示ルールとして扱う。

### 実装対象

DB:

- case_mail_links（Thread単位の手動Assign）
- case_auto_assign_rules（送信者メールアドレスに基づく明示ルールAssign）
- case_tool_links（Case右ガジェットの外部ツールリンク）
- case_stakeholders（ContactとCaseの関係。contact_case_links相当）
- case_context_versions（Current Situation生成結果）
- Case専用Storage Directory（File連携の初期実装）
- file_links（同一Storage objectを複数Case/通常Storageから参照するための明示リンク）

後続扱い:

- case_candidate_rules（自動Case判定を再開する場合）

API:

- `GET /cases/{id}/mail-links`
- `GET /cases/{id}/auto-assign-rules`
- `POST /cases/{id}/auto-assign-rules`
- `DELETE /cases/{id}/auto-assign-rules/{rule_id}`
- `POST /mails/{id}/cases`
- `DELETE /mails/{id}/cases/{case_id}`
- `POST /cases/{id}/current-situation`
- `GET /cases/{id}/tools`
- `POST /cases/{id}/tools`
- `PATCH /cases/{id}/tools/{tool_id}`
- `DELETE /cases/{id}/tools/{tool_id}`
- `GET /cases/{id}/files`
- `POST /cases/{id}/files/{storage_object_id}/link`
- `DELETE /cases/{id}/files/{storage_object_id}/link`

保留:

- `GET /case-candidate-rules`
- `POST /case-candidate-rules`
- `POST /mails/{id}/run-case-selection`

画面:

- Mail詳細のCaseバッジ表示・手動Assign
- Case詳細内Mail一覧
- Case詳細内Assigned Mail検索・一括Assign・Remove
- Case詳細Assigned Mail画面からのAuto Assign Rule追加・削除
- Case詳細内Stored Files Window（Case専用Storage Directory配下を表示）
- Case詳細Overview / Current Situation / Case Tools / Calendarガジェット
- Case詳細Stakeholders
- Bucket Case表示

LLM:

- case_current_situation_summary

保留:

- mail_case_selection

### 完了条件

- Caseが関連メールThread集合を持つ形で表示される
- ユーザーが手動でCaseリンクを修正できる
- LLM自動Case判定を行わないため、ユーザー確定値が勝手に上書きされない
- 明示Auto Assign Ruleは、受信時にSPAM判定されていない全メールへ適用される。Skip扱いの送信者も対象に含む
- 明示Auto Assign Ruleは、ArchivedでないCaseを対象に適用される。Completed Caseは対象に含む
- 関連ファイルはCase専用Storage Directoryへ保存・表示できる
- 既存Storage objectをCaseへ明示リンクでき、同一ファイルを通常Storageや別Caseからも参照できる
- Case詳細のStored Files Windowで削除操作する際は、「このCaseから除外」と「ファイル本体を削除」を区別する
- 各Caseが専用Storage Directoryを持ち、Caseが存在する限り削除できない
- Case詳細が「案件の基地」として機能し、Overview / 状況説明 / Mail入口 / Task入口 / Files / Calendar / Toolsが見える
- Case Toolsは「アイコン + URL」の単純な外部リンクとして扱い、Caseごとに並べ替え・追加・削除できる
- Current Situationは、ユーザーがRefreshした時だけ、Overview / 関連メールThread要約 / Task情報 / Calendar接続点 / File Digestから生成される

### レビュー観点

- 手動Assignの手間が許容範囲か
- Case詳細が案件の基地として機能しているか
- メールとファイルを辿りやすいか
- Overviewが「このCaseの意図・完了条件」を思い出す場所として機能しているか
- Current Situationが、久しぶりに開いたCaseの状況把握に役立つか
- Toolsガジェットが邪魔にならず、外部ツールへ素早く飛べるか

### Phase 7で明示的に保留するもの

- 自動Case判定 / 候補提示
- case_candidate_rules
- Calendar実データ接続

---

## Phase 8: Case / Task中核

Status: Fix

### 目的

Taskを実データとして扱い、Case詳細を実際の作業管理に接続する。

Phase 7でCaseの基地UIとMail/File連携は概ね固まったため、Phase 8ではTaskを最優先で実装した。TaskはCase / Mail / Storageと接続され、日常運用上の作業単位として扱える状態まで到達した。

Case Series / Create next Caseは、初期運用では独立機能として急がず、Recurring Taskや手動Case作成で代替する。祝日・例外日・作業ブロックなどCalendar依存の高度なTask調整はPhase 9以降で扱う。

### 実装対象

DB:

- tasks
- task_links
- task_suggestions
- task_work_blocks（Calendar作業ブロック接続時に拡張）
- task_progress_entries
- Task Storage Directory

API:

- `GET /tasks`
- `POST /tasks`
- `PATCH /tasks/{id}`
- `POST /tasks/{id}/complete`
- `POST /tasks/{id}/cancel`
- `DELETE /tasks/{id}`
- `POST /tasks/{id}/progress-entries`
- `PATCH /tasks/{id}/progress-entries/{entry_id}`
- `DELETE /tasks/{id}/progress-entries/{entry_id}`
- `POST /mails/{id}/create-task`
- `POST /mails/{id}/suggest-tasks`

画面:

- Task一覧
- Task詳細
- Task新規作成
- メール詳細からTask作成パネル
- Case詳細へのNext Task / New Task導線
- Task Files表示

LLM:

- mail_task_suggestion
- task_prefill_generation
- subtask_suggestionは保留

初期実装順:

1. Taskテーブル / API / 画面
2. Case詳細へのTask一覧・次Task・完了状況接続
3. Case Closed時の未完了Task制約
4. メールからTask作成
5. mail_task_suggestion
6. Progress Memo時系列
7. Recurring Task
8. Task Files

### 完了条件

- Task作成・完了・キャンセル・論理削除できる
- Task削除はdeleted_at
- Task一覧でInbox / Done / Not Started / Archivedを切り替えられる
- Start Date到達でIn Progressへ移る
- Doneから2週間経過したTaskはArchived相当として扱える
- Case詳細にNext TaskとNew Task導線が表示される
- Task作成時にCaseをSuggest入力できる
- メールからLLMでTaskを作成できる
- メールからTask化する時、割り当てCaseがBucket以外なら元メールThreadをCaseに紐づける
- Task詳細にSummary / Done When / Progress Memo / Source Mail / Case / Calendar接続点 / Task Filesが表示される
- Progress Memoは日付ごとの時系列メモとして保存・編集・削除できる
- Completed TaskのFilesは、そのCaseのCompleted Tasksディレクトリへ移動する
- Recurring Taskは毎週 / 2週に1度 / 毎月 / 毎年に対応する
- 毎月はN日、月末、月末前日、第N曜日、最終曜日を指定できる
- Repeat設定がありStart / Due Dateが空の場合、Repeat設定から初回Start / Due Dateを自動補完する

### レビュー観点

- Case一覧で「今止まっているもの」が分かるか
- Task化の手数が少ないか
- Task削除が実削除になっていないか
- ClosedとArchiveの違いがUIで分かるか
- Recurring Taskの自動生成が意図通りか
- Task FilesがCase Storageと整合しているか

### Phase 8で明示的に保留するもの

- Calendar実データ連携
- Task work blockとGoogle Calendarの接続
- 祝日 / 例外日を考慮したRecurring Task調整
- Subtaskの再導入
- Case Series / Create next Case
- 特定メール到着によるTask自動作成ルール

---

## Phase 9: Calendar連携

Status: In progress / core implemented

### 目的

メールから予定化し、Case/TaskとGoogle Calendarをつなぐ。

Phase 8でTask基盤を作った後、早めにCalendar連携へ進む。Case Current SituationにはCalendar接続点を先に用意済みのため、Calendar実データが入った時点でCase状況説明にも反映できる。

### 実装対象

DB:

- calendar_events
- calendar_event_links
- calendar_sync_states / calendar source selection
- calendar_event_candidates（必要に応じて後続）

API:

- `GET /api/v1/calendar/events`
- `GET /api/v1/calendar/events/{id}`
- `POST /api/v1/calendar/sync`
- `POST /api/v1/google/calendar/events`
- `PATCH /api/v1/calendar/events/{id}`
- `POST /api/v1/calendar/events/{id}/move`
- `POST /api/v1/calendar/events/{id}/links`
- `DELETE /api/v1/calendar/events/{id}/links/{link_id}`
- `POST /api/v1/mails/{id}/calendar-prefill`
- `POST /api/v1/tasks/{id}/work-blocks`（Task作業ブロック接続時に拡張）

画面:

- Calendar週表示画面
- Calendar右ガジェット（月ミニカレンダー / Upcoming / Calendar Source）
- Calendar新規Event手入力画面
- Calendar Event詳細 / 編集 / Mail添付画面
- Mail詳細からLLMで予定作成する画面
- Case詳細Calendarガジェット
- Task作業ブロック作成UI（後続）

LLM:

- calendar_candidate_extraction / calendar event prefill
- preparation_task_suggestion
- handover_task_generation

外部副作用:

- Google Calendar create/update
- Google Calendar同期ロード
- ローカルDBを表示キャッシュとして持ち、Google Calendarを正本とする

### 完了条件

- Calendar週表示で、複数Calendar Sourceの予定を同時表示できる
- Google Calendarから未来中心の予定をDBへ同期できる
- DB上のCalendar Eventを高速に表示できる
- メールから予定候補を抽出できる
- ユーザー確認後にGoogle Calendarへ登録できる
- 手入力で予定を登録できる
- 予定作成時にCase / Task / Mailをリンクできる
- 既存予定の詳細確認・編集・日時変更・リンク編集ができる
- Calendar上でイベントカードをドラッグ&ドロップして日時変更できる
- Case詳細に関連予定とNext Eventが表示される
- Case詳細Calendarガジェットで、関連イベントのある日を確認できる
- Calendar作成unknownは自動再実行しない

### レビュー観点

- 予定候補の日付・時刻抽出が信頼できるか
- 登録前編集がしやすいか
- Calendar説明欄に必要情報が入るか
- Google Calendarで開く導線があるか
- Google Calendarのみの予定とDB拡張情報つき予定の扱いが混乱しないか
- 複数Calendar Source表示時の色・重なり・Upcoming表示が見やすいか
- DnD日時変更が直感的か

---

## Phase 10: Gmail送信 / Follow-up仕上げ

### 目的

送信・送信後確認・フォローアップ監視を外部副作用込みで仕上げる。

### 実装対象

DB:

- follow_ups
- external_operations

API:

- `POST /drafts/{id}/send`
- `POST /mails/send`
- `GET /follow-ups`
- `POST /follow-ups/{id}/resolve`
- `POST /follow-ups/{id}/dismiss`
- `POST /follow-ups/{id}/snooze`

画面:

- 送信前確認
- 送信履歴
- Mail右ガジェットからのFollow Up候補一覧
- 候補のResolve / Dismiss / Snooze

LLM:

- 初期実装ではFollow-up候補検出にLLMを使わない
- Dismissサンプルが溜まった後、必要に応じてLLMフィルタまたはルール改善に使う

外部副作用:

- Gmail send external_operation
- Gmail star external_operation

### 完了条件

- 送信前確認が出る
- Gmail送信がexternal_operation経由
- unknown時に自動再送しない
- 送信成功後にprocessedになる
- HighになったらGmailスター付与operationが作られる
- 送信メール本文からFollow-up候補を出せる
- AutoBody / quoted replyはFollow-up候補検出対象から除外される
- Follow-up候補をResolve / Dismiss / Snoozeできる
- Dismiss時に理由入力を求めない

### レビュー観点

- 送信前確認が邪魔すぎないか
- unknown時の表示が怖くないか
- Gmail送信済みのDB反映が分かりやすいか
- Follow-up候補が過剰に出すぎないか
- 手動操作が増えすぎていないか

---

## Phase 11: Case Context / Contact Context / 引継ぎログ

### 目的

案件の文脈を蓄積し、後任者や将来の自分に引き継げるようにする。

### 実装対象

DB:

- case_context_versions
- contact_context_versions
- handover_logs
- generated files

API:

- `GET /cases/{id}/context`
- `POST /cases/{id}/context/regenerate`
- `PATCH /cases/{id}/context`
- `GET /contacts/{id}/context`
- `POST /contacts/{id}/context/regenerate`
- `POST /cases/{id}/handover-log`

画面:

- Case Context編集
- Contact Context表示
- 引継ぎログ生成・編集・保存

LLM:

- case_context_update
- contact_context_update
- handover_log_generation

### 完了条件

- Case Contextを生成・確認・編集できる
- Contact Contextを生成できる
- 引継ぎログをMarkdownで生成できる
- 生成結果を編集してGenerated fileとして保存できる
- 高機密ファイル本文を勝手に含めない

### レビュー観点

- Case Contextが次のメール処理に役立つか
- 引継ぎログが「読める文書」になっているか
- 機密情報警告が適切か

---

## Phase 12: Backup / Restore / 証明書管理詳細

### 目的

運用保守を強化する。

### 実装対象

DB:

- backups
- backup_media
- schema_versions拡張

API:

- `GET /backups`
- `POST /backups/run`
- `POST /backups/{id}/restore`
- `POST /backups/{id}/test-result`
- `GET /client-certificates`
- `POST /client-certificates`
- `POST /client-certificates/{id}/revoke`
- `POST /client-certificates/{id}/create-renewal-task`

画面:

- バックアップ画面
- 証明書管理画面
- 復旧テスト記録
- Migration履歴

### 完了条件

- 証明書発行・失効できる
- 期限7日前Taskが作られる
- 手動バックアップできる
- バックアップ履歴が残る
- 復旧テスト結果を記録できる
- 復元前に外部副作用停止手順がある

### レビュー観点

- 証明書管理が理解できるか
- バックアップ手順が怖すぎないか
- 復元時にGmail送信が再実行されないか

---

## Phase 13: 後続拡張

### 候補

- Google Tasksエクスポート
- Case Series高度化（次回Case作成提案、系列テンプレート管理、周期リマインド）
- Recurring Task高度化（祝日・例外日・Calendar連携後の営業日調整）
- ポモドーロタイマー
- 高度な日程調整
- ファイル全文検索
- 案件内RAG
- GitHub / Overleaf連携
- PWA化
- 高度なモバイルUI
- 自動バックアップ高度化
- ログ圧縮・アーカイブ

### 方針

後続拡張は、既存のCase / Task / Mail / Contact / File / Eventの構造を壊さないように追加する。

---

# 3. レビュー運用

## 3.1 基本姿勢

ユーザーは、Codexに対して最初から完璧なUI指定をする必要はない。

むしろ、以下の方が効率がよい。

```text
1. 設計書に従ってまず動くものを作らせる。
2. 実際に触る。
3. 気に入らない部分を具体的に指摘する。
4. 小さく修正させる。
5. 何度も繰り返す。
```

特に画面は、実際に触らないと判断しづらい。

## 3.2 「次これ作って」より「これは違う」の方がよい場面

以下は、作ってから直す方がよい。

- メール一覧のカード密度
- ボタン配置
- タブの順番
- Case詳細の情報量
- Task一覧の見せ方
- Pending Contact処理の流れ
- Draft編集画面の使い勝手
- スマホ表示

これらは、仕様書だけで最適化しにくい。

## 3.3 先に厳密に指定すべき場面

以下は、実装前またはPR時に厳しく確認する。

- DBスキーマ
- migration
- 状態遷移
- 外部副作用
- 認証・セッション
- LLM入力保存方針
- Pending Contact
- Case削除の通常導線禁止と誤作成向け例外Delete
- Task論理削除
- Email Address単独Skip禁止
- Gmailスター仕様
- ProcessedとSkipの分離

ここを誤ると後から修正コストが高い。

## 3.4 レビューコメントの書き方

良いコメント例:

```text
この画面では未処理メールを最優先で見たいので、High/Middle/Pendingを上に分けて表示してください。

このボタン名だと「メールをCaseに紐づける」感じが強いので、「このCaseにメールを追加」に変えてください。

Task削除が物理DELETEになっています。deleted_atによる論理削除に直してください。

Gmail送信APIが直接Gmailを叩いています。external_operations経由にしてください。

Contact未登録Fromなのに重要度判定が走っています。Pendingで止めてください。
```

避けたいコメント例:

```text
なんか違う
いい感じにして
もっと使いやすく
仕様通りにして
```

ただし、UIについては「なんか違う」から始めてもよい。  
その場合、次に「何が違うか」を一緒に具体化する。

## 3.5 Codexへの依頼テンプレート

### 新機能実装依頼

```text
CaseClosedの設計書群に従って、[機能名] を実装してください。

対象設計書:
- [関連設計書名]

今回の対象:
- DB:
- API:
- Worker:
- 画面:
- テスト:

重要制約:
- ユーザー確定値をLLM/Systemで上書きしない
- 外部副作用はexternal_operations経由
- Task削除は論理削除
- Case削除は通常導線に出さず、誤作成向けの確認付き例外操作に限定する
- Email Address単独Skipは作らない

完了条件:
- ...
```

### 修正依頼

```text
以下の点を修正してください。

現状:
- ...

問題:
- ...

期待する挙動:
- ...

関連設計書:
- ...

テスト:
- この挙動を確認するunit/integration testを追加してください。
```

### UI修正依頼

```text
この画面を実際に使ってみたところ、以下が使いにくいです。

対象画面:
- ...

変更したい点:
- ...

残してほしい点:
- ...

変更してはいけない仕様:
- processedとSkipは混同しない
- Pending Contactの表示は残す
- Caseがメール集合を持つ表現は維持する
```

---

# 4. Phase別レビュー観点一覧

## Phase 1

- ログインできるか
- 24時間で切れるか
- 5回失敗ロックが効くか
- System Caseがあるか

## Phase 2

- Job状態が見えるか
- Write RequestがSingle DB Writer経由か
- unknownが自動再実行されないか

## Phase 3

- Pending Contactが解消しやすいか
- Email Address単独Skipがないか
- LLM自動Fillが便利か

## Phase 4

- メール一覧がまとめーる風か
- 日別表示があるか
- 未処理一覧があるか
- 3タブがあるか
- 検索が全メール対象か

## Phase 5

- High/Middle/Lowが実用的か
- Lowが要約されていないか
- Pending中にLLM判定されていないか
- Pinnedが要約されていないか
- メール生成の言語・宛先文脈が自然か
- HTMLメール・返信引用表示が破綻していないか

## Phase 6

- 添付ファイルを保存・再参照できるか
- Fileの保存場所と元メールが辿れるか
- LLM input許可/ブロックが効いているか
- 物理削除後もDBメタ情報が残るか
- Storage操作履歴がMaintenance / Debugで確認できるか

## Phase 7

- Case判定がユーザー確定値を上書きしないか
- Inbox required / no_case_neededが自然か
- CaseにMail / Fileを集約できるか

## Phase 8

- Case詳細が案件の基地になっているか
- Task化でprocessedになるか
- Task削除が論理削除か
- Case Closed条件が効いているか

## Phase 9

- 予定候補抽出が使えるか
- 登録前編集ができるか
- Calendar作成がexternal_operations経由か

## Phase 10

- Gmail送信が確認付きか
- 送信がexternal_operations経由か
- High時にGmailスターoperationが作られるか
- unknown時に止まるか

## Phase 11

- Case Contextが役に立つか
- 引継ぎログが読めるか
- 高機密情報を勝手に含めていないか

## Phase 12

- 証明書更新Taskが作られるか
- Backup履歴が見えるか
- Restore時に外部副作用が止まるか

---

# 5. 現在の到達状況と次の目標

当初の到達目標はPhase 4完了だったが、実装はメール実運用を優先して進んだ。

Phase 4完了時点で期待していた状態:

```text
安全にログインできる
System Caseが存在する
Job / Write Request / External Operation基盤がある
Pending Contact処理ができる
Gmail同期できる
Gmail本文をDB保存できる
まとめーる風メール一覧がある
読み込み日別表示がある
未処理メール一覧がある
受け取ったメール / 対応済み / Skipタブがある
全メール検索ができる
Pending中はLLM自動処理が止まる
```

現状はPhase 4を越えて、Phase 5のMail Intelligence、Phase 6のStorage基盤、Phase 7のCase連携基盤、Phase 8のTask中核、Phase 9のCalendar連携中核、Phase 10のGmail送信機能の一部まで先行実装済みである。

Phase 6のStorage基盤は、手元ファイル・メール添付・Contact画像・Storage一覧/詳細/検索/ディレクトリ・添付元メール参照・LLM input許可切替・物理削除・Storage操作履歴・ファイル更新バージョン管理・LLM Digest・Version Differenceまで実装済みである。Storage / Case Stored Files / Task Filesは、共通Storage Explorerを用いる方針に整理済みで、Root Directoryだけを変えて同じ移動・ドロップ・右クリック操作を使う。ディレクトリの再帰ドロップ、ディレクトリ移動、Case専用ディレクトリからCase本体へ戻る導線、右クリック「別ウィンドウで開く」、`.eml`表示、Markdown表表示を含む。

Phase 7のCase連携基盤はFix扱いとする。Case一覧/詳細、Case Genre、Case専用Storage Directory、引継ぎ資料特殊ディレクトリ、file_linksによる同一Storage objectの複数Case参照、Overview / Open When / Closed When / Genre / tags、Stakeholders、Current Situation手動生成、Mail Thread手動Assign / Remove、Case詳細Assigned Mail検索、Stored Files Window、右ガジェットCalendar枠、Case Toolsアイコンランチャーまで実装済みである。Case Toolsは「アイコン + URL」の単純なリンク集合として扱い、通常表示はアイコンのみ、設定時に追加・削除・ドラッグ並べ替えを行う。Case Tool Iconsはfile-iconsと同系統の仕組みで、登録URLとの部分一致が最も長いアイコンを採用する。

Current Situationは自動生成せず、ユーザーが「今どうなっていたか」を確認したい時にRefreshを押して生成する。入力にはCase概要、関連メールThread要約、Task情報、Calendar実データ、Case Storage内File Digestを含める。

LLM自動Case判定はPhase 7では実装しない。まず手動Assignと明示Auto Assign Rule運用を優先し、実運用で手間が大きい場合に、候補提示またはLLM自動判定として後続追加する。

Caseの繰り返し案件は、初期運用では独立したCase Series機能を急がず、手動Case作成とRecurring Taskで扱う。前年・前回Caseをテンプレートに次回Caseを作成する機能は、運用上の必要度を見て後続追加する。

Phase 8のTask中核はFix扱いとする。Task DB/API、Task一覧/詳細/新規作成/編集/削除/Done、Not Started / Inbox / Done / Archived、Start DateによるIn Progress化、Case詳細のNext Task / New Task導線、メールからLLM Task生成、Task Files、Progress Memo時系列、Completed Task FilesのCompleted Tasksディレクトリ移動、Recurring Task（毎週 / 2週に1度 / 毎月 / 毎年、月末・月末前日・第N曜日・最終曜日、Repeat設定から初回Start / Due Date自動補完）まで実装済みである。Case詳細のNext Taskは、Inbox相当の開始済み未完了Taskを優先し、存在しない場合だけNot Started Taskを表示する。表示時はInbox / Not Startedのバッジで区別する。

Phase 9のCalendar連携は中核実装済みである。Google Calendar OAuth scope拡張、Calendar API有効化前提、Calendar Event DB、Google Calendar同期ロード、複数Calendar Source同時表示、週表示、月ミニカレンダー、Upcoming、過去/参加不要イベントの薄表示、重複イベントの横分割、終日/複数日イベント、イベント詳細/編集、Calendar上DnD日時変更、手入力新規Event作成、メールからLLMでEvent作成、Case / Task / Mailリンク編集、Case詳細Calendarガジェット、Case Next Event接続まで実装済みである。Google Calendarを正本とし、DBは表示キャッシュとCaseClosed独自メタデータの保持に使う。

引継ぎ資料からのTask群生成を追加実装済みである。Case詳細のNew Task横から専用画面へ移動し、Caseの「引継ぎ資料」ディレクトリ内ファイルを選択して、追加プロンプトとともにLLMへ渡す。LLMはTask候補群を返し、ユーザーはNew Task画面に1件ずつ事前入力された状態で確認し、登録またはSkipする。入力ファイルはMarkdown / EML / DOCX / XLSXのテキスト抽出に対応し、Due Dateだけ取得できた場合はStart DateをDue Dateの1週間前で補完する。

フロントエンド共通化として、上部ナビゲーションはページ側が必要な導線を宣言する形へ整理し、Suggest入力はバッジ化・直下候補表示を共通コンポーネント化する方針とした。Mail宛先、Case/Taskリンク、Stakeholder、Calendar Linkなどは順次このSuggestInputへ寄せる。

Phase 6で未実装として残すもの:

```text
□ file_security_meta_classification
■ file_summary
□ Storage設定UIの本格化（Phase 9以降）
□ 保存失敗・取得失敗のMaintenance表示強化
■ file_linksによる明示的な多対多File参照
```

次の主目標はCalendar連携の仕上げと、引継ぎ資料Task生成の運用確認である。Task作業ブロック、祝日・例外日を考慮したRecurring Task調整、Google Calendarとの差分同期の自動化、Gmail特殊ロード検索画面、Storage設定UI、Maintenance表示強化は後続で扱う。Case Series / Create next Case、自動Case判定、特定メール到着によるTask自動作成ルールは実用上の必要度を見ながら追加する。`file_security_meta_classification` は引き続き保留する。

Phase 6開始時に特に確認する:

```text
■ 保存先ルートと容量方針
■ 物理ファイル名をIDベースにする方針
■ 元ファイル名・MIME・サイズ・hashの保存方針
■ メール添付をいつ取得するか
■ LLM投入可否Policyの初期値
■ 物理削除を正とし、DBメタ情報と操作履歴を残す方針
■ Storage操作履歴のMaintenance / Debug表示
■ 添付取得Jobを既存jobsへ載せ、失敗をMaintenance Job一覧で見えるようにする方針
□ 保存失敗・取得失敗のMaintenance表示強化
```



全体実装開始前に確認していた項目:

```text
□ 技術スタックを決めた
□ リポジトリ構成を決めた
□ migrationツールを決めた
□ test frameworkを決めた
□ 開発DBと本番DBを分ける
□ 本番データをWindows開発環境に置かない方針を確認した
□ mTLSはリバースプロキシで行う方針を確認した
□ Case削除は通常導線に出さず、誤作成向け例外Deleteのみ許可することを確認した
□ Task論理削除を確認した
□ Email Address単独Skipなしを確認した
□ 外部副作用はexternal_operations経由を確認した
□ LLM入力全文をllm_runsに保存しないことを確認した
```

---

# 6. 最初にCodexへ投げるべき依頼

最初の依頼は、いきなりGmail連携ではなく、土台作りにする。

ただし、実装より先にテストを作成する。  
最初のCodex依頼は「プロジェクト雛形実装」ではなく、「Phase 0〜1のテスト作成」から始める。

推奨依頼:

```text
CaseClosedの設計書群に従って、Phase 0〜1のテストを先に作成してください。

まだ本実装は行わないでください。

対象:
- /health endpointのテスト
- SQLite接続・migration実行のテスト
- app_settings / system_logs / audit_logs / cases / case_events のmigrationテスト
- Inbox Case と システムメンテナンス Case の初期データテスト
- ログイン成功・失敗・5回失敗ロック・24時間セッション失効のテスト
- System Caseを削除できないことのテスト
- 誤作成Case削除で関連Taskが論理削除され、通常完了CaseはArchive運用であることのテスト

重要:
- 既存テストは削除・弱体化しない
- 外部APIはmockしてください
- 設計書と矛盾する場合は質問してください
```

その次の依頼:

```text
CaseClosedの設計書群と追加済みテストに従って、プロジェクト雛形を作成してください。

対象:
- FastAPIアプリ雛形
- SQLite接続
- Alembic migration
- pytest
- app_settings / system_logs / audit_logs / cases / case_events の初期migration
- Inbox Case と システムメンテナンス Case の初期データ作成
- /health endpoint
- READMEに開発環境起動手順

まだGmail / LLM / Calendarは実装しないでください。

重要制約:
- Case削除は通常導線に出さず、誤作成向けの確認付き例外操作に限定する
- 本番secretを含めない
- migrationで初期データを投入できるようにする

完了条件:
- pytestが通る
- migrationを実行できる
- /healthが200を返す
- InboxとシステムメンテナンスCaseがDBに存在する
```

---

# 7. 最重要方針

```text
1. 設計書をすべて一度に実装させない。
2. Codexへの依頼は小さく切る。
3. UIはまず作って触って直す。
4. DB・状態遷移・外部副作用・認証は最初から厳しく見る。
5. 「これは気に入らない」は有効なレビュー。ただし、次に何が違うかを具体化する。
6. 画面は頻繁に変えてよい。
7. データモデルは安易に変えない。
8. Gmail送信・Calendar作成の二重実行を絶対に避ける。
9. Pending Contactを早期に使えるようにする。
10. まとめーる風メール一覧を初期UIの基準にする。
```
