# CaseClosed 状態遷移設計書

Version: 0.1  
作成日: 2026-05-22  
対象: 個人用案件管理Webアプリ CaseClosed

---

## 0. 本書の位置づけ

本書は、CaseClosed に登場する主要エンティティの状態、状態遷移、遷移条件、禁止遷移、関連する副作用を定義する。

本書は以下の設計書を前提とする。

- CaseClosed 概要設計書
- CaseClosed 詳細設計書
- CaseClosed DB設計書
- CaseClosed API設計書
- CaseClosed Worker / Job / External Operation設計書
- CaseClosed 画面仕様書

本書の目的は、実装時に状態の解釈が分岐することを避けることである。

---

# 1. 状態設計の基本原則

## 1.1 状態は用途ごとに分離する

CaseClosedでは、単一の状態値にすべての意味を詰め込まない。

例:

- Caseの進行状態
- Caseのアーカイブ状態
- Caseのボール所在
- Taskの実行状態
- Mailの処理状態
- Mailの重要度
- Contactの状態
- Jobの実行状態
- External Operationの副作用状態

これらは別々の状態軸として管理する。

## 1.2 完了・除外・非表示を混同しない

以下は別概念である。

```text
Case Closed:
  案件として終結した。

Archived:
  通常運用画面から外した。

Task Completed:
  作業が完了した。

Task Canceled:
  不要と判断して閉じた。

Task Deleted:
  誤作成・ノイズとして論理削除した。

Mail Processed:
  対応済みになった。

Mail Skip:
  通常処理対象外になった。
```

## 1.3 ユーザー操作を自動処理で上書きしない

状態遷移において、ユーザー確定値はLLM/Systemによって上書きされない。

例:

- user_importance がある場合、llm_importanceで上書きしない。
- ユーザーがCaseに入れたメールを、LLM Case判定で別Caseへ勝手に移動しない。
- ユーザーがTaskをCompletedにした後、自動処理でNot Startedへ戻さない。

## 1.4 外部副作用は状態遷移と分離する

Gmail送信、Gmailスター付与、Google Calendar予定作成などは、内部状態変更と外部副作用を分けて管理する。

外部副作用は `external_operations` で状態管理する。

---

# 2. Case状態

## 2.1 状態軸

Caseは以下の状態軸を持つ。

```text
progress_status:
  not_started
  in_progress
  closed

ball_status:
  none
  user
  other
  date_wait
  stalled

archive state:
  active    = archived_at IS NULL
  archived  = archived_at IS NOT NULL
```

## 2.2 progress_status

### not_started

まだ実質的に作業が始まっていない状態。

典型例:

- Caseだけ先に作った
- メールやTaskはあるが、ユーザーがまだ動いていない
- 年次作業の開始前

### in_progress

作業中の状態。

典型例:

- 未完了Taskがある
- 関連メールが処理中
- 相手待ち・日付待ち・自分側作業が残っている

### closed

案件として完了・終結した状態。

DB上は以下で表現する。

```text
progress_status = closed
closed_at IS NOT NULL
```

## 2.3 Case Closed条件

Caseは、未完了Taskが残っている場合はClosed不可。

Closed可能な条件:

```text
Caseに属する全Taskが以下のいずれか:
  completed
  canceled
  deleted_at IS NOT NULL
```

ただし、`deleted_at IS NOT NULL` のTaskは通常タスク集合から除外されるため、Closed判定では未完了とは扱わない。

Closed不可なTask状態:

```text
not_started
in_progress
```

## 2.4 Case状態遷移

```text
not_started -> in_progress
not_started -> closed
in_progress -> closed
closed -> in_progress
```

### not_started -> in_progress

発火条件:

- Taskが作成される
- 関連メールが追加される
- ユーザーが手動で進行中にする
- Recurring Taskが生成される

### in_progress -> closed

発火条件:

- ユーザーがClosed操作を行う
- 未完了Taskが存在しない
- 確認ダイアログで承認する

副作用:

- closed_at設定
- case_eventsにclosed記録
- 必要に応じて引継ぎログ生成候補を表示

### closed -> in_progress

発火条件:

- ユーザーがReopenする
- Closed後に新規対応が必要になった

副作用:

- closed_atをNULLに戻す
- case_eventsにreopened記録

## 2.5 禁止遷移

```text
closed -> not_started
archived system case
delete case
```

Case削除は提供しない。

## 2.6 Archive状態

Archiveはprogress_statusとは別軸である。

```text
active:
  archived_at IS NULL

archived:
  archived_at IS NOT NULL
```

### Archive可能条件

通常CaseはArchive可能。  
Closed済みであることを推奨するが、必須にはしない。

### Archive禁止

以下はArchive不可。

- Inbox
- システムメンテナンス

## 2.7 ball_status

```text
none:
  ボール所在なし、または判定不要

user:
  ユーザー側に対応がある

other:
  相手側の返答・確認待ち

date_wait:
  日付・会議当日・締切到来待ち

stalled:
  停滞、要確認
```

ball_statusはCaseの見せ方に使う。  
Closed条件そのものではない。

## 2.8 Case期限状態

Case本体には原則として期限を持たせない。

期限はTaskに持たせる。  
Case画面では、Case内Taskの期限から以下を計算表示する。

```text
期限なし
期限あり
期限接近
期限超過
```

DBに保存する必須状態ではなく、Repository層またはView層で計算してよい。

---

# 3. Task状態

## 3.1 状態

```text
not_started
in_progress
completed
canceled
```

加えて、削除状態を以下で表現する。

```text
deleted_at IS NULL:
  通常Task

deleted_at IS NOT NULL:
  論理削除Task
```

## 3.2 状態の意味

### not_started

未着手。

### in_progress

作業中。

### completed

ユーザーが実行し終えた状態。

### canceled

一度は考慮したが不要になった状態。  
履歴として意味がある。

### deleted

誤作成・ノイズとして非表示にする状態。  
DB上は `deleted_at` による論理削除。

## 3.3 Task状態遷移

```text
not_started -> in_progress
not_started -> completed
not_started -> canceled
not_started -> deleted

in_progress -> completed
in_progress -> canceled
in_progress -> deleted

completed -> in_progress
completed -> deleted

canceled -> not_started
canceled -> deleted

deleted -> restored
```

`restored` は独立状態ではなく、`deleted_at = NULL` に戻す操作を指す。

## 3.4 Completed条件

子Taskを持つ親Taskは、未完了の下位Taskが残っている場合Completed不可。

Completed可能な下位Task状態:

```text
completed
canceled
deleted_at IS NOT NULL
```

Completed不可:

```text
not_started
in_progress
```

## 3.5 Canceledの扱い

CanceledはClosed条件上、閉じた状態として扱う。  
ただし、作業完了とは区別する。

用途:

- 依頼が不要になった
- 予定が消えた
- 他者対応で済んだ
- 実施しないことを決定した

## 3.6 Deletedの扱い

Deletedは論理削除であり、通常画面から非表示にする。

用途:

- 誤作成
- 重複作成
- ノイズ
- 復活不要に近いが、履歴参照のためDBには残す

物理削除は原則提供しない。  
保守画面でも慎重に扱う。

## 3.7 Task作成時の初期状態

原則:

```text
not_started
```

ただし、ユーザーが明示的に作業中として作る場合:

```text
in_progress
```

LLM候補は正式Taskではない。  
ユーザー採用時にTaskとして作成される。

---

# 4. Mail処理状態

## 4.1 状態軸

Mailは以下の状態軸を持つ。

```text
processed_status:
  unprocessed
  processed

importance:
  Pinned
  High
  Middle
  Low
  Skip
  Pending

Case membership:
  Caseが関連メール集合として持つ

Gmail external signal:
  initial_is_starred
  external_importance
```

## 4.2 processed_status

### unprocessed

まだ対応完了していないメール。

### processed

何らかの形で対応済みになったメール。

## 4.3 processedになる操作

以下の操作でprocessedになる。

```text
返信送信
Task化
予定化
手動で処理済みにする
不要として処理済みにする
```

メールからTask作成した場合、原則としてprocessedになる。

## 4.4 processedにならない操作

以下だけではprocessedにならない。

```text
要約を読む
本文を開く
返信草案を作る
Caseに追加する
別Caseへコピーする
新規Caseを作る
Contact確認
添付情報を見る
```

## 4.5 processed状態遷移

```text
unprocessed -> processed
processed -> unprocessed
```

### unprocessed -> processed

発火条件:

- 返信送信成功
- Task作成
- Calendar予定作成
- ユーザーが処理済み操作
- ユーザーが不要として処理済み操作

### processed -> unprocessed

発火条件:

- ユーザーが未処理に戻す
- 誤って処理済みにした場合

## 4.6 Skipとの関係

Skipはprocessedとは別軸である。

```text
Skip:
  通常処理対象外

Processed:
  対応済み
```

Skipメールは通常未処理一覧から除外するが、Processedとはみなさない。

Skipタブで確認可能にする。

---

# 5. Mail重要度状態

## 5.1 重要度ラベル

```text
Pinned
High
Middle
Low
Skip
Pending
```

## 5.2 各ラベルの意味

### Pinned

特殊枠・ピン留め。  
Gmailスターとは無関係。

付与可能:

- ユーザー
- 重要度フィルタ

LLMはPinnedを出力できない。

Case候補抽出・Case判定対象外。

### High

高優先度。  
自動要約・Case判定対象。

Highになった場合、Gmailスター付与External Operationを作成する。

### Middle

通常処理対象。  
自動要約・Case判定対象。

### Low

低優先度。  
LLM重要度判定の出力ラベルとして使用可能。  
自動要約なし。  
自動Case判定なし。

### Skip

通常処理対象外。  
LLM出力不可。  
Processedとは別扱い。

### Pending

Contact未登録Fromにより判定保留。  
重要度判定・Case判定・自動要約を停止する。

## 5.3 effective_importance計算優先順位

```text
user_importance
> Contact skipped
> rule_importance
> external_importance
> llm_importance
> Pending
```

補足:

- Contact未登録Fromの場合、原則Pendingになる。
- Gmail読み込み時点でスターが付いていた場合、external_importance = High 相当。
- Gmail側で後からスター解除されても、アプリ側では下げない。
- PinnedはGmailスターと無関係。

## 5.4 重要度状態遷移

### Pending -> High/Middle/Low/Skip

発火条件:

- Contact登録
- 既存Contactへのメールアドレス追加
- Contact skipped登録

副作用:

- Contact skippedならSkip
- active Contactなら重要度判定Job発火
- High/Middleなら要約・Case判定Job発火

### Low -> High/Middle

発火条件:

- ユーザーが重要度変更
- ルール変更後の再判定

副作用:

- Case判定Job発火
- 自動要約Job発火
- HighならGmailスターExternal Operation作成

### High/Middle -> Low

発火条件:

- ユーザーが重要度変更

副作用:

- 自動Case判定は以後行わない
- 既存Case関連メール集合からは自動では除外しない

### 任意 -> Pinned

発火条件:

- ユーザーがPinned設定
- ルールによりPinned

副作用:

- 通常のCase判定対象から除外
- Gmailスターは操作しない

### 任意 -> Skip

発火条件:

- Contact skipped
- 複合条件Skipルール
- ユーザー操作

副作用:

- 通常未処理一覧から除外
- processedにはしない

## 5.5 From単独Skip禁止

Email Address単独Skipという概念は存在しない。

Fromだけを理由にSkipしたい場合は、Contactを作成し、そのContactを `skipped` にする。

重要度フィルタでFrom単独Skipは作成不可。

---

# 6. Pending Contact状態

## 6.1 対象

Pending判定の対象はFromのみ。

以下に該当するFromはPendingになる。

```text
Contact未登録From
no-reply
メーリングリスト
事務通知アドレス
広告送信者
```

ただし、すでにContact登録済みまたはContact skippedであればPendingにならない。

## 6.2 Pending中に停止する処理

```text
重要度判定
Case判定
自動要約
High/Middle添付のCase連動取得
```

## 6.3 Pending中でも許可する処理

```text
Contact登録画面LLM自動Fill
メール本文表示
Gmailで開く
Contact手動作成
Contact skipped作成
既存Contactへのメールアドレス追加
```

## 6.4 Pending解除

Pending解除条件:

- 新規Contact作成
- 既存ContactにFromメールアドレス追加
- Contact skippedとして作成

解除後:

```text
active Contact:
  重要度判定Job発火

skipped Contact:
  effective_importance = Skip
```

---

# 7. Case関連メール集合状態

## 7.1 基本方針

CaseClosedでは、メールがCaseに従属するというより、Caseが関連メール集合を持つ。

DB上は `case_mail_links` で表現する。

## 7.2 link_role

```text
primary
copy
```

### primary

自動判定またはユーザー操作により、そのメールの主要Caseとして扱う。

原則:

```text
1メールにつきprimary Caseは最大1つ
```

### copy

ユーザー操作により、同じメールを別Caseにも表示する。

用途:

- 出張と学会の両方に関係するメール
- 委員会と学生対応の両方に関係するメール
- 後で参照したい関連メール

## 7.3 状態遷移

```text
no_case -> primary
primary -> another primary
primary -> copy追加
copy -> removed
primary -> removed
```

## 7.4 自動判定

自動Case判定は1メール1primaryのみ作成する。

LLM/Systemは、ユーザーが設定したprimaryを上書きしてはならない。

## 7.5 Inbox

`inbox_required` の場合、Inbox Caseの関連メール集合へprimaryとして追加する。

`no_case_needed` の場合、Case関連メール集合には追加しない。

メールからTaskを作る場合、Case未定ならInbox配下Taskとする。

---

# 8. Contact状態

## 8.1 status

```text
active
skipped
archived
```

## 8.2 kind

```text
person
mailing_list
```

`mailing_list` は人物ではなく、メーリングリスト・ニュース配信・システム通知などの特殊Contactである。

通常Contact一覧、通常Contact用カスタムタブ、通常Contact向け詳細、LLMメモ/Context更新の対象には混ぜない。Mailing List専用タブと専用詳細で扱う。

Mailing List Contactは1 Contact = 1メールアドレスとし、Contact tagsは持たない。宛先置き換え条件は `mailing_list_recipient_expression` として保存する。memoと関連Caseは持てるが、LLMによるmemo/Context自動更新の対象にはしない。

Mailing List Contactのメールアドレスは常にActive/Primaryであり、Remove/Deactivate/Set Primary操作を持たない。

## 8.3 sender_resolution_mode

```text
self
reply_to
```

- `self`: FromのContact自体を送信者として扱う。
- `reply_to`: Fromが `mailing_list` Contactの場合に `Reply-To` を実送信者候補として扱う。

`person` は `self` のみ許可する。`mailing_list` は `self` / `reply_to` を選択できる。

## 8.4 active

通常のContact。

用途:

- 宛先補完
- Case候補判定
- LLM文脈
- 関連人物表示

## 8.5 skipped

そのContactからのメールを通常処理対象外にする。

用途:

- 広告送信者
- ニュースレター
- no-reply
- ML
- システム通知

ただし、個別メールに対するユーザー明示重要度変更は優先する。

## 8.6 archived

通常表示から外すContact。

過去メール・過去Caseとの関係は保持する。

## 8.7 Contact状態遷移

```text
active -> skipped
active -> archived
skipped -> active
skipped -> archived
archived -> active
```

Contact本体削除は、紐づく全メールアドレスが物理削除可能な場合のみ許可する。履歴ありメールアドレスが1件でもある場合は削除不可。

## 8.8 Email Address状態

Email Address単位のSkip状態は存在しない。

状態は以下に限定する。

```text
unresolved
linked
```

### unresolved

Contact未登録のメールアドレス。

### linked

Contactに紐づいたメールアドレス。

## 8.9 禁止事項

```text
skipped_address状態を作らない
Email Address単独Skipを作らない
From単独Skipルールを作らない
```

---

# 9. Draft状態

## 9.1 状態

```text
draft
sent
discarded
failed
```

## 9.2 draft

編集中・保存中の草案。

返信草案・新規メール草案の両方を含む。

```text
draft_type:
  reply
  new_mail
```

## 9.3 sent

Gmail送信External Operationが成功した草案。

## 9.4 discarded

ユーザーが破棄した草案。

## 9.5 failed

送信または生成に失敗した草案。  
ただし、Gmail送信の不明状態はDraftではなくExternal Operation側の `unknown` で扱う。

## 9.6 状態遷移

```text
draft -> sent
draft -> discarded
draft -> failed
failed -> draft
discarded -> draft
```

## 9.7 送信時の扱い

`POST /drafts/{draft_id}/send` は直接Gmail送信しない。

以下を作成する。

```text
external_operations.operation_type = gmail_send
```

送信成功後にDraftをsentにする。

---

# 10. File状態

## 10.1 状態軸

```text
storage state:
  active
  trashed
  purged

llm_policy:
  allowed
  confirm_required
  forbidden
```

## 10.2 storage state

### active

通常利用可能。

### trashed

ゴミ箱状態。  
通常画面からは非表示またはゴミ箱表示。

### purged

物理削除済み。  
DBメタ情報は残す。

## 10.3 File状態遷移

```text
active -> trashed
trashed -> active
trashed -> purged
```

## 10.4 物理削除

物理削除は確認ダイアログ必須。

物理削除後もDBメタ情報は残す。

## 10.5 LLM Policy

```text
allowed:
  LLM本文投入可

confirm_required:
  LLM投入前に確認必須

forbidden:
  LLM本文投入不可
```

## 10.6 LLM Policy遷移

```text
allowed -> confirm_required
allowed -> forbidden
confirm_required -> allowed
confirm_required -> forbidden
forbidden -> confirm_required
forbidden -> allowed
```

`forbidden` からの変更は確認ダイアログ必須。

---

# 11. Calendar Event Link状態

## 11.1 基本方針

予定の正本はGoogle Calendar。

CaseClosed側は、Google Calendar event IDとCase/Task/Mailとの関係を保持する。

## 11.2 状態

```text
linked
unlinked
external_deleted
unknown
```

## 11.3 状態遷移

```text
linked -> unlinked
linked -> external_deleted
linked -> unknown
unknown -> linked
unknown -> external_deleted
```

## 11.4 注意

Google Calendar予定を削除することと、CaseClosed上のリンクを外すことは別操作である。

---

# 12. Follow-up Watch状態

## 12.1 状態

```text
active
fulfilled
reminder_task_created
closed
```

## 12.2 active

返信待ち監視中。

## 12.3 fulfilled

同一Gmail threadに相手から返信が来た。

## 12.4 reminder_task_created

期限超過により、リマインドTaskが作成された。

## 12.5 closed

ユーザーが手動解除、またはリマインド対応完了により閉じた。

## 12.6 状態遷移

```text
active -> fulfilled
active -> reminder_task_created
active -> closed
reminder_task_created -> closed
fulfilled -> closed
```

## 12.7 作成条件

Follow-up Watchはすべての送信メールに自動作成しない。

作成条件:

- ユーザーが「返信を待つ」を明示
- LLMが候補提示し、ユーザーが承認

---

# 13. Job状態

## 13.1 状態

```text
pending
running
succeeded
failed
canceled
stale
```

## 13.2 pending

実行待ち。

## 13.3 running

Workerが実行中。

## 13.4 succeeded

正常終了。

## 13.5 failed

リトライ上限到達、または致命的エラー。

## 13.6 canceled

ユーザーまたはシステムによりキャンセル。

## 13.7 stale

サーバーダウン等によりrunningのまま残ったJob。

MVPという用語は使わないが、初期実装ではstale jobを自動再実行しない。  
保守画面で確認し、必要なら手動再実行する。

## 13.8 状態遷移

```text
pending -> running
pending -> canceled
running -> succeeded
running -> failed
running -> stale
failed -> pending
stale -> pending
stale -> canceled
```

## 13.9 リトライ方針

通常失敗:

```text
retry_count < max_retry_count:
  pendingへ戻す

retry_count >= max_retry_count:
  failed
```

JSON不正などLLM構造エラーは、プロンプトを補正してリトライする。

## 13.10 stale検出

Orchestrator起動時または定期チェックで、一定時間以上runningのJobをstaleにする。

stale化した場合:

- システムメンテナンスCaseにTask作成
- Maintenance画面に表示
- 自動再実行しない

---

# 14. Write Request状態

## 14.1 状態

```text
pending
applied
discarded
failed
canceled
```

## 14.2 pending

Single DB Writerによる反映待ち。

## 14.3 applied

DB反映済み。

## 14.4 discarded

base_version競合やユーザー値保護により破棄。

## 14.5 failed

DB制約違反などで反映失敗。

## 14.6 canceled

明示的にキャンセル。

## 14.7 状態遷移

```text
pending -> applied
pending -> discarded
pending -> failed
pending -> canceled
failed -> pending
```

## 14.8 競合時

base_version競合時:

- user source同士なら後勝ちにしない
- UIに競合を表示
- 再読込または手動マージを促す

LLM/System sourceがuser_*を更新しようとした場合:

```text
discarded
```

---

# 15. External Operation状態

## 15.1 状態

```text
pending
running
succeeded
failed
unknown
canceled
manual_resolution_required
```

## 15.2 pending

外部副作用実行待ち。

## 15.3 running

実行中。

## 15.4 succeeded

外部副作用が成功し、外部ID等を保存できた状態。

## 15.5 failed

外部副作用が発生していないことが明確な失敗。

再実行可能な場合がある。

## 15.6 unknown

外部副作用が起きたか不明。

例:

- Gmail送信中に通信断
- Calendar作成中にタイムアウト
- Gmailスター付与中に応答不明

この状態では自動再実行禁止。

## 15.7 manual_resolution_required

unknown等に対して、人間の確認が必要な状態。

## 15.8 canceled

実行前にキャンセルされた状態。

## 15.9 状態遷移

```text
pending -> running
pending -> canceled
running -> succeeded
running -> failed
running -> unknown
failed -> pending
unknown -> manual_resolution_required
manual_resolution_required -> succeeded
manual_resolution_required -> failed
manual_resolution_required -> canceled
```

## 15.10 unknown時の副作用

unknownになった場合:

- 自動再実行しない
- システムメンテナンスCaseに確認Taskを作成
- Maintenance画面に表示
- ユーザーがGmail/Calendar側を確認して手動解決する

## 15.11 冪等性

External Operationには必ず以下を持つ。

```text
operation_type
idempotency_key
request_payload_hash
external_id
attempt_count
```

---

# 16. LLM Run状態

## 16.1 状態

```text
pending
running
succeeded
failed
canceled
```

## 16.2 succeeded

LLM出力が構文的に処理可能だった状態。

人間が見て微妙な内容でも、JSON schemaを満たし、必須フィールドがあり、enum違反がなければsucceededとする。

## 16.3 failed

以下の場合にfailedとする。

- JSON不正がリトライ上限後も解消しない
- 必須フィールド欠落が解消しない
- enum違反が解消しない
- provider errorが解消しない
- cost limitにより実行不可

## 16.4 状態遷移

```text
pending -> running
running -> succeeded
running -> failed
running -> canceled
failed -> pending
```

## 16.5 人間が見て微妙な出力

以下はfailed扱いしない。

- 要約の表現が微妙
- 返信草案が好みと違う
- Case判定が微妙
- Contact候補が曖昧

ユーザーが編集・修正できる前提で表示する。

## 16.6 Cost Limit

Cost Limit超過または超過見込みの場合:

- LLM Runはfailedまたはskipped相当として扱う
- システムメンテナンスCaseにTaskを作成する
- 自動処理は必要に応じて停止する

---

# 17. Session状態

## 17.1 状態

```text
active
expired
logged_out
revoked
locked
```

## 17.2 active

ログイン済み。

有効期間:

```text
ログインから24時間
```

延長なし。

## 17.3 expired

24時間経過により自動失効。

## 17.4 logged_out

ユーザーがログアウト。

## 17.5 revoked

証明書失効等によりセッション無効化。

## 17.6 locked

パスワード失敗5回によるロック。

解除はサーバー物理アクセスによる保守操作。

## 17.7 状態遷移

```text
active -> expired
active -> logged_out
active -> revoked
active -> locked
locked -> active
```

`locked -> active` は保守操作後の再ログインによる。

---

# 18. Client Certificate状態

## 18.1 状態

```text
active
expiring_soon
expired
revoked
```

## 18.2 active

有効な証明書。

## 18.3 expiring_soon

期限7日前から。

副作用:

- システムメンテナンスCaseに証明書更新Taskを作成

## 18.4 expired

期限切れ。

## 18.5 revoked

保守画面から失効。

副作用:

- 関連セッションをrevokedにする

## 18.6 状態遷移

```text
active -> expiring_soon
expiring_soon -> expired
active -> revoked
expiring_soon -> revoked
expired -> revoked
```

---

# 19. Backup状態

## 19.1 状態

```text
not_configured
scheduled
running
succeeded
failed
restore_test_required
restore_test_succeeded
restore_test_failed
```

## 19.2 実装優先度

バックアップ・復旧は設計上重要だが、実装優先度は中核機能より下げる。

ただし、状態設計上の置き場所は確保する。

## 19.3 状態遷移

```text
not_configured -> scheduled
scheduled -> running
running -> succeeded
running -> failed
succeeded -> restore_test_required
restore_test_required -> restore_test_succeeded
restore_test_required -> restore_test_failed
failed -> scheduled
```

## 19.4 failed時

- システムメンテナンスCaseにTask作成
- Maintenance画面に表示

---

# 20. Recurring Task Template状態

## 20.1 状態

```text
active
paused
archived
```

## 20.2 active

定期生成対象。

## 20.3 paused

一時停止。

## 20.4 archived

通常利用停止。

## 20.5 状態遷移

```text
active -> paused
paused -> active
active -> archived
paused -> archived
archived -> active
```

## 20.6 重複生成防止

`generated_recurring_tasks.generated_for_period` により同一期間の重複生成を防ぐ。

---

# 21. 状態遷移と監査ログ

## 21.1 必ず監査ログに残す状態遷移

```text
Gmail送信
Google Calendar予定作成・変更
File LLM Policy変更
証明書発行・失効
バックアップ復元
物理削除
Case Closed
Case Archive
Task Completed
Task Canceled
Task Deleted
Mail Processed
Mail importance変更
Contact skipped化
External Operation unknown手動解決
```

## 21.2 Event Logに残す状態遷移

Case文脈に関係する以下はcase_eventsに残す。

```text
Case作成
Case Closed
Case Reopen
Case Archive
関連メール追加
Task作成
Task Completed
Task Canceled
予定作成
ファイル追加
Case Context更新
引継ぎログ生成
```

---

# 22. 状態遷移の実装優先度

## Priority A

- Case
- Task
- Mail processed
- Mail importance
- Pending Contact
- Contact
- Draft
- Job
- Write Request
- External Operation
- Session

## Priority B

- File
- Calendar Event Link
- LLM Run
- Client Certificate
- Follow-up Watch

## Priority C

- Backup
- Recurring Task Template
- Google Tasks Export
- Pomodoro Session

---

# 23. 未確定事項

以下は実装中に調整する。

- Case ball_statusの自動推定条件
- Case期限状態の表示閾値
- Task優先度の有無
- Mail processedを戻したときのCase/Task/Eventへの影響
- Contact archivedの表示範囲
- Draft failed状態の詳細
- File purged後のUI表現
- Follow-up Watchの自動解除条件の細部
- Backup復旧テストの詳細

---

# 24. 最重要ルール

実装時に迷った場合は、以下を優先する。

```text
1. CaseはClosedとArchiveを分ける。
2. Case削除は提供しない。
3. TaskはCompleted/Canceled/Deletedを分ける。
4. Task削除は論理削除。
5. Mail ProcessedとSkipを混同しない。
6. Pending Contact中は重要度判定・Case判定・自動要約を止める。
7. Contact未登録FromはPendingにする。
8. Email Address単独Skipは作らない。
9. Caseが関連メール集合を持つ。
10. External Operation unknownは自動再実行しない。
11. LLM出力の内容が微妙でも、構造が正しければ失敗扱いしない。
12. ユーザー確定値をLLM/Systemが上書きしない。
```
