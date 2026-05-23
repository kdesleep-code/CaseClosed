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
6. LLMで重要度・要約・Case判定できる
7. メールからTask / Draft / Calendarへ流せる
8. Caseにメール・Task・予定・Contact・Fileを集約できる
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
- Case削除APIが存在しないか
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
- Case削除APIが存在しない

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

### 完了条件

- Gmailからメールを取得できる
- 本文をDBに保存できる
- Contact未登録FromはPendingになる
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

## Phase 5: 重要度判定・要約・Case判定

### 目的

メールをLLMで整理し、Caseへ流し込めるようにする。

### 実装対象

LLM:

- mail_importance_classification
- mail_summary_ja
- mail_case_selection

DB:

- mail_summaries
- prompt_versions
- llm_runs
- llm_instruction_rules
- case_candidate_rules
- case_mail_links

API:

- `GET /llm-runs`
- `GET /llm-runs/{id}`
- `GET /mail-importance-rules`
- `POST /mail-importance-rules`
- `GET /case-candidate-rules`
- `POST /case-candidate-rules`
- `POST /mails/{id}/run-importance`
- `POST /mails/{id}/summarize`
- `POST /mails/{id}/run-case-selection`

画面:

- Mail一覧で要約表示
- Mail詳細でLLM結果表示
- LLM実行履歴
- LLM追加指示設定
- 重要度ルール設定

機能:

- High / Middle / Low判定
- High / Middleのみ自動要約
- High / MiddleのみCase判定
- Lowは自動要約なし
- HighならGmailスター付与external_operation
- LLMはPinned/Skip/Pendingを出力不可
- JSON schema validation
- JSON不正リトライ

### 完了条件

- Pending中はLLM重要度判定されない
- Contact解決後に重要度判定が走る
- Lowは要約されない
- HighになったらGmailスター付与operationが作られる
- Caseが関連メール集合を持つ形で表示される
- Inbox requiredはInboxへ入る
- no_case_neededはCaseリンクなし

### レビュー観点

- 重要度判定が実用上大きくズレないか
- 要約が一覧で役に立つか
- Case判定が勝手に変な上書きをしないか
- LLM失敗時の表示が分かりやすいか
- 追加指示を変えたくなる場所が見えているか

---

## Phase 6: Case / Task中核

### 目的

案件管理アプリとして機能させる。

### 実装対象

DB:

- tasks
- task_links
- task_suggestions
- task_work_blocks
- case_tags
- case_context_versions
- contact_case_links

API:

- `GET /cases`
- `POST /cases`
- `PATCH /cases/{id}`
- `POST /cases/{id}/close`
- `POST /cases/{id}/archive`
- `GET /cases/{id}/mails`
- `POST /cases/{id}/mails`
- `DELETE /cases/{id}/mails/{message_id}`
- `GET /tasks`
- `POST /tasks`
- `PATCH /tasks/{id}`
- `POST /tasks/{id}/complete`
- `POST /tasks/{id}/cancel`
- `DELETE /tasks/{id}`
- `POST /mails/{id}/create-task`
- `POST /mails/{id}/suggest-tasks`

画面:

- Case一覧
- Case詳細
- Task一覧
- Task詳細
- メールからTask作成画面/モーダル

LLM:

- mail_task_suggestion
- subtask_suggestionは後続でも可

### 完了条件

- Caseを作成・編集できる
- Case削除APIがない
- Case Closedできる
- 未完了TaskがあるCaseはClosed不可
- Task作成・完了・キャンセル・論理削除できる
- Task削除はdeleted_at
- メールからTask化したら原則processedになる
- Case詳細に関連メール・Taskが集約表示される

### レビュー観点

- Case一覧で「今止まっているもの」が分かるか
- Case詳細が案件の基地として機能しているか
- Task化の手数が少ないか
- Task削除が実削除になっていないか
- ClosedとArchiveの違いがUIで分かるか

---

## Phase 7: Draft / Gmail送信 / Follow-up基盤

### 目的

メール対応をアプリ内で完結させる。

### 実装対象

DB:

- mail_drafts
- follow_up_watches
- external_operations

API:

- `POST /mails/{id}/generate-reply-draft`
- `POST /drafts`
- `GET /drafts`
- `GET /drafts/{id}`
- `PATCH /drafts/{id}`
- `POST /drafts/{id}/regenerate`
- `POST /drafts/{id}/send`
- `POST /follow-up-watches`

画面:

- 返信草案画面/モーダル
- 新規メール作成画面
- Draft一覧/詳細
- Follow-up候補表示

LLM:

- reply_draft_generation
- new_mail_draft_generation
- reminder_mail_generation

外部副作用:

- Gmail send external_operation

### 完了条件

- 返信草案を生成・編集・保存できる
- 新規メールを作成できる
- 送信前確認が出る
- Gmail送信がexternal_operation経由
- unknown時に自動再送しない
- 送信成功後にprocessedになる
- 必要ならFollow-up Watch候補を出せる

### レビュー観点

- 返信草案が実用的か
- 新規メール作成の導線が自然か
- 送信前確認が邪魔すぎないか
- unknown時の表示が怖くないか
- Gmail送信済みのDB反映が分かりやすいか

---

## Phase 8: Calendar連携

### 目的

メールから予定化し、Case/TaskとGoogle Calendarをつなぐ。

### 実装対象

DB:

- calendar_event_links
- calendar_event_candidates

API:

- `GET /calendar/today`
- `GET /calendar/events`
- `POST /mails/{id}/extract-calendar-candidates`
- `POST /calendar/events`
- `PATCH /calendar/events/{id}/links`
- `POST /calendar/events/{id}/suggest-preparation-tasks`
- `POST /tasks/{id}/work-blocks`

画面:

- 今日の予定
- Calendar画面
- メールから予定作成画面
- Task作業ブロック作成UI

LLM:

- calendar_candidate_extraction
- preparation_task_suggestion

外部副作用:

- Google Calendar create/update external_operation

### 完了条件

- 今日の予定が表示される
- メールから予定候補を抽出できる
- ユーザー確認後にGoogle Calendarへ登録できる
- 作成後にメールがprocessedになる
- Calendar作成unknownは自動再実行しない
- Case詳細に関連予定が表示される

### レビュー観点

- 予定候補の日付・時刻抽出が信頼できるか
- 登録前編集がしやすいか
- Calendar説明欄に必要情報が入るか
- Google Calendarで開く導線があるか

---

## Phase 9: File / Storage基盤

### 目的

Caseにファイルを集約する。

### 実装対象

DB:

- files
- storage_objects
- file_links
- file_versions
- file_security_rules
- file_summaries

API:

- `GET /files`
- `GET /files/{id}`
- `POST /files/upload`
- `POST /attachments/{id}/fetch`
- `POST /files/{id}/summarize`
- `PATCH /files/{id}/llm-policy`
- `POST /files/{id}/trash`
- `POST /files/{id}/restore`
- `DELETE /files/{id}`

画面:

- File一覧
- File詳細
- Case詳細内Fileカード
- Mail添付カード

LLM:

- file_security_meta_classification
- file_summary

### 完了条件

- ファイルをローカル保存できる
- 物理保存はIDベース
- UIではCaseベース表示
- 添付元メールを辿れる
- LLM Policyを設定できる
- forbiddenはLLM投入不可
- trash / restore / purgeが区別される
- purge後もDBメタ情報は残る

### レビュー観点

- Case内ファイル表示が分かりやすいか
- LLM Policyが怖くないか
- 添付ファイル取得タイミングが適切か
- 誤削除しにくいか

---

## Phase 10: Case Context / Contact Context / 引継ぎログ

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

## Phase 11: Backup / Restore / 証明書管理詳細

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

## Phase 12: 後続拡張

### 候補

- Google Tasksエクスポート
- Recurring Task
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
- Case削除禁止
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
- Case削除は作らない
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
- High時にGmailスターoperationが作られるか

## Phase 6

- Case詳細が案件の基地になっているか
- Task化でprocessedになるか
- Task削除が論理削除か
- Case Closed条件が効いているか

## Phase 7

- Draft編集がしやすいか
- Gmail送信が確認付きか
- 送信がexternal_operations経由か
- unknown時に止まるか

## Phase 8

- 予定候補抽出が使えるか
- 登録前編集ができるか
- Calendar作成がexternal_operations経由か

## Phase 9

- FileがCase内で見やすいか
- LLM Policyが効いているか
- purge後もメタ情報が残るか

## Phase 10

- Case Contextが役に立つか
- 引継ぎログが読めるか
- 高機密情報を勝手に含めていないか

## Phase 11

- 証明書更新Taskが作られるか
- Backup履歴が見えるか
- Restore時に外部副作用が止まるか

---

# 5. 実装開始前チェックリスト

当面の到達目標はPhase 4完了とする。

Phase 4完了時点で期待する状態:

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

Phase 1〜2は省略せず、しっかり実装する。



実装開始前に確認する。

```text
□ 技術スタックを決めた
□ リポジトリ構成を決めた
□ migrationツールを決めた
□ test frameworkを決めた
□ 開発DBと本番DBを分ける
□ 本番データをWindows開発環境に置かない方針を確認した
□ mTLSはリバースプロキシで行う方針を確認した
□ Case削除なしを確認した
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
- Case削除APIが存在しないことのテスト

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
- Case削除APIは作らない
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
