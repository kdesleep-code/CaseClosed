# CaseClosed 画面仕様書

Version: 0.1  
作成日: 2026-05-22  
対象: 個人用案件管理Webアプリ CaseClosed

---

## 0. 本書の位置づけ

本書は、CaseClosed の主要画面について、表示項目、必須操作、呼び出すAPI、状態変化、監査ログ対象を定義する画面仕様書である。

本書は以下の既存設計書を前提とする。

- CaseClosed 概要設計書
- CaseClosed 詳細設計書
- CaseClosed DB設計書
- CaseClosed API設計書
- CaseClosed Worker / Job / External Operation設計書

本書では、厳密なUIレイアウトや配色は固定しない。  
実装者は、PC / iPad / iPhone で使いやすいレスポンシブUIを設計してよい。

ただし、各画面で必要な情報・操作ボタン・状態遷移・API呼び出しは、本書に従う。


特にメール一覧画面については、既存の「まとめーる」の日別メール確認ビューを初期UIの重要な参考とする。  
CaseClosedでは最終的に案件中心のUIへ発展させるが、メール入口の操作感については、最初から過度に作り替えず、まとめーるで既に使いやすい部分を引き継ぐ。

ただし、初期実装の画面は確定版ではない。  
まず動く画面を作り、実際に使いながら頻繁に修正することを前提とする。

---

# 1. UI全体方針

## 1.1 基本思想

CaseClosed のUIは、以下を目的とする。

```text
案件を遅滞なく、連絡漏れなく、スムーズにClosedする。
```

画面設計では、以下を重視する。

1. 未処理メールを見逃さない。
2. 自分側で止まっているTaskを見逃さない。
3. Pending Contactを早く解消できる。
4. メールからCase / Task / Calendar / Contactへ少ない操作で流せる。
5. LLM生成結果は修正可能な候補として扱う。
6. ユーザー操作を待たせない。
7. 外部副作用は明示的に確認できる。
8. モバイルでは短時間確認・軽処理を優先する。

## 1.2 レスポンシブ方針

### PC

- 情報量多め。
- 2〜3カラム表示を許可。
- メール一覧 + 詳細 + Case/Task情報の同時表示を重視する。
- 管理画面・設定画面・証明書管理・バックアップ確認はPC主対象。

### iPad

- PCに近い操作を可能にする。
- 2カラム程度を許可。
- メール処理、Case確認、Task確認、返信草案編集まで対応する。

### iPhone

- カード型UIを基本とする。
- 一覧 → 詳細 → 操作 の縦遷移を基本とする。
- 重要メール確認、処理済み化、簡易返信、Task作成、予定確認を重視する。
- 複雑な設定・保守操作・大量ファイル整理は原則PC推奨。

## 1.3 共通UI要素

全画面または主要画面に共通して以下を持つ。

### グローバルナビゲーション

- Top
- Mail
- Cases
- Tasks
- Calendar
- Contacts
- Files
- Logs
- Settings
- Maintenance

### 共通通知領域

以下の通知を表示する。

- Job失敗
- External Operation unknown
- Gmail送信失敗
- Calendar作成失敗
- LLM Cost Limit警告
- 証明書期限接近
- バックアップ未確認
- stale job発生
- Pending Contact件数

### 確認ダイアログ対象

以下は確認ダイアログを必須とする。

- Gmail送信
- Google Calendar予定作成
- LLM利用禁止ファイルのポリシー変更
- 証明書失効
- バックアップ復元
- 物理削除
- Case関連の不可逆に近い操作
- unknown external operation の手動解決

---

# 2. 画面種別と実装単位

## 2.1 画面の分類

CaseClosedでは、すべての機能を必ずグローバルナビゲーション上の独立画面として扱うわけではない。  
ただし、ユーザーが明確な作業単位として利用するものは、画面仕様上の「画面」または「サブ画面」として定義する。

画面種別は以下に分ける。

### Primary Screen

グローバルナビゲーションから直接到達する主要画面。

例:

- Top
- Mail
- Cases
- Tasks
- Calendar
- Contacts
- Files
- Logs
- Settings
- Maintenance

### Detail Screen

一覧や関連リンクから遷移する詳細画面。

例:

- Mail詳細
- Case詳細
- Task詳細
- Contact詳細
- File詳細
- Draft詳細
- LLM実行履歴詳細

### Work Screen / Work Modal

特定の作業を完了するための画面またはモーダル。  
グローバルナビゲーションには出さない場合があるが、画面仕様としては明示する。

例:

- 新規メール作成
- 返信草案編集
- 新規Case作成
- メールからTask作成
- メールから予定作成
- Contact登録
- LLM追加プロンプト入力
- ファイルアップロード
- 引継ぎログ生成

### Admin / Maintenance Screen

保守・運用のための画面。

例:

- 証明書管理
- バックアップ
- Job管理
- External Operation確認
- Worker状態確認

## 2.2 中核機能と後続機能

本プロジェクトではMVPという用語は使わないが、実装順序上の優先度は存在する。

中核機能以外も、将来追加するだけの「未設計機能」とはしない。  
ただし、初期実装時にはすべての画面を同じ完成度で作る必要はない。

方針:

```text
Priority A:
  毎日使う中核画面。最初から操作可能にする。

Priority B:
  中核と強く関係する補助画面。初期から入口・最低限の画面は用意する。

Priority C:
  後続拡張。設計上の置き場所は確保するが、初期実装では簡易版または未実装でもよい。
```

## 2.3 新規メール作成の扱い

新規メール作成は、Mail一覧やDraft画面の付属機能ではなく、Work Screenとして明示的に扱う。

ただし、グローバルナビゲーションに「Compose」を独立表示するかどうかはUI実装時に判断する。

基本導線:

- Mail一覧から「新規メール」
- Case詳細から「このCaseに関連する新規メール」
- Contact詳細から「このContactに新規メール」
- Draft一覧から「新規Draft」
- Task詳細から「このTaskに関連するメール」

新規メール作成画面は、作成後すぐ送信するのではなく、まず `mail_drafts` に保存する。  
送信時のみ Gmail送信 `external_operation` を作成する。

---

# 3. Top画面

## 2.1 目的

Top画面は、ユーザーが最初に見る業務ダッシュボードである。

目的は以下である。

- 今日対応すべきものを把握する。
- 未処理メールに入る。
- Pending Contactを解消する。
- 自分側で止まっているTaskを確認する。
- システムメンテナンス上の重要警告を確認する。

## 2.2 表示項目

### 今日の予定

- Google Calendar由来の予定
- Case名
- Task名
- 開始時刻
- 終了時刻
- 場所
- 元メールリンクがあれば表示

API:

```http
GET /calendar/today
```

### 未処理メールサマリ

- High件数
- Middle件数
- Pending件数
- Pinned件数
- 未処理総数

API:

```http
GET /mails/summary
```

### 未処理メールカード

優先順:

1. Pinned
2. High
3. Middle
4. Pending
5. Lowは原則Topでは折りたたみ

表示項目:

- 件名
- From
- 受信日時
- effective_importance
- processed_status
- Pending理由
- Case名
- 要約
- 次アクション
- 締切候補

API:

```http
GET /mails?processed=unprocessed&limit=...
```

### Pending Contactカード

- 未登録Fromアドレス
- 推定表示名
- 推定所属
- 推定タグ
- 件数
- 最新メール日時

API:

```http
GET /contacts/unresolved-from-addresses
```

### 自分側Task

条件:

```text
Task.status ∈ {not_started, in_progress}
かつ Case.ball_status = user または Task.due_atが近い
```

表示項目:

- Task名
- Case名
- due_at
- status
- 優先度
- 関連メール

API:

```http
GET /tasks?focus=user
```

### システムメンテナンス警告

- LLM Cost Limit
- stale job
- unknown external operation
- 証明書期限
- バックアップ未確認

API:

```http
GET /maintenance/summary
```

## 2.3 必須操作

- メール詳細を開く
- Pending Contact処理画面を開く
- Task詳細を開く
- 今日の予定を開く
- システムメンテナンスCaseを開く
- メールを処理済みにする
- メールから返信草案を作る
- メールからTask化する
- メールから予定化する

## 2.4 監査ログ

- メールカード表示は `mail_list_exposed`
- 予定表示は通常監査ログではなく event/system寄りでよい
- ファイルカードがTopに出る場合は `file_card_exposed`

---

# 4. Mail一覧画面

## 4.1 目的

メール一覧画面は、既存まとめーる由来のメール処理入口である。

単なるメールクライアントではなく、メールをCase、Task、Calendar、Contactへ流し込むための処理画面である。

初期実装では、既存まとめーるの日別メール確認ビューを強く参考にする。  
ユーザーは現行まとめーるの一覧画面を比較的気に入っているため、CaseClosedの初期メール一覧は、まとめーるの操作感を大きく壊さないことを重視する。

## 4.2 初期UI方針

メール一覧画面は、最初から完成形を狙わない。  
まず、まとめーるに近い画面を作り、実際に使いながら変更する。

初期方針:

```text
1. 読み込んだ日別の表示を可能にする。
2. 未処理メール一覧は別枠で用意する。
3. 受け取ったメール一覧 / 対応済みメール一覧 / Skipされたメール一覧はタブで切り替える。
4. 検索は現在表示中リストへのマスクではなく、過去の全メールに対して検索し、検索結果一覧を表示する。
5. 重要度順 / 受信時刻順で並び替え可能にする。
6. 新規メール作成、Contact、未処理メール、Task、Case、ルール設定への導線を置く。
```

この画面は、CaseClosedの案件中心設計へつなぐ入口である。  
ただし、メール処理の実務上の使いやすさを優先し、画面構造は実運用で積極的に修正してよい。

## 4.3 表示モード

### 日別表示

Gmail同期またはメール読み込みを行った日ごとに、メール一覧を表示できる。

表示単位:

```text
読み込み日
```

であり、必ずしもメール受信日と一致しなくてよい。

表示項目:

- 読み込み日
- その日に読み込んだスレッド数
- その日に読み込んだメール件数
- 生成/同期時刻
- 前日/翌日移動
- 日付カレンダー

API:

```http
GET /mails/by-loaded-date?date=YYYY-MM-DD
GET /mails/loaded-dates
```

### 未処理メール一覧

日別表示とは別に、未処理メールだけを集めた一覧を用意する。

これはTop画面にも概要表示するが、Mail画面では独立した一覧として操作できるようにする。

API:

```http
GET /mails?processed=unprocessed
```

### タブ表示

メール一覧画面には、少なくとも以下のタブを置く。

```text
受け取ったメール一覧
対応済みメール一覧
Skipされたメール一覧
```

#### 受け取ったメール一覧

通常の受信・取得メール一覧。  
未処理/処理済みを含めてもよいが、初期表示では未処理または当日読み込み分を優先する。

#### 対応済みメール一覧

`processed_status = processed` のメールを表示する。

#### Skipされたメール一覧

`effective_importance = Skip` またはContact skipped等により通常処理対象外になったメールを表示する。  
SkipはProcessedとは別概念である。

API:

```http
GET /mails?tab=received
GET /mails?tab=completed
GET /mails?tab=skipped
```

## 4.4 検索方針

検索は、現在表示中の一覧をその場で絞り込むだけのマスク検索ではない。

検索は、DBに保存された過去の全メールを対象として実行し、検索結果一覧画面または検索結果モードとして表示する。

対象:

- 件名
- From
- To
- Cc
- 本文
- 要約
- 添付ファイル名
- Case名
- Contact名

API:

```http
GET /mails/search?q=...
```

検索結果では、通常のメールカードと同じ操作を可能にする。

## 4.5 並び替え

最低限、以下を用意する。

```text
重要度順
受信時刻順
```

将来候補:

```text
読み込み時刻順
Case順
期限候補順
未処理優先
```

API:

```http
GET /mails?sort=importance
GET /mails?sort=received_at
```

## 4.6 表示項目

各メールカードに以下を表示する。

- 件名
- From
- To
- Cc簡易表示
- 受信日時
- 読み込み日時
- Gmailリンク
- effective_importance
- importance根拠
- processed_status
- 対応完了日時
- Pending状態
- Case表示
- 要約
- snippet
- 次アクション
- 添付有無
- 添付種別サマリ
- スター由来かどうか
- Pinnedかどうか
- 同一Thread内メール件数

## 4.7 上部導線

メール一覧画面上部には、少なくとも以下への導線を置く。

- Gmailからメールを同期する
- 新規メール作成
- Contact / アドレス帳
- 未処理メール一覧
- Task一覧
- Case一覧
- 重要度ルール
- LLMへの追加指示

実装上、グローバルナビゲーションと重複してもよい。  
メール処理中にすぐ使う導線を優先する。

## 4.8 必須操作

- メール詳細を開く
- 新規メール作成
- 重要度変更
- Pinned設定 / 解除
- 処理済みにする
- 不要として処理済みにする
- Caseへ入れる
- 別Caseへコピー
- 新規Case作成
- Task化
- 予定化
- 返信草案生成
- Contact登録
- フィルタ作成
- Gmailで開く
- 添付情報を確認する

## 4.9 API対応

```http
GET /mails
GET /mails/by-loaded-date
GET /mails/search
GET /mails/{message_id}
POST /mails/{message_id}/importance
POST /mails/{message_id}/pin
POST /mails/{message_id}/process
POST /mails/{message_id}/create-task
POST /mails/{message_id}/create-calendar-event-candidate
POST /mails/{message_id}/generate-reply-draft
POST /cases/{case_id}/mails
POST /cases
POST /drafts
POST /mail-importance-rules
```

## 4.10 Pendingメールの表示

Pendingメールは以下を明示する。

```text
Contact未登録Fromのため、重要度判定・Case判定・自動要約は停止中です。
```

操作:

- Contact登録画面を開く
- LLM自動Fillを実行
- Contactを作成
- 既存Contactにメールアドレスを追加
- Contact skippedとして登録

## 4.11 監査ログ

メール一覧に表示されたメールIDは、exposure batchとして記録する。

```text
audit_exposure_batches
audit_exposure_items
```

日別一覧、未処理一覧、検索結果一覧、対応済み一覧、Skip一覧のいずれでも、表示されたメールは接触可能性ありとして記録する。

## 4.12 初期実装後の調整前提

メール一覧画面は、実運用で最も変更される可能性が高い画面である。

したがって、実装者は以下を前提にする。

```text
1. 初期版はまとめーるに近い構造で作る。
2. レイアウト・タブ構成・カード密度・ボタン配置は運用しながら頻繁に変更する。
3. ただし、日別表示、未処理別枠、3タブ、全メール検索は初期仕様として保持する。
4. CaseClosed独自のCase/Task/Contact操作は、まとめーる風UIに追加する形で導入する。
```

# 5. Mail詳細画面

## 4.1 目的

メール詳細画面は、1通または1スレッドを確認し、必要な処理を完了させる画面である。

## 4.2 表示項目

- 件名
- From
- To
- Cc
- 受信日時
- Gmailリンク
- Thread情報
- 本文テキスト
- HTML本文表示
- 添付情報
- effective_importance
- importance根拠
- processed_status
- Pending理由
- 関連Case一覧
- primary Case
- copy Case
- 関連Task
- 関連Calendar Event
- LLM要約
- LLM次アクション
- 返信草案
- 予定候補
- Contact情報

API:

```http
GET /mails/{message_id}
GET /mails/{message_id}/thread
```

## 4.3 必須操作

### メール処理

- 処理済みにする
- 不要として処理済みにする
- 重要度変更
- Pinned設定 / 解除
- Gmailで開く

### Case操作

- Caseへ入れる
- primary Caseを変更する
- 別Caseへコピー
- Caseから外す
- 新規Caseを作成して入れる

API:

```http
POST /cases/{case_id}/mails
DELETE /cases/{case_id}/mails/{message_id}
POST /cases
```

### Task操作

- メールからTask作成
- 既存Taskへ関連付け
- LLMでTask候補抽出
- サブタスク候補生成

API:

```http
POST /mails/{message_id}/create-task
POST /tasks/{task_id}/mails
POST /mails/{message_id}/suggest-tasks
```

メールからTask作成した場合、原則としてメールは `processed` になる。

### Calendar操作

- 予定候補抽出
- Google Calendarへ予定作成
- 準備Task候補生成

API:

```http
POST /mails/{message_id}/extract-calendar-candidates
POST /calendar/events
POST /calendar/events/{event_id}/suggest-preparation-tasks
```

### Draft操作

- 返信草案生成
- 既存草案表示
- 草案編集
- 追加プロンプト付き再生成
- Gmail送信

API:

```http
POST /mails/{message_id}/generate-reply-draft
GET /drafts?message_id=...
PATCH /drafts/{draft_id}
POST /drafts/{draft_id}/regenerate
POST /drafts/{draft_id}/send
```

`POST /drafts/{draft_id}/send` はGmail送信External Operationを作成する。

### Contact操作

- Fromを新規Contact登録
- 既存ContactにFromメールアドレスを追加
- Contact skippedとして登録
- LLM自動Fill

API:

```http
POST /contacts
POST /contacts/{contact_id}/email-addresses
POST /contacts/{contact_id}/skip
POST /contacts/unresolved-from-addresses/{encoded_email}/generate-prefill
```

## 4.4 添付ファイル表示

表示項目:

- ファイル名
- MIME type
- サイズ
- 取得状態
- 関連Case
- LLM Policy
- ダウンロード可否

操作:

- 添付実体取得
- Caseファイルとして保存
- プレビュー
- ダウンロード
- LLM要約
- LLM Policy変更

API:

```http
GET /mails/{message_id}/attachments
POST /attachments/{attachment_id}/fetch
POST /files/{file_id}/summarize
PATCH /files/{file_id}/llm-policy
```

## 4.5 監査ログ

- 本文表示: `mail_body_viewed`
- HTML本文表示: `mail_body_viewed`
- Gmailで開く: `gmail_link_opened`
- 添付カード表示: `file_card_exposed`
- 添付ダウンロード: `file_downloaded`
- Gmail送信: `gmail_sent`

---

# 6. Pending Contact処理画面

## 5.1 目的

Contact未登録FromによりPendingになっているメールをまとめて処理する画面である。

初期運用ではPendingが大量に発生することが想定されるため、独立画面として用意する。

## 5.2 表示項目

アドレス単位で表示する。

- Fromメールアドレス
- 表示名候補
- 最新メール件名
- 最新メール日時
- 該当メール件数
- LLM推定表示名
- LLM推定所属
- LLM推定役職
- LLM推定タグ
- LLM推定メモ
- Skip候補理由
- 信頼度

API:

```http
GET /contacts/unresolved-from-addresses
```

## 5.3 必須操作

- LLM自動Fill実行
- 新規Contact作成
- 既存Contactへ追加
- Contact skippedとして作成
- 該当メール一覧を開く
- 最新メール詳細を開く
- 候補破棄
- 再生成

API:

```http
POST /contacts/unresolved-from-addresses/{encoded_email}/generate-prefill
POST /contacts
POST /contacts/{contact_id}/email-addresses
POST /contacts/{contact_id}/skip
GET /mails?from=...
```

## 5.4 処理後の挙動

Contact登録・既存Contact追加・Contact skipped化後、対象メールはPendingから解除される。

その後、以下のJobを発火する。

- Contact skippedなら、対象メールをSkip扱いにする。
- active Contactなら、重要度判定Jobを発火する。
- High / Middleになれば、Case判定・自動要約を発火する。

## 5.5 監査ログ

- Pending Contact一覧表示
- Contact作成
- Contact skip
- LLM自動Fill実行
- 該当メール一覧表示

---

# 7. Case一覧画面

## 6.1 目的

現在動いているCaseを俯瞰し、自分側で止まっているCase、最近更新されたCase、Closed待ちCaseを確認する。

## 6.2 表示項目

- Case名
- タグ
- progress_status
- ball_status
- open Task数
- overdue Task数
- 直近イベント
- 関連未処理メール件数
- 関連ファイル件数
- closed_at
- archived_at

API:

```http
GET /cases
```

## 6.3 フィルタ

- active
- closed
- archived
- system case
- ball_status
- tag
- 未処理メールあり
- overdue Taskあり
- 最近更新

## 6.4 必須操作

- Case詳細を開く
- 新規Case作成
- Case編集
- CaseをClosedにする
- Archiveする
- タグ編集
- System Caseを開く

API:

```http
POST /cases
PATCH /cases/{case_id}
POST /cases/{case_id}/close
POST /cases/{case_id}/archive
```

Case削除は提供しない。

---

# 8. Case詳細画面

## 7.1 目的

Case詳細画面は、Caseが持つメール・Task・予定・人物・ファイル・文脈・イベントを集約表示する中心画面である。

## 7.2 表示項目

### Case概要

- Case名
- 説明
- タグ
- progress_status
- ball_status
- closed_at
- archived_at
- system_case_type

### 関連メール集合

Caseが持つメール集合として表示する。

表示項目:

- 件名
- From
- 受信日時
- importance
- processed_status
- link_role
- 要約
- Gmailリンク

API:

```http
GET /cases/{case_id}/mails
```

### Task一覧

- open Task
- completed Task
- canceled Task
- deleted Taskは通常非表示
- 木構造表示

API:

```http
GET /cases/{case_id}/tasks
```

### Calendar

- 関連予定
- 作業ブロック
- 元メール

API:

```http
GET /cases/{case_id}/calendar-events
```

### Contacts

- 関連Contact
- 関係性メモ
- タグ

API:

```http
GET /cases/{case_id}/contacts
```

### Files

- ファイルカード
- Origin
- LLM Policy
- 機密度メモ
- 添付元メール

API:

```http
GET /cases/{case_id}/files
```

### Case Context

- 現在のCase Context
- 更新日時
- 生成元
- 再生成ボタン
- 手動編集

API:

```http
GET /cases/{case_id}/context
POST /cases/{case_id}/context/regenerate
PATCH /cases/{case_id}/context
```

### Event History

- メール受信
- メール処理済み
- Task作成
- Task完了
- 予定作成
- ファイル保存
- Case Context更新
- Closed
- Archived

API:

```http
GET /cases/{case_id}/events
```

## 7.3 必須操作

- Case編集
- CaseをClosedにする
- Archiveする
- メールを追加
- メールを別Caseへコピー
- Task作成
- Task完了
- Calendar作業ブロック作成
- Contact追加
- Fileアップロード
- 外部リンク追加
- Case Context再生成
- 引継ぎログ生成
- Gmailで関連メールを開く

## 7.4 Closed条件

CaseをClosedにする場合、未完了Taskが残っていてはならない。

閉じた状態とみなすTask:

```text
completed
canceled
```

未完了Taskがある場合は、Closed操作時に一覧表示し、完了またはCancelを促す。

## 7.5 System Case

以下のSystem Caseは削除不可・Archive不可・Closed不可または原則非推奨とする。

- Inbox
- システムメンテナンス

---

# 9. Task一覧画面

## 8.1 目的

ユーザー本人が実行すべき作業を確認し、処理する画面である。

## 8.2 表示モード

- 今日
- 今週
- 期限超過
- 自分側
- Case別
- 未着手
- 進行中
- Completed
- Canceled
- Deletedは通常非表示

API:

```http
GET /tasks
```

## 8.3 表示項目

- Task名
- Case名
- 親Task
- 状態
- due_at
- estimate_minutes
- scheduled_minutes
- worked_minutes
- 関連メール
- 関連予定
- 作成元
- LLM候補由来か

## 8.4 必須操作

- Task詳細を開く
- 新規Task作成
- 状態変更
- Completedにする
- Canceledにする
- 論理削除
- 子Task作成
- Calendarへ作業ブロック配置
- 関連メールを開く
- 関連Caseを開く

API:

```http
POST /tasks
PATCH /tasks/{task_id}
POST /tasks/{task_id}/complete
POST /tasks/{task_id}/cancel
DELETE /tasks/{task_id}
POST /tasks/{task_id}/subtasks
POST /tasks/{task_id}/work-blocks
```

## 8.5 完了条件

未完了の下位Taskがある親TaskはCompleted不可。

閉じた状態:

```text
completed
canceled
```

---

# 10. Task詳細画面

## 9.1 表示項目

- Task名
- 説明
- Case
- 親Task
- 子Task
- 状態
- due_at
- estimate_minutes
- scheduled_minutes
- worked_minutes
- 関連メール
- 関連予定
- 関連ファイル
- メモ
- 作成元
- イベント履歴

## 9.2 必須操作

- 編集
- Completed
- Canceled
- 論理削除
- 子Task追加
- 関連メール追加
- Calendar配置
- 作業時間記録
- Caseを開く
- 関連メールを開く

---

# 11. Calendar画面

## 10.1 目的

Google Calendar上の予定とCase / Task / Mailの関係を確認し、予定作成や作業ブロック配置を行う。

## 10.2 表示項目

- 今日の予定
- 今週の予定
- Case関連予定
- Task作業ブロック
- 元メール
- Google Calendarリンク

API:

```http
GET /calendar/events
```

## 10.3 必須操作

- 予定詳細を開く
- Caseへ関連付け
- Taskへ関連付け
- Google Calendarで開く
- メールから作成された予定を確認
- Task作業ブロック作成

API:

```http
POST /calendar/events
PATCH /calendar/events/{event_id}/links
POST /tasks/{task_id}/work-blocks
```

## 10.4 外部副作用

Google Calendar予定作成・変更は `external_operations` 経由。

`unknown` になった場合は自動再実行しない。

---

# 12. Contact一覧画面

## 11.1 目的

人物・組織・タグを管理し、メール処理・Case判定・宛先補完に使う。

## 11.2 表示項目

- 表示名
- メールアドレス
- status
- タグ
- 関連Case数
- 未処理メール数
- 最終メール日時
- メモ

API:

```http
GET /contacts
```

## 11.3 フィルタ

- active
- skipped
- archived
- tag
- organization
- 未解決アドレスあり
- 最近追加

## 11.4 必須操作

- Contact詳細を開く
- 新規Contact作成
- 編集
- skipped化
- activeへ戻す
- archived化
- メールアドレス追加
- タグ編集
- Merge
- 関連Case確認

API:

```http
POST /contacts
PATCH /contacts/{contact_id}
POST /contacts/{contact_id}/skip
POST /contacts/{contact_id}/activate
POST /contacts/{contact_id}/archive
POST /contacts/{contact_id}/email-addresses
POST /contacts/merge
```

---

# 13. Contact詳細画面

## 12.1 表示項目

- 表示名
- status
- メールアドレス一覧
- 優先メールアドレス
- タグ
- メモ
- 関連Case
- 関連メール
- Contact Context
- Merge履歴

## 12.2 必須操作

- 編集
- メールアドレス追加
- メールアドレス削除
- 優先メールアドレス変更
- skipped化
- active化
- archived化
- タグ編集
- 関連Caseを見る
- 関連メールを見る
- Contact Context再生成

## 12.3 注意

Email Address単独Skipは存在しない。

Fromだけを理由にメールをSkipしたい場合は、Contact自体を skipped にする。

---

# 14. 新規メール作成画面

## 14.1 目的

新規メール作成画面は、Gmail上の既存スレッドへの返信ではなく、新しいメールを作成するためのWork Screenである。

本画面は、Case、Contact、Task、Mailのいずれかを起点として開くことができる。

## 14.2 起動元

- Mail一覧の「新規メール」
- Case詳細の「このCaseに関連する新規メール」
- Contact詳細の「このContactへメール」
- Task詳細の「このTaskに関連するメール」
- Draft一覧の「新規Draft」

## 14.3 表示項目

- To
- Cc
- Bcc
- Subject
- Body
- 関連Case
- 関連Task
- 関連Contact
- 添付ファイル
- LLM追加プロンプト
- 既存Draft候補
- 送信前確認状態

API:

```http
GET /contacts/search
GET /cases/search
GET /tasks/search
POST /drafts
GET /drafts/{draft_id}
```

## 14.4 必須操作

- 宛先補完
- タグAND指定による宛先展開
- Case関連付け
- Task関連付け
- Contact関連付け
- 本文保存
- LLMによる本文草案生成
- 追加プロンプト付き再生成
- 添付追加
- Draft保存
- Gmail送信
- 破棄

API:

```http
POST /drafts
PATCH /drafts/{draft_id}
POST /drafts/{draft_id}/generate
POST /drafts/{draft_id}/regenerate
POST /drafts/{draft_id}/attachments
POST /drafts/{draft_id}/send
DELETE /drafts/{draft_id}
```

## 14.5 保存方針

新規メールは、作成開始時または初回保存時に `mail_drafts` として保存する。

```text
draft_type = new_mail
```

送信しないで画面を離れてもDraftは保持する。

## 14.6 送信方針

Gmail送信前に確認ダイアログを表示する。

送信APIは直接Gmailへ送らず、`gmail_send` external_operationを作成する。

`unknown` になった場合は自動再送しない。

## 14.7 送信後の挙動

送信成功後、以下を行う。

- Draftをsent扱いにする
- Gmail送信済みメールをDBへ反映する
- 関連Caseがあれば、Caseの関連メール集合に追加する
- 関連Taskがあれば、Taskイベントに記録する
- 必要に応じてFollow-up Watch作成候補を表示する

## 14.8 監査ログ

- Draft作成
- Draft編集
- LLM草案生成
- 添付追加
- Gmail送信
- 宛先展開


# 15. Draft画面

## 13.1 目的

LLMで生成された返信草案・新規メール草案を確認・編集・送信する。

## 13.2 表示項目

- draft_type
- 宛先
- Cc
- Bcc
- 件名
- 本文
- 元メール
- 関連Case
- LLM生成履歴
- 追加プロンプト
- 最終編集日時

API:

```http
GET /drafts
GET /drafts/{draft_id}
```

## 13.3 必須操作

- 編集
- 保存
- 追加プロンプト付き再生成
- 破棄
- Gmail送信
- 元メールを開く
- Caseを開く

API:

```http
PATCH /drafts/{draft_id}
POST /drafts/{draft_id}/regenerate
DELETE /drafts/{draft_id}
POST /drafts/{draft_id}/send
```

## 13.4 Gmail送信

送信前に確認ダイアログを表示する。

送信APIは直接Gmail送信しない。

```text
external_operations に gmail_send を作成する。
```

`unknown` になった場合は自動再送しない。

---

# 16. File一覧画面

## 14.1 目的

Caseに関連するファイル、アップロードファイル、Gmail添付、生成物、外部リンクを確認する。

## 14.2 表示項目

- ファイル名
- Origin
- Case
- 添付元メール
- アップロード日時
- サイズ
- MIME type
- LLM Policy
- trashed状態
- version

API:

```http
GET /files
```

## 14.3 フィルタ

- Case
- Origin
- LLM Policy
- trashed
- ファイル種別
- 最近追加
- 添付由来
- Generated

## 14.4 必須操作

- 詳細表示
- ダウンロード
- プレビュー
- LLM要約
- LLM Policy変更
- ゴミ箱へ移動
- 復元
- 物理削除
- Caseを開く
- 添付元メールを開く

API:

```http
GET /files/{file_id}
POST /files/{file_id}/summarize
PATCH /files/{file_id}/llm-policy
POST /files/{file_id}/trash
POST /files/{file_id}/restore
DELETE /files/{file_id}
```

物理削除は確認ダイアログ必須。

---

# 17. File詳細画面

## 15.1 表示項目

- ファイル名
- 物理保存ID
- Origin
- Case
- 添付元メール
- version一覧
- LLM Policy
- 要約
- メタ情報
- ダウンロード履歴
- LLM投入履歴

## 15.2 必須操作

- プレビュー
- ダウンロード
- 要約生成
- LLM Policy変更
- ゴミ箱へ移動
- 復元
- 物理削除
- Caseを開く
- 元メールを開く

## 15.3 監査ログ

- ファイルカード表示
- プレビュー
- ダウンロード
- LLM投入
- 物理削除

---

# 18. LLM実行履歴画面

## 16.1 目的

LLM実行履歴、失敗、コスト、プロンプト改善材料を確認する。

## 16.2 表示項目

- function_type
- model_name
- provider_name
- prompt_version_id
- input_hash
- input_source_json
- input_diagnostic_json
- output_json
- status
- error_type
- retry_count
- token数
- 推定コスト
- 作成日時

API:

```http
GET /llm-runs
GET /llm-runs/{llm_run_id}
```

## 16.3 必須操作

- 詳細確認
- output_json表示
- 関連メールを開く
- 関連Caseを開く
- 関連Contact候補を開く
- 再実行
- prompt_version確認

注意:

- LLM入力全文は保存しない。
- プロンプト改善に必要な診断情報を保存する。

---

# 19. Audit Log画面

## 17.1 目的

ユーザーがどの情報に接触した可能性があるかを追跡する。

## 17.2 表示項目

- 日時
- session_id
- action_type
- target_type
- target_id
- Case
- Contact
- Mail
- File
- 端末情報
- IP
- User-Agent

API:

```http
GET /audit-logs
GET /audit-exposure-batches
```

## 17.3 フィルタ

- 日時範囲
- action_type
- target_type
- Case
- Contact
- Mail
- File
- LLM機能
- エラーのみ
- 端末
- セッション

## 17.4 必須操作

- ログ詳細確認
- exposure batchの展開
- 対象メールを開く
- 対象Caseを開く
- 対象ファイルを開く

---

# 20. Settings画面

## 18.1 目的

アプリ全体の設定を管理する。

## 18.2 設定項目

- LLM provider
- LLM model
- LLM cost limit
- Gmail同期設定
- Calendar設定
- Worker数
- rate limit
- セッション設定
- 表示設定
- 通知設定
- メール重要度ルール
- Case候補ルール
- prompt version管理

## 18.3 必須操作

- 設定変更
- ルール追加
- ルール編集
- ルール並び替え
- ルール無効化
- prompt version確認

API:

```http
GET /settings
PATCH /settings
GET /mail-importance-rules
POST /mail-importance-rules
PATCH /mail-importance-rules/{rule_id}
GET /case-candidate-rules
POST /case-candidate-rules
PATCH /case-candidate-rules/{rule_id}
```

## 18.4 注意

From単独Skipルールは作成不可。  
FromだけでSkipしたい場合はContact skippedを使う。

---

# 21. Maintenance画面

## 19.1 目的

システムメンテナンス系の操作、異常確認、復旧支援を行う。

## 19.2 表示項目

- System Maintenance Case
- stale jobs
- failed jobs
- unknown external operations
- LLM Cost Limit警告
- 証明書期限
- バックアップ状態
- 復旧テスト状態
- Worker稼働状態
- Queue長
- DB Writer状態
- Audit Log Writer状態

API:

```http
GET /maintenance/summary
GET /jobs
GET /external-operations
GET /client-certificates
GET /backups
```

## 19.3 必須操作

- Graceful Shutdown
- stale job確認
- job手動再実行
- failed job確認
- unknown external operation手動解決
- 証明書発行
- 証明書失効
- バックアップ実行
- 復旧テスト記録
- Worker状態確認

API:

```http
POST /maintenance/graceful-shutdown
POST /jobs/{job_id}/retry
POST /external-operations/{operation_id}/resolve
POST /client-certificates
POST /client-certificates/{certificate_id}/revoke
POST /backups/run
POST /backups/{backup_id}/restore
```

## 19.4 確認ダイアログ

以下は確認必須。

- Graceful Shutdown
- external operation unknown解決
- 証明書失効
- バックアップ復元
- 物理削除
- Worker停止

---

# 22. Login画面

## 20.1 目的

mTLS後のアプリ内パスワード認証を行う。

## 20.2 表示項目

- アプリ名
- 端末名
- 証明書状態
- パスワード入力欄
- ログイン失敗回数
- ロック状態

## 20.3 認証仕様

- パスワード形式
- 試行回数制限: 5回
- 5回失敗でロック
- ロック解除はサーバー物理アクセスによる保守操作
- ログインから24時間後に自動ログアウト
- セッション延長なし

API:

```http
POST /auth/login
POST /auth/logout
GET /auth/session
```

---

# 23. 証明書管理画面

## 21.1 目的

端末ごとのクライアント証明書を管理する。

## 21.2 表示項目

- certificate_id
- 端末名
- fingerprint
- 発行日
- 有効期限
- status
- 最終利用日時
- User-Agent
- IP

API:

```http
GET /client-certificates
```

## 21.3 必須操作

- 証明書発行
- 証明書失効
- 端末名変更
- 更新タスク生成
- 利用履歴確認

API:

```http
POST /client-certificates
PATCH /client-certificates/{certificate_id}
POST /client-certificates/{certificate_id}/revoke
POST /client-certificates/{certificate_id}/create-renewal-task
```

証明書失効時は関連セッションを無効化する。

---

# 24. バックアップ画面

## 22.1 目的

バックアップ・復旧・復旧テストを管理する。

実装優先度は高くないが、設計上は重要機能として画面を定義する。

## 22.2 表示項目

- 最新バックアップ日時
- バックアップ種別
- 成功/失敗
- 保存先メディア
- 暗号化状態
- サイズ
- 復旧テスト日時
- 復旧テスト結果

API:

```http
GET /backups
```

## 22.3 必須操作

- 手動バックアップ実行
- バックアップ履歴確認
- 復旧テスト記録
- 復元
- 保存先メディア情報登録

API:

```http
POST /backups/run
POST /backups/{backup_id}/restore
POST /backups/{backup_id}/test-result
POST /backup-media
```

復元は確認ダイアログ必須。

---

# 25. 画面別API対応表

## 23.1 Top

```text
GET /calendar/today
GET /mails/summary
GET /mails
GET /tasks
GET /contacts/unresolved-from-addresses
GET /maintenance/summary
```

## 23.2 Mail

```text
GET /mails
GET /mails/by-loaded-date
GET /mails/search
GET /mails/{message_id}
GET /mails/{message_id}/thread
POST /mails/{message_id}/importance
POST /mails/{message_id}/process
POST /mails/{message_id}/create-task
POST /mails/{message_id}/generate-reply-draft
POST /cases/{case_id}/mails
```

## 23.3 Case

```text
GET /cases
GET /cases/{case_id}
GET /cases/{case_id}/mails
GET /cases/{case_id}/tasks
POST /cases
PATCH /cases/{case_id}
POST /cases/{case_id}/close
POST /cases/{case_id}/archive
```

## 23.4 Task

```text
GET /tasks
GET /tasks/{task_id}
POST /tasks
PATCH /tasks/{task_id}
POST /tasks/{task_id}/complete
POST /tasks/{task_id}/cancel
DELETE /tasks/{task_id}
```

## 23.5 Contact

```text
GET /contacts
GET /contacts/{contact_id}
GET /contacts/unresolved-from-addresses
POST /contacts
PATCH /contacts/{contact_id}
POST /contacts/{contact_id}/skip
POST /contacts/{contact_id}/email-addresses
POST /contacts/unresolved-from-addresses/{encoded_email}/generate-prefill
```

## 23.6 Maintenance

```text
GET /maintenance/summary
GET /jobs
GET /external-operations
POST /jobs/{job_id}/retry
POST /external-operations/{operation_id}/resolve
POST /maintenance/graceful-shutdown
```

---

# 26. 実装優先度

本プロジェクトではMVPという用語は使わない。  
ただし、実装順序上の優先度は定義する。

## Priority A: 最初に必要

- Login
- Top
- Mail一覧
- Mail詳細
- Pending Contact処理
- 新規メール作成
- Draft編集
- Case一覧
- Case詳細
- Task一覧
- Task詳細
- Contact一覧
- Contact詳細
- Maintenance最小画面

## Priority B: 次に必要

- Calendar画面
- Draft画面
- File一覧
- File詳細
- LLM実行履歴
- Audit Log
- Settings

## Priority C: 後続

- バックアップ画面
- 証明書管理詳細
- 高度なCalendar配置
- 引継ぎログ生成画面
- ポモドーロタイマー
- Google Tasksエクスポート
- 高度なファイル検索
- 案件内RAG

---

# 27. 未確定事項

以下は実装しながら調整する。

- 具体的なレイアウト
- カード密度
- 色
- ボタン配置
- iPhoneでの省略表示
- iPadでの2カラム/3カラム切り替え
- Case詳細のタブ構成
- メールスレッド表示形式
- Calendar画面の週表示
- File preview対応範囲
- LLM実行履歴の詳細表示粒度

ただし、各画面に定義された必須操作は欠落させない。

---

# 28. 最重要確認事項

実装時に迷った場合は、以下を優先する。

```text
1. 未処理メールを見逃さない。
2. Pending Contactを解消しやすくする。
3. Caseがメール・Task・予定・人物・ファイルを持つ画面にする。
4. Task化・予定化・返信・処理済み化を少ない操作で行えるようにする。
5. ユーザー操作を待たせず、optimistic_stateで即時反映する。
6. 外部副作用は確認可能にし、unknownは自動再実行しない。
7. Contact未登録FromはPendingにする。
8. Email Address単独Skipは作らない。
9. Case削除は作らない。
10. Task削除は論理削除にする。
```
