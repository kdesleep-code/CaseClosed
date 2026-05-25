# CaseClosed 詳細設計書

Version: 0.5  
作成日: 2026-05-22  
対象: 個人用案件管理Webアプリ CaseClosed

---

## 0. 本書の位置づけ

本書は、大学教員の業務を「案件 / Case」単位で管理し、メール・タスク・予定・人物・ファイル・LLM支援・監査ログを統合する個人用業務支援Webアプリ **CaseClosed** の詳細設計書である。

本書は実装判断のための設計書であり、DB詳細設計、API詳細設計、画面詳細設計は必要に応じて別文書として切り出す。

本アプリは一般公開や外部リリースを前提としない本人専用システムである。そのため、一般的な意味でのMVPという概念は用いず、実装順序と優先度により段階的に利用可能範囲を広げる。

---

# 1. 全体アーキテクチャ

## 1.1 基本構成

```text
[Browser UI]
    |
[Web/API Process]
    |
    |-- Read API ----> SQLite read
    |
    |-- User Action --> Write Request
    |-- Job Request  --> Job Queue
    |-- Audit Event  --> Audit Log Writer
    |
[Orchestrator]
    |
[Dynamic Worker Pool]
    |-- Gmail Sync Worker
    |-- LLM Worker
    |-- Calendar Worker
    |-- File Worker
    |-- Context Update Worker
    |-- Report / Handover Worker
    |
[Single DB Writer]
    |
[SQLite DB + Local File Storage]
```

## 1.2 Web/API Process

担当:

- 画面表示
- ユーザー操作受付
- Read API
- Write Request作成
- Job作成
- Audit Log Request作成
- 軽量なバリデーション

業務テーブルへ直接writeしない。

## 1.3 Orchestrator

担当:

- Job Queue監視
- 優先度制御
- Dynamic Worker Poolへの割当
- 通常失敗時のリトライ制御
- Graceful Shutdown制御
- TimeEvent / Recurring Task発火

## 1.4 Dynamic Worker Pool

担当:

- Gmail同期
- LLM処理
- Calendar連携
- File処理
- Context更新
- Report / Handover生成

Worker数は動的可変とする。

設定項目:

- min_workers
- max_workers
- provider別rate limit
- LLM cost limit
- worker heartbeat timeout

## 1.5 Single DB Writer

業務DB更新を一元的に処理する。

原則:

- Web/APIやWorkerは業務テーブルへ直接writeしない
- Write Requestを優先度順に処理する
- ユーザー操作由来のWrite Requestを最優先する
- LLM/System由来のWrite Requestは user_* カラムを更新してはならない
- base_version競合時は安全側に倒す

## 1.6 Audit Log Writer

Audit Log専用Writer。

メール一覧表示、本文表示、ファイルカード表示など高頻度ログを処理する。業務DB更新用のSingle DB Writerを詰まらせないために分離する。

---

# 2. DB設計原則

## 2.1 基本原則

1. 外部由来の一次情報と、アプリ内の解釈・状態を分離する。
2. ユーザー確定値と自動推定値を分離する。
3. LLM / Systemは専用カラム・専用テーブルにのみ書く。
4. effective値はDB VIEWまたはRepository層で計算する。
5. Gmail、Google Calendarなど外部サービス由来の一次情報をアプリ側で汚さない。
6. ContactはGoogle Contactsと完全分離する。
7. Taskは正式な木構造を持つ。
8. Taskは論理削除とし、原則として物理削除しない。
9. FileはIDベースで物理保存し、UIではCaseベースで表示する。
10. LLM入力全文は原則ログに保存しない。ただしプロンプトエンジニアリングに必要な再構成情報は保存する。
11. QueueはMVP相当の初期実装ではSQLite、将来Redis/RQ/Celery等へ移行可能にする。

## 2.2 DB詳細設計の別文書化

本書では主要テーブルと設計原則までを扱う。

以下は別文書 `CaseClosed_DB_Detailed_Design.md` として作成する。

- 各テーブルのカラム
- 型
- NOT NULL制約
- unique制約
- index
- 外部キー
- 論理削除方針
- version管理
- migration方針
- VIEW / Repository層でのeffective値計算

---

# 3. 認証・アクセス制御

## 3.1 基本方針

認証・アクセス制御は他機能に先立って実装する。

```text
Tailscale
+
クライアント証明書認証
+
アプリ内パスワード認証
```

## 3.2 アクセス経路

- インターネットに直接公開しない
- Tailscale経由でのみ到達可能とする
- 有効なクライアント証明書を持つ端末のみ通す
- さらにアプリ内パスワードで24時間のセッション認証を行う

## 3.3 クライアント証明書認証

推奨実装:

- NginxまたはCaddy等のリバースプロキシでmTLSを行う
- アプリには検証済み証明書fingerprintをヘッダで渡す
- アプリ側はfingerprintを `client_certificates` と照合する

証明書仕様:

- 端末ごとに発行
- 有効期限は6か月
- 期限7日前に証明書更新Taskを自動生成
- 保守・運用画面から失効可能
- iPhone / iPad も証明書認証対象

証明書失効時には関連セッションを無効化する。

## 3.4 アプリ内パスワード認証

- PINではなくパスワード形式とする
- パスワードは安全なハッシュ方式で保存する
- ログイン失敗は5回まで
- 5回失敗した場合はアカウントをロックする
- ロック解除はサーバーへの物理アクセスを前提とした保守操作で行う
- ログイン後24時間で自動ログアウトする
- セッション延長は行わず、24時間経過時点で再認証とする

## 3.5 重要操作確認

追加認証ではなく確認ダイアログを出す。

対象:

- Gmail送信
- Google Calendar予定作成
- Gmailスター付与を伴う重要度変更
- LLM利用禁止ファイルのポリシー変更
- 証明書失効
- バックアップ復元
- 物理削除が将来必要になった場合

---

# 4. Core / Case設計

## 4.1 Caseの定義

Caseとは、完了状態が存在している一連の仕事である。

例:

- 授業運営
- 委員会業務
- 学生の研究
- 倫理審査
- 業績報告
- 出張手続き
- サーバー保守
- 本アプリの開発
- 本アプリの保守・運用
- システムメンテナンス

## 4.2 Case構造

Caseはフラットに管理する。親子関係は持たせない。分類はタグで表現する。

## 4.3 Case種別

```text
normal
recurring
system
```

### normal

通常の完了可能な案件。

### recurring

同一Caseが周期的にTaskを生成する案件。

### system

アプリ初期状態で作成される特殊Case。削除不可・アーカイブ不可。

代表例:

- Inbox / なんでも箱
- 本アプリの保守・運用
- システムメンテナンス

## 4.4 Case状態

### progress_status

```text
not_started
in_progress
closed
```

Caseの終結状態は、ソフト名 Case-Closed に合わせて `closed` と呼ぶ。
Taskの完了状態は `completed` のままとする。

### ball_status

```text
none
user
other
date_wait
stalled
```

### archive状態

`archived_at` で管理する。

```text
active: archived_at IS NULL
archived: archived_at IS NOT NULL
```

## 4.5 Case期限状態

Case本体には原則として独立した期限を持たせない。

期限は主にTaskに存在するものとし、Caseの期限状態は関連Taskから算出する。

UI上の期限状態例:

```text
no_deadline
has_deadline
due_soon
overdue
```

算出対象:

- Case配下の未完了Task
- Case配下の未完了Follow-up由来Task
- Calendar作業ブロックではなくTaskのdue_atを優先

DB詳細設計では、将来の例外に備えてCase固有期限を追加できる構造にしておくが、初期仕様では使わない。

## 4.6 Case Closed条件

Caseは、未完了Taskが残っている場合はClosed不可。

親Task・子Taskを含むすべてのTaskが以下のいずれかである必要がある。

```text
completed
canceled
deleted
```

`deleted` は論理削除済みTaskを指す。

CaseがClosedになった日時は `closed_at` で管理する。

## 4.7 Case削除

Caseは削除しない。

Closed後も情報追記・引継ぎログ生成・テンプレート化・翌年度参考に使うため、Caseはアーカイブで通常運用対象から外す。

---

# 5. 特殊Case

## 5.1 Inbox / なんでも箱

特殊な system Case。

目的:

- 対応が必要そうだが既存Caseに割り当てられないメールを置く
- Case未定のTaskを一時的に置く

LLM Case判定が `inbox_required` の場合は、Inbox Caseに自動紐づけする。

削除不可・アーカイブ不可。

## 5.2 本アプリの保守・運用

特殊な system Case。

対象Task例:

- クライアント証明書を更新する
- 証明書の有効期限を確認する
- 不要な証明書を失効する
- バックアップ結果を確認する
- 四半期フルバックアップを実行する
- 復旧テストを実施する
- システム更新を適用する

## 5.3 システムメンテナンス

特殊な system Case。

システム異常や運用上の注意をTask化する。

対象例:

- LLM Cost Limitを超過しそう
- LLM provider API key が失効している
- Gmail同期が継続失敗している
- Google Calendar連携が失敗している
- Jobが長時間滞留している
- Backupが失敗した
- 証明書期限が迫っている

Cost Limit超過または超過見込み時には、このCaseにTaskを自動生成する。

---

# 6. Recurring Case / 定期タスク

## 6.1 基本方針

「自動的に新しいCaseが立ち上がる」よりも、「同一Caseが毎年・毎月・毎週などの周期でTaskを生成する」ことを基本とする。

## 6.2 Recurring Task Template

Recurring Caseは定期タスクテンプレートを持つ。

例:

```text
Case: 情報リテラシー演習

毎年4月:
- 授業日程をGoogle Calendarへ登録する
- 初回資料を確認する

毎年3月:
- シラバスを確認する
```

## 6.3 重複生成防止

`generated_for_period` により、同じ年度・月・週などに同じTaskが重複生成されないようにする。

---

# 7. Task設計

## 7.1 Taskの定義

Taskは、ユーザー本人が実行する具体的なアクションである。

Taskは必ず1つのCaseに属する。

## 7.2 Taskに該当するもの

- メールに返信する
- リマインドを送る
- 書類を提出する
- 資料を確認する
- 授業スライドを作る
- 倫理審査書類を修正する
- サーバー更新を実施する

## 7.3 Taskに該当しないもの

- 返事を待つ
- 相手の確認待ち
- 会議当日を待つ

待つこと自体はTaskではない。一定期間返信がない場合に「リマインドを送る」Taskが発生する。

## 7.4 Task状態

```text
not_started
in_progress
completed
canceled
```

論理削除は状態ではなく `deleted_at` で管理する。

## 7.5 Task木構造

Taskは正式な木構造を持つ。

```text
Task
  ├─ Subtask
  │    └─ Sub-subtask
  └─ Subtask
```

`parent_task_id` により表現する。

## 7.6 親Task完了条件

未完了の下位Taskが存在する場合、親Taskは完了不可。

`completed` と `canceled` は閉じた状態とみなす。`deleted_at IS NOT NULL` のTaskは通常の完了判定から除外する。

## 7.7 Task削除

TaskはDBから実削除しない。

通常削除は `deleted_at` による論理削除とする。

```text
canceled:
  考慮したが不要。履歴として意味がある。

deleted_at:
  誤作成・ノイズ。通常画面から消すが、監査ログ・イベント整合性のためDBには残す。
```

将来的に物理削除機能を実装する場合も、保守・運用画面限定とし、audit/eventから参照されるTaskは物理削除不可とする。

## 7.8 LLMサブタスク候補

LLMが生成するサブタスクは、即正式Taskにはせず候補として表示する。ユーザーが採用・編集・破棄する。

---

# 8. Mail / Gmail設計

## 8.1 Gmail一次情報

Gmailから取得したメールは、一次情報として `gmail_messages` / `gmail_threads` に保存する。LLM結果やユーザー操作結果を混ぜない。

## 8.2 取得範囲

- 初回: 過去7日
- 通常: 差分取得
- 対象: 受信トレイ
- 送信済み: 直近分を取得
- アプリから送信したメールは即時DB反映を検討する

## 8.3 取得後の再監視

一度Gmailから読み込んだメールは、本文・スター状態・ラベル状態などを継続再監視しない。

スターについても、読み込み時点の状態を `external_importance` として保存する。

## 8.4 メール保持

処理済みになってもメールは保持し続ける。DB容量が増えた場合は、定期的にアーカイブ化する。

## 8.5 重要度分類

```text
Pinned
High
Middle
Low
Skip
Pending
```

### Pinned

旧Top。特殊枠・ピン留め。

- ユーザーまたは重要度フィルタのみ付与可能
- LLMは出力不可
- Case候補抽出・Case判定の対象外
- Gmailスターとは無関係

### High / Middle

通常の処理対象。

- LLM出力可能
- Case候補抽出・Case判定対象
- 自動和訳要約対象

### Low

LLMによる重要度判定で出力可能な低優先度ラベル。

- 自動和訳要約しない
- 自動Case判定しない
- 手動要約は将来許可してよい

### Skip

通常処理対象外。

- LLM出力不可
- Processedとは別扱い

### Pending

FromメールアドレスがContactsに存在しない場合の判定保留状態。

- 監視対象はFromのみ
- To/Cc/Bccの未知アドレスではPendingにしない
- メーリングリストやno-replyもContact未登録ならPending
- Pending中は重要度判定もCase判定も停止

## 8.6 重要度優先順位

```text
user_importance
> Contact Skip
> rule_importance
> external_importance
> llm_importance
```

`external_importance` は、読み込み時点のGmailスター等を指す。

## 8.7 Gmailスター連携

- Gmail読み込み時にスターが付いていたメールは `external_importance=High` 相当として扱う
- LLMがHighと判断したメールにはGmailスターを付与する
- ユーザーがアプリ上でHighにした場合もGmailスターを付与する
- Gmail側で後からスター解除されても、アプリ側の重要度は下げない
- 一度読み込んだメールのスター状態は再監視しない
- Pinnedはスターと無関係

Gmailスター付与は外部副作用であるため、`external_operations` 経由で行う。

## 8.8 メール処理状態

```text
unprocessed
processed
```

### processedになる操作

- 返信送信
- タスク化
- 予定化
- 手動で処理済みにする
- 不要として処理済みにする

### processedにならない操作

- 要約を読む
- 本文を開く
- 返信草案を作る
- Caseの関連メール集合に追加する
- 新規案件を作る
- Contact確認

## 8.9 SkipとProcessed

Skipは通常未処理一覧から除外するが、Processedとは別扱い。

## 8.10 Case判定実行条件

Case候補抽出・LLM Case判定は以下の場合のみ実行する。

```text
effective_importance ∈ {High, Middle}
```

手動でHigh/Middleへ変更された場合もCase判定を発火する。

Low、Skip、Pending、Pinnedでは自動Case判定しない。

---

# 9. 重要度フィルタ

## 9.1 条件

部分一致条件:

```text
From
To
Subject
Body
```

将来拡張候補:

```text
Cc
attachment filename
Gmail label
```

## 9.2 ルール優先順位

ルール一覧の上にあるものほど優先度が高い。最初に一致したルールを採用する。

## 9.3 ルール出力

```text
Pinned
High
Middle
Low
Skip
```

および、LLM重要度判定用の追加プロンプト。

## 9.4 From条件とSkip

メールアドレス単独Skipという概念は持たない。

Fromだけを理由に今後Skipしたい場合は、そのメールアドレスをContactに登録し、Contact自体を `skipped` にする。

重要度フィルタでは、Fromのみを条件とするSkipルールは作成しない。From条件を使う場合でも、Subject / Body / 添付 / Gmailラベルなどを含む複合条件Skipとして扱う。

```text
From = X
AND Subject contains "newsletter"
→ Skip
```

---

# 10. Contact設計

## 10.1 基本方針

ContactはGoogle Contactsとは完全に別管理する。外部に出したくない情報を持つ可能性が高いため、アプリ内独自DBを正本とする。

## 10.2 ContactとEmail Address

ContactとEmailAddressは分離する。

- 1人のContactが複数メールアドレスを持てる
- 優先メールアドレスを持つ
- リマインダーメールなどは全メールアドレス宛送信も可能

## 10.3 Contact状態

```text
active
skipped
archived
```

## 10.4 Email Address状態

Email Addressには以下の状態のみを持たせる。

```text
unresolved
linked
```

Email Address単位のSkip状態は持たない。

メールアドレス単独Skipという概念も持たない。Fromだけを理由に今後Skipしたい場合は、そのメールアドレスをContactに登録し、Contact自体を `skipped` にする。

## 10.5 未知メールアドレス

未知メールアドレスとは、CaseClosedのContact DBに情報がないメールアドレスを指す。

メール重要度判定でPendingになるかどうかの監視対象はFromのみである。

## 10.6 Pending Contact登録支援

Contact未登録Fromから来たメールはPendingになる。

Pending中は、重要度判定、Case判定、自動和訳要約を停止する。

ただし、Contact登録画面の自動Fillを目的とするLLM処理だけは例外的に実行可能とする。これは初期運用時にPendingが大量発生する負担を下げるためである。

LLMは、メール本文、署名、件名、送信者アドレスなどから以下を候補生成する。

```text
表示名
所属・組織
役職・立場
推奨タグ
メモ
Skip候補理由
信頼度
```

生成結果は正式Contactではなく、ユーザーが採用・編集・破棄する候補として保存する。

## 10.7 Contact Skip

Contactが `skipped` の場合、そのContactに紐づくメールアドレスからのメールは重要度判定前にSkip扱いとする。

Address Skipは存在しない。

ただし、個別メールに対するユーザー明示的な重要度変更は優先する。

## 10.8 Contact Merge

既存Contact同士を1人の人物として統合できるようにする。マージ履歴を保存する。

## 10.9 Contact Tags

タグは自由入力。初期タグは用意しない。

用途:

- 宛先補完
- タグAND送信
- Case候補判定
- LLM文脈
- 関連人物表示

---

# 11. Case判定

## 11.1 基本方針

Case判定は2段階で行う。

```text
1. Case候補抽出
2. LLMによる最終Case判定
```

## 11.2 Case候補抽出

各Caseが「この条件なら候補になりうる」というルールを持つ。

条件例:

- Subject / Body キーワード
- From / To
- Contactタグ
- 過去の手動紐づけ
- Caseタグ
- 除外キーワード

## 11.3 LLM Case判定結果

```text
existing_case
inbox_required
no_case_needed
new_case_candidate
uncertain
```

### existing_case

既存Caseに自動紐づけする。

### inbox_required

Inbox Caseに自動紐づけする。

### no_case_needed

広告メール・通知・ニュースレターなど、案件化不要なメール。Caseリンクなし。

### new_case_candidate

新規Case候補としてユーザーに提示する。即時Case作成はしない。

### uncertain

判断不能としてユーザー確認に回す。

## 11.4 Caseが持つ関連メール集合

本アプリでは、概念上「メールがCaseに紐づく」というより、Caseが関連メール集合を持つものとして扱う。

自動判定では、1通のメールは原則として1つのprimary Caseの関連メール集合に追加される。

手動操作として「別の案件にコピー」を許可する。この場合、主Caseとは別に、副次Caseの関連メール集合にも同じメールを表示できる。

DB設計では `case_mail_links` のようなリンクテーブルを採用し、`link_role = primary / copy` を持たせることを推奨する。

---

# 12. LLM支援機能

## 12.1 共通方針

全LLM実行は `llm_runs` に保存する。

保存するもの:

- function_type
- model_name
- provider_name
- prompt_version_id
- input_hash
- input_source_json
- input_diagnostic_json
- applied_instruction_rule_ids_json
- output_json
- status
- error_type
- error_message
- retry_count
- token数
- 推定コスト

原則保存しないもの:

- メール本文全文
- ファイル本文全文
- LLM入力全文

ただし、プロンプトエンジニアリングと品質改善のため、入力を再構成するための参照情報、バージョン、hash、抽象化された入力概要、適用された追加指示ルールIDは保存する。

## 12.2 Prompt Version / Output Schema

LLMプロンプトと出力JSON schemaは `prompt_versions` でfunction_typeごとに版管理する。

保存対象:

- system_prompt_template
- user_prompt_template
- retry_prompt_template
- output_schema_json
- default model / provider
- temperature等の基本パラメータ

schema変更時はprompt_versionを上げる。過去の `llm_runs` は実行時の `prompt_version_id` を参照する。

## 12.3 LLM追加指示ルール

ユーザーは、送信者、Contactタグ、Caseタグ、件名、本文キーワード等に応じて、LLMへの追加指示を登録できる。

例:

- 学生からのメールでは、学生が行うべきことと自分が行うべきことを分けて書く
- 事務メールでは、締切と提出先を強調する
- 返信文面は簡潔にし、今後の対応を中心に書く
- 査読依頼では、専門分野との合致度を表示する

追加指示は `llm_instruction_rules` に保存し、対象function_type、条件、優先順位、有効/無効を管理する。

複数ルールが一致した場合は、優先順位順に適用する。適用されたルールIDは `llm_runs.applied_instruction_rule_ids_json` に保存する。

## 12.4 自動実行LLM

- メール重要度判定
- High / Middleメールの和訳要約
- Case判定
- 案件入りスレッド全体要約
- Case Context更新
- Contact Context更新
- ファイル機密度メタ判定

Lowメールは重要度判定の出力としては許可するが、自動要約・自動Case判定は行わない。

## 12.5 手動実行LLM

- 返信草案生成
- 新規メール草案生成
- メールからタスク化
- サブタスク候補生成
- 予定候補抽出
- 準備タスク候補生成
- リマインドメール生成
- 引継ぎログ生成
- ファイル本文要約

## 12.6 LLM失敗時の扱い

### システム連携上の失敗

例:

- JSON不正
- schema不一致
- 必須フィールド欠落
- API timeout
- rate limit
- provider error

対応:

- 自動リトライする
- JSON不正やschema不一致の場合は、修復指示を追加したプロンプトで再実行する
- retry_count上限を超えた場合は失敗状態として保存し、必要に応じてシステムメンテナンスCaseにTaskを生成する

### 品質上の不十分さ

例:

- 人間が見て返信草案がやや不自然
- 要約が少し弱い
- 推奨アクションが完全ではない

対応:

- システム失敗とはみなさない
- UIに表示する
- ユーザーが手動修正できるようにする
- 再生成・追加プロンプトによる修正を可能にする

## 12.7 Cost Limit

LLM cost limitを設定可能にする。

cost limitを超過しそうな場合、または超過した場合は、システムメンテナンスCaseにTaskを自動生成する。

自動LLM処理は停止または制限する。手動LLM実行については、UIで警告した上で実行可否を判断する。

## 12.8 和訳要約

High / Middleメールは読み込み時に和訳要約を自動生成する。

形式:

- 概要: 3〜5行の自然文
- 要対応
- 期限
- 次アクション
- key_points

## 12.9 返信草案

- ユーザー操作時のみ生成
- Gmail Draftではなくアプリ内draft
- 送信しないで画面遷移した場合も保持
- 再度生成ボタンを押した場合、既存草案をまず提示
- 追加プロンプト付き再実行では既存草案を入力に含めて修正

---

# 13. Calendar連携

## 13.1 基本方針

予定の正本はGoogle Calendar。

アプリ側にはGoogle Calendar event IDと関連Case/Task/Mailを保持する。

## 13.2 Google Calendar説明欄

以下を記載する。

- Case名
- Task名
- 元メール件名
- 元メールのGmailリンク

アプリ内リンクは入れない。

## 13.3 メールから予定作成

UIフロー:

```text
メール詳細
→ 予定候補抽出
→ ユーザー確認・編集
→ Google Calendar登録
→ メールは処理済み
→ 画面はその場に維持
```

予定作成後、予定作成ボタンは準備Task生成ボタンへ変化する。

## 13.4 作業ブロック

TaskをGoogle Calendarに作業ブロックとして置ける。

- 予定名は `案件名：タスク名` を基本とする
- 自由編集可能
- Calendarに置くと `scheduled_minutes` に反映
- 実施済みにすると `worked_minutes` に反映

---

# 14. Google Tasks連携

Google Tasks連携は後続拡張とする。

方針:

- CaseClosed内Taskを外部表示・通知・モバイル確認用にエクスポートする可能性がある
- Google TasksはTaskの正本ではない
- 初期実装ではImportや双方向同期を行わない
- 詳細仕様は将来決定する

---

# 15. Follow-up Watch / リマインド

## 15.1 基本方針

返信待ちはTaskではない。一定期間返信がなければ、リマインドTaskが自動生成される。

## 15.2 作成条件

- ユーザーが「返信を待つ」を明示した場合
- LLMが候補提示し、ユーザーが承認した場合

すべての送信メールに自動では作らない。

## 15.3 待ち期間

デフォルトは1週間。ユーザー指定可能。

## 15.4 状態

```text
active
fulfilled
reminder_task_created
closed
```

## 15.5 解除条件

- 同一Gmail threadに相手から返信が来た
- ユーザーが手動解除
- リマインドTask完了
- リマインドメール送信

---

# 16. File / Storage設計

## 16.1 基本方針

ファイル正本はアプリ内ローカルストレージに置く。

## 16.2 物理保存

物理配置はIDベース。UI表示はCaseベース。ダウンロード時は元のファイル名に戻す。

## 16.3 添付ファイル

メール取得時は添付メタ情報のみ保存する。

重要度・Case判定後に以下を満たすものだけ実体を取得する。

- High / Middleメールの添付
- Caseが推定できたメールの添付

## 16.4 LLM Policy

```text
allowed
confirm_required
forbidden
```

`forbidden` は完全禁止。手動でポリシー変更しない限り、LLM本文投入不可。

## 16.5 ファイル削除

通常削除は論理削除、つまりゴミ箱。保守・運用画面から物理削除できる余地は残す。

物理削除後もDBメタ情報は残す。

---

# 17. 監査ログ・操作履歴

## 17.1 ログ種別

```text
Audit Log
System Log
Event Log
```

## 17.2 Audit Log

ユーザーが何を見たか、何を操作したか、どの情報に接触した可能性があるかを記録する。

例:

- メール一覧表示
- メール本文表示
- ファイルカード表示
- ファイルダウンロード
- Gmail送信
- Gmailスター付与
- Task完了
- Task論理削除
- Case関連メール変更
- 証明書失効

## 17.3 メール一覧表示ログ

メール一覧に含まれたメールIDをすべて `mail_list_exposed` として記録する。

## 17.4 LLM投入ログ

LLM入力全文は原則保存しない。

input_hash、参照ID、入力再構成に必要なsource情報、関連Contextのversionを保存する。

## 17.5 ログ閲覧

保守・運用画面から一覧 + 絞り込み。

条件:

- 日時範囲
- ログ種別
- 操作種別
- 対象種別
- Case
- Contact
- Mail
- File
- LLM機能
- エラーのみ

---

# 18. API設計方針

## 18.1 基本原則

- API名は英語で統一
- Read APIは直接DB read
- Audit LogはAudit Log Writerへ送る
- 業務DB更新はSingle DB Writer経由
- 単純編集はPATCH
- 業務操作はPOST action
- 実体削除は原則使わず、論理削除はPOST actionまたはPATCH
- 外部副作用はexternal_operations経由
- 軽い操作はoptimistic_stateで即時反映

## 18.2 PATCH / POST action

### PATCH

単純な属性編集。

例:

```http
PATCH /cases/{case_id}
PATCH /tasks/{task_id}
PATCH /contacts/{contact_id}
```

### POST action

業務上意味を持つ操作。

例:

```http
POST /cases/{case_id}/complete
POST /tasks/{task_id}/complete
POST /tasks/{task_id}/delete
POST /mails/{mail_id}/process
POST /drafts/{draft_id}/send
POST /files/{file_id}/trash
```

## 18.3 optimistic_state

メール処理済み化、Task完了、Case関連メール変更など軽い操作では、APIレスポンスに `optimistic_state` を返し、UIを即時反映する。

### 推奨仕様

- APIレスポンスには `write_request_id` を含める
- UIは `optimistic_state` を即時反映する
- 対象レコードには `pending_write_request_id` を表示用に紐づける
- DB反映完了後、UIは実DB状態で再同期する
- DB反映失敗時は、該当箇所に失敗表示を出し、必要に応じて再試行ボタンを出す
- base_version競合時は自動上書きせず、ユーザーに競合表示を出す
- 複数タブ操作では、最新DB状態を優先し、古いoptimistic_stateは破棄する

### optimistic_stateの有効期限

初期値として30秒を推奨する。

30秒を超えてDB反映が確認できない場合、UIは「反映待ち」または「確認が必要」と表示する。

---

# 19. Job / Worker / DB Writer

## 19.1 Job優先度

```text
Priority 0:
  ユーザー操作由来DB更新

Priority 10:
  ユーザー操作由来LLM処理

Priority 20:
  Gmail送信後UI反映
  Calendar作成後反映
  Gmailスター付与後反映

Priority 50:
  Gmail同期
  重要度判定
  Case判定
  和訳要約

Priority 70:
  スレッド要約
  Case/Contact Context更新

Priority 100:
  添付取得
  ファイル機密度判定

Priority 200:
  バックアップ
  アーカイブ
  クリーンアップ
```

## 19.2 Job失敗と復旧

通常失敗:

- retry_count上限まで自動リトライする
- JSON不正など修復可能なLLM失敗では、プロンプト修正つきでリトライする

プロセス停止・サーバーダウン:

- runningのまま残ったstale jobは、初期実装では自動再実行しない
- 保守・運用画面で確認できるようにする
- 将来的にstale job検出・再実行を検討する

## 19.3 Graceful Shutdown

保守・運用画面から実行可能。

手順:

1. 新規Job受付停止
2. 実行中Jobの完了待ち
3. pending Write Request反映
4. Worker停止
5. DB Writer停止
6. サービス停止可能状態へ

---

# 20. External Operation

## 20.1 基本方針

外部副作用を伴う操作は `external_operations` を通す。

対象:

- Gmail送信
- Gmailスター付与
- Google Calendar予定作成
- Google Calendar予定変更
- Google Tasksエクスポート

## 20.2 状態

```text
pending
running
succeeded
failed
unknown
canceled
```

`unknown` は、通信断等で外部副作用が起きたか不明な場合に使用する。

## 20.3 二重実行防止

`external_operations` には以下を持たせる。

- operation_type
- idempotency_key
- request_payload_hash
- external_id
- attempt_count
- last_attempt_at
- unknown_reason
- manual_resolution_required

### Gmail送信

Gmail送信は二重送信が最も危険である。

- `unknown` になった場合は自動再実行しない
- ユーザー確認待ちにする
- Gmail側で送信済みを確認した上で手動解決する

### Gmailスター付与

スター付与は比較的低リスクだが、外部副作用として記録する。

- succeeded後に状態反映
- failed時は再試行可
- unknown時は必要に応じて手動確認

### Google Calendar予定作成

- external_idにGoogle Calendar event IDを保存する
- unknown時は自動再実行しない
- Google Calendar上に重複予定がないか確認して手動解決する

---

# 21. バックアップ・復旧

## 21.1 基本方針

バックアップ・復旧は設計上重要な機能として扱う。ただし、実装優先度は初期中核機能より下げる。

## 21.2 バックアップ対象

- SQLite DB
- ファイルストレージ
- 設定情報
- 証明書管理情報
- 監査ログ
- System Log
- Event Log
- Case Context
- Contact Context
- prompt_versions

## 21.3 バックアップ先

- 外付けHDD/SSD
- クラウドバックアップは原則用いない
- バックアップは暗号化して保存する

## 21.4 バックアップ頻度

推奨初期設定:

- 週1回の増分バックアップ
- 四半期に1回のフルバックアップ

ただし、実装初期では手動バックアップから開始してよい。

## 21.5 復旧方針

任意のバックアップ日時を選んで復元できることを目標とする。

復旧時の注意:

- 復元直後は外部API Jobを自動再開しない
- `external_operations` の `pending/running/unknown` は手動確認対象にする
- Gmail送信やCalendar作成の二重実行を避ける
- 復旧後に整合性チェックを行う

## 21.6 復旧テスト

復旧テストは「本アプリの保守・運用」Caseに定期Taskとして生成する。

---

# 22. 既存まとめーる資産の扱い

## 22.1 基本方針

CaseClosedはほぼ新規実装とする。まとめーるのコードはCaseClosedリポジトリに入れない。

## 22.2 継承するもの

- メール確認を入口とする考え方
- 重要度フィルタ
- Pinned / High / Middle / Low / Skip的な分類
- LLMによる要約・返信草案生成
- タグによる宛先指定
- メール詳細から少ない操作で処理する操作感

## 22.3 継承しないもの

- 既存コード
- 既存DB構造
- 既存フィルタ設定
- HTML生成中心の画面構造

## 22.4 HTML生成

静的HTML生成機能は正式には継承しない。

ただし、日付別・重要度別にメールを確認するレビュー画面は、CaseClosedのWeb UIとして実装する。

---

# 23. 開発・テスト環境

## 23.1 環境分離

```text
Development:
  Windows PC
  VS Code
  テスト用DB
  テスト用storage

Staging:
  Windows仮本番またはUbuntu上の別環境
  実Gmail/Calendar連携は制限付き

Production:
  Ubuntuサーバー
  本番DB
  本番storage
  Tailscale + client certificate
  外付けHDD/SSDバックアップ
```

## 23.2 ディレクトリ構成案

```text
caseclosed/
  app/
    api/
    core/
    db/
    models/
    services/
    workers/
    llm/
    repositories/
    templates/
    static/
  migrations/
  storage/
    objects/
    generated/
    trash/
  logs/
  config/
  tests/
```

## 23.3 設定

環境ごとに `.env` を分ける。

```text
CASECLOSED_ENV=development|staging|production
DATABASE_URL=sqlite:///...
STORAGE_ROOT=...
GMAIL_CLIENT_SECRET_PATH=...
GOOGLE_TOKEN_PATH=...
LLM_PROVIDER=...
LLM_MODEL_DEFAULT=...
```

## 23.4 本番データ方針

Windows開発環境には本番データを原則保持しない。本番データはUbuntu側に置く。

---

# 24. テスト方針

## 24.1 基本方針

UIの完全自動テストより、以下のロジックテストを重視する。

- 状態遷移
- Write Request反映
- ユーザー値保護
- LLM出力パース
- 外部副作用の二重実行防止
- Contact Pending処理
- Task木構造制約
- 論理削除と監査ログ整合性

## 24.2 必須ユニットテスト

### Mail

- Fromが未知アドレスのメールがPendingになる
- To/Ccが未知でもFromが既知ならPendingにならない
- no-replyやメーリングリストもContact未登録ならPendingになる
- Contact Skipが重要度フィルタより優先される
- user_importanceがContact Skipより優先される
- Gmailスター読み込み時にexternal_importanceが設定される
- Gmail側スター解除を再監視しない
- LLMはPinned/Skip/Pendingを出力できない
- LowはLLM重要度判定で出力可能
- Lowでは自動要約・自動Case判定が発火しない
- High/MiddleのみCase判定Jobが発火する
- 手動でHigh/Middleに変えた時もCase判定Jobが発火する
- Skipメールはprocessedとは別扱い

### Case

- 未完了TaskがあるCaseはClosed不可
- completed/canceled TaskのみならCaseをClosedにできる
- deleted_at付きTaskはCase Closed判定から除外される
- archived Caseは通常一覧から除外される
- closed_atとarchived_atが分離される
- system Caseは削除不可・アーカイブ不可
- Case本体に期限がなくてもTask期限から期限状態が算出される

### Task

- 未完了下位Taskがある親Taskは完了不可
- canceled下位Taskは閉じた状態として扱われる
- Task削除はdeleted_atによる論理削除になる
- 論理削除Taskは通常一覧から除外される
- サブタスク候補は採用時のみ正式Taskになる

### Contact

- 未知Fromメールアドレスはunresolvedになる
- unresolvedを既存Contactに紐づけられる
- Contact mergeでメールアドレス・タグ・関連Caseが統合される
- Fromだけを理由にSkipしたい場合はContactを `skipped` にする
- Email Address単位のSkip状態は存在しない

### LLM

- JSON schemaに合うか
- 必須フィールドがあるか
- 不正JSON時にリトライされるか
- 修復プロンプト付きで再実行されるか
- High/Middle/Low以外を出した時に拒否されるか
- 追加プロンプト再実行で既存結果が入力に含まれるか
- llm_runsに履歴が残るか
- Cost Limit超過時にシステムメンテナンスCaseへTaskが生成されるか

### External Operation

- Gmail送信が二重実行されない
- Gmailスター付与がexternal_operations経由になる
- unknown状態で安易に再実行されない
- succeeded後にexternal_idが保存される
- Calendar作成unknown時に自動再実行されない

## 24.3 結合テスト

- Gmail同期 → Pending判定 → Contact解決 → 重要度判定 → 和訳要約 → Case判定
- Gmailスター付きメール → external_importance High → 表示
- LLM High判定 → Gmailスター付与 → external_operations succeeded
- メールから返信草案 → 編集 → 送信 → 処理済み化
- メールから予定抽出 → Calendar作成 → 処理済み化
- 送信メール → follow-up watch → 期限超過 → リマインドTask生成
- Task木構造 → 子Task完了 → 親Task完了
- Task論理削除 → 通常一覧非表示 → 監査ログ整合
- File upload → 機密度判定 → trash → restore → purge
- Graceful Shutdown
- Backup復元後にexternal_operationsが自動再実行されない

---

# 25. 実装順序

MVPという用語は用いない。以下の順に段階的に実装する。

## Stage 1：安全な土台

1. プロジェクト雛形
2. SQLite + migration
3. system_logs
4. client_certificates
5. sessions
6. audit_logs
7. ログイン画面
8. 証明書管理画面
9. 保守・運用画面の最小版

## Stage 2：処理基盤

1. jobs
2. write_requests
3. QueueInterface
4. SQLiteQueue
5. Single DB Writer
6. Audit Log Writer
7. Dynamic Worker Pool
8. Graceful Shutdown
9. optimistic_state基本処理

## Stage 3：Case / Contact基盤

1. cases
2. system cases
3. case_tags
4. case_events
5. contacts
6. contact_email_addresses
7. contact_tags
8. unresolved address
9. Contact Skip
10. Contact merge
11. contact_group_aliases

## Stage 4：Gmail取り込み・メールUI

1. Gmail API設定
2. gmail_messages
3. gmail_threads
4. 添付メタ情報
5. 初回7日取得
6. 差分取得
7. Gmailスター読み込み時external_importance保存
8. メール一覧
9. メール詳細
10. mail_user_state
11. mail_auto_state
12. Pending Contact処理

## Stage 5：重要度判定・LLM要約

1. mail_importance_rules
2. Contact Skip優先処理
3. llm_runs
4. prompt_versions
5. llm_instruction_rules
6. LLM重要度判定
5. High/Middle和訳要約
6. Lowでは要約しない制御
7. Gmailスター付与external_operation
8. mail_summaries

## Stage 6：Case判定・Context更新

1. case_candidate_rules
2. case_mail_links
3. LLM Case判定
4. existing_case紐づけ
5. inbox_required自動紐づけ
6. no_case_neededリンクなし処理
7. 別Caseへの手動コピー
8. case_context_versions
9. contact_context_versions
10. スレッド全体要約

## Stage 7：返信・送信

1. mail_drafts
2. 返信草案生成
3. 新規メール草案生成
4. 既存草案再表示
5. Gmail送信
6. external_operations
7. unknown時の手動確認
8. 送信済み即時反映
9. 処理済み化

## Stage 8：Task

1. tasks
2. task_links
3. Task木構造
4. Task論理削除
5. メールからTask化
6. Case未定時Inbox配下Task化
7. task_suggestions
8. サブタスク候補生成

## Stage 9：Calendar / Follow-up

1. calendar_event_links
2. 今日の予定取得
3. メールから予定作成
4. 準備Task生成
5. follow_up_watches
6. リマインドTask
7. リマインドメール生成

## Stage 10：Recurring / File / Handover / Backup

1. recurring_task_templates
2. generated_recurring_tasks
3. files
4. storage_objects
5. file_links
6. file_security_rules
7. Gmail添付保存
8. バックアップ・復旧基本機能
9. 引継ぎログ生成

---

# 26. 後続拡張

初期実装後に検討する。

- iPhone / iPad向け本格UI最適化
- PWA化
- フローティング・ポモドーロタイマー
- PDF / Word / Excel本文抽出・プレビュー
- ファイル全文検索
- 案件内RAG
- Google Tasks連携
- 高度な日程調整支援
- 作業ブロック自動分割配置
- LLMによるプロンプト再調整
- オンプレミスLLM対応
- Redis / RQ / CeleryへのQueue移行
- Job自動復旧
- ログ自動アーカイブ・圧縮
- 引継ぎログのPDF / Word / HTML出力
- 大学暦・学期連動のRecurring Case
- GitHub / Overleaf高度連携
- Gmailラベル指定拡張
- Contact高度分析

---

# 27. 主要テーブル一覧

## Core

- cases
- case_tags
- case_context_versions
- case_events
- system_cases

## Task

- tasks
- task_links
- task_suggestions
- task_work_blocks

## Mail

- gmail_messages
- gmail_threads
- gmail_attachments_meta
- mail_user_state
- mail_auto_state
- mail_summaries
- mail_thread_summaries
- mail_drafts
- case_mail_links
- follow_up_watches

## Contact

- contacts
- contact_email_addresses
- contact_tags
- contact_context_versions
- contact_case_links
- contact_group_aliases
- contact_merge_history

## Calendar

- calendar_event_links
- calendar_event_candidates

## File

- files
- storage_objects
- file_links
- file_versions
- file_security_rules
- file_summaries

## LLM

- llm_runs
- prompt_versions
- llm_instruction_rules
- handover_logs

## Logs / Events

- audit_logs
- system_logs
- events

## Jobs / Queue

- jobs
- write_requests
- external_operations

## Auth

- client_certificates
- sessions
- login_attempts

## Settings / Rules

- app_settings
- mail_importance_rules
- case_candidate_rules
- llm_instruction_rules

## Recurring

- recurring_task_templates
- generated_recurring_tasks

## Backup

- backup_runs
- backup_media
- restore_runs

---

# 28. 未確定・実装時判断事項

以下は、実装中に現物を見ながら調整する。

- UIレイアウト
- トップ画面の優先表示順
- モバイルUIの詳細
- LLMプロンプト本文
- APIごとのPATCH / POST action最終判断
- 各テーブルの細かい型・index
- Worker数のデフォルト値
- LLMモデルの初期選定
- バックアップの詳細運用
- HTML/Markdown/PDF出力の細部

ただし、必要なボタン・操作が存在しない状態は避ける。

メール詳細画面には少なくとも以下の操作を用意する。

- 返信草案生成
- 送信
- タスク化
- 予定化
- Case変更
- 別Caseへコピー
- 新規Case候補作成
- Contact解決
- 処理済み
- 不要として処理済み
- 重要度変更
- フィルタ作成
- Gmailで開く

---

# 29. 設計上の最重要原則

```text
1. ユーザー操作を待たせない。
2. ユーザー操作をLLMや自動処理で上書きしない。
3. 外部一次情報とアプリ内解釈を混ぜない。
4. SQLite書き込みはSingle DB Writerに集約する。
5. Contact情報はGoogle Contactsへ出さない。
6. LLM入力全文は原則ログに保存しないが、プロンプト改善に必要な再構成情報は保存する。
7. 外部API副作用は二重実行しない。
8. TaskとCaseの完了条件を曖昧にしない。
9. Taskは実削除せず、論理削除する。
10. Caseは削除しない。
11. Gmailスターはexternal_importanceとして扱う。
12. PendingはFrom未知アドレスに限定し、Pending中は重要度判定・Case判定を止める。
13. Lowは重要度ラベルとしては使うが、自動要約・自動Case判定しない。
14. UIは最初から完成形を狙わず、触りながら調整する。
15. 機能追加ごとに必要テーブルをmigrationで追加する。
```
# Phase 4 Contact Memo Split Note

Contact memo is split into two ownership domains.

- User memo: manually edited by the user and never overwritten by LLM workers.
- AI memo: maintained by future LLM Contact context update flow from received mail/thread history.

The former single Contact memo is migrated to User memo. AI memo starts empty and is displayed separately in Contact detail UI.
