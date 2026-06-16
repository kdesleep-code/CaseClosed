# CaseClosed セキュリティ / 認証 / 運用保守設計書

Version: 0.1  
作成日: 2026-05-22  
対象: 個人用案件管理Webアプリ CaseClosed

---

## 0. 本書の位置づけ

本書は、CaseClosedにおけるセキュリティ、認証、アクセス制御、証明書管理、セッション管理、運用保守、バックアップ・復旧、障害対応の設計を定義する。

本書は以下の設計書を前提とする。

- CaseClosed 概要設計書
- CaseClosed 詳細設計書
- CaseClosed DB設計書
- CaseClosed API設計書
- CaseClosed Worker / Job / External Operation設計書
- CaseClosed 画面仕様書
- CaseClosed 状態遷移設計書
- CaseClosed LLM / Prompt設計書

本アプリは本人専用の個人用業務支援システムである。  
ただし、Gmail、Google Calendar、個人情報、学生情報、研究情報、医療・生体信号関連資料、契約・倫理審査関連資料を扱う可能性があるため、個人用であってもセキュリティは強めに設計する。

---

# 1. 基本方針

## 1.1 防御の基本構成

CaseClosedは、以下の多層防御を基本とする。

```text
Tailscaleによるネットワーク到達制限
+
リバースプロキシによるmTLS
+
アプリ内パスワード認証
+
24時間固定セッション
+
重要操作確認
+
厚めの監査ログ
```

## 1.2 インターネット直接公開禁止

CaseClosedはインターネットに直接公開しない。

アクセス経路は原則として以下に限定する。

```text
許可端末
  -> Tailscale
  -> 自宅Ubuntuサーバー
  -> リバースプロキシ
  -> CaseClosedアプリ
```

## 1.3 本人専用

本アプリは、当面は利用者本人のみが使う。

- 複数ユーザーアカウントは作らない。
- 権限ロール管理は作らない。
- 秘書・共同研究者用アカウントは想定しない。
- ただし、端末単位の証明書管理は行う。

## 1.4 重要操作は追加認証ではなく確認ダイアログ

日常操作のたびに再認証は求めない。  
ただし、危険操作には確認ダイアログを出す。

確認対象:

- Gmail送信
- Google Calendar予定作成・変更
- LLM利用禁止ファイルのポリシー変更
- 証明書失効
- バックアップ復元
- 物理削除
- External Operation unknownの手動解決
- Graceful Shutdown
- Worker停止
- 外部副作用を伴う操作

## 1.5 ユーザーを待たせない

認証・運用保守は強めに設計するが、通常のメール処理・Task処理を過度に妨げない。

---

# 2. 想定環境

## 2.1 Production

```text
Ubuntu server
Tailscale enabled
Reverse proxy: Caddy or Nginx
CaseClosed app process
SQLite DB
Local file storage
External HDD/SSD backup
```

## 2.2 Development

```text
Windows PC
VS Code
test DB
test storage
mock Gmail/Calendar
mock LLM
```

本番データをWindows開発環境に原則保持しない。

## 2.3 Staging

```text
Windows仮本番またはUbuntu上の別環境
制限付きGoogle API連携
test DB
test storage
```

Stagingでは本番Gmail送信・本番Google Calendar書き込みを原則行わない。

---

# 3. アクセス制御アーキテクチャ

## 3.1 推奨構成

```text
[Client Device]
    |
[Tailscale]
    |
[Reverse Proxy: Caddy/Nginx]
    |  mTLS verification
    |  X-Client-Cert-Fingerprint header
    |
[CaseClosed App]
    |  app password authentication
    |
[SQLite / Storage]
```

## 3.2 Tailscaleの役割

Tailscaleはネットワーク到達性を制限する。

役割:

- 公開インターネットから到達不能にする。
- 許可端末だけがサーバーに到達できるようにする。
- 大学・自宅・外出先から同じprivate networkとしてアクセス可能にする。

注意:

- Tailscaleだけを認証の全てにしない。
- Tailscale到達後もmTLSとアプリ内パスワードを要求する。

## 3.3 リバースプロキシの役割

リバースプロキシは以下を担当する。

- HTTPS終端
- mTLSクライアント証明書検証
- 証明書fingerprintをアプリへ渡す
- 不正証明書端末の遮断
- アクセスログ出力
- 必要に応じてsecurity header付与

推奨:

```text
Caddy または Nginx
```

## 3.4 アプリの役割

アプリは以下を担当する。

- mTLS検証済みfingerprintの受け取り
- `client_certificates` との照合
- アプリ内パスワード認証
- セッション発行・失効
- 試行回数制限
- 監査ログ
- 証明書管理画面
- 保守画面

---

# 4. mTLS / クライアント証明書

## 4.1 基本方針

クライアント証明書は端末ごとに発行する。

対象端末:

- Windows PC
- iPhone
- iPad
- その他許可端末

## 4.2 証明書検証位置

証明書検証は、アプリ本体ではなくリバースプロキシで行う。

理由:

- mTLS実装をWebフレームワークに依存させない。
- 証明書検証失敗リクエストをアプリまで到達させない。
- Caddy/Nginxの標準機能を使える。

## 4.3 アプリへの伝達

リバースプロキシは、検証済み証明書のfingerprintをアプリへ渡す。

例:

```http
X-Client-Cert-Fingerprint: SHA256:...
```

注意:

- このヘッダは外部から直接注入されないよう、アプリはリバースプロキシからの接続のみ受ける。
- アプリを直接外部公開しない。
- localhostまたはprivate socket経由を推奨する。

## 4.4 client_certificates テーブル

主要項目:

```text
certificate_id
device_name
fingerprint
subject
issued_at
expires_at
status
last_seen_at
last_seen_ip
last_seen_user_agent
created_at
updated_at
revoked_at
revoked_reason
```

status:

```text
active
expiring_soon
expired
revoked
```

## 4.5 証明書期限

有効期限:

```text
6か月
```

期限7日前に、システムメンテナンスCase配下へTaskを自動生成する。

Task例:

```text
クライアント証明書を更新する: iPhone
```

## 4.6 証明書発行

証明書発行は保守画面から行う。

手順:

1. 端末名を入力する。
2. 証明書を発行する。
3. 証明書・秘密鍵・インストール手順を表示またはダウンロードする。
4. `client_certificates` に登録する。
5. 監査ログに記録する。

注意:

- 証明書秘密鍵の保存方法は慎重に扱う。
- 可能であれば、秘密鍵は発行時のみダウンロード可能にする。
- サーバー側に秘密鍵を長期保存しない方針が望ましい。

## 4.7 証明書失効

証明書失効は確認ダイアログ必須。

失効時:

- `client_certificates.status = revoked`
- `revoked_at` 設定
- 関連セッションを `revoked` にする
- システムログ・監査ログへ記録

## 4.8 iPhone / iPad

iPhone / iPadも証明書認証対象とする。

注意:

- 証明書インストール手順を保守画面にメモとして表示できるようにする。
- iOS側の証明書有効期限切れに注意する。
- 証明書更新Taskを必ず生成する。

---

# 5. アプリ内パスワード認証

## 5.1 基本方針

mTLSを通過した端末でも、アプリ内パスワード認証を要求する。

PINではなくパスワード形式とする。

## 5.2 パスワード保存

パスワードは平文保存しない。

保存方式:

```text
password_hash
password_salt
password_hash_algorithm
```

推奨:

```text
Argon2id
```

実装都合で難しければbcrypt等を検討する。

## 5.3 ログイン試行回数制限

ログイン失敗は端末証明書単位または全体でカウントする。

制限:

```text
5回失敗でロック
```

ロック後:

- Web UIから解除しない。
- サーバーに物理アクセスして解除する。
- Maintenance用CLIまたはローカル管理コマンドで解除する。

## 5.4 ロック解除

ロック解除は、サーバー物理アクセス前提とする。

例:

```bash
caseclosed-admin unlock-login
```

またはSQLiteを直接編集する保守手順を用意する。

解除操作はsystem_logsに残す。

## 5.5 セッション発行

ログイン成功後、セッションを発行する。

セッション有効期間:

```text
ログインから24時間
```

延長なし。  
アクティビティがあっても24時間で自動ログアウトする。

## 5.6 セッションCookie

Cookie方針:

```text
HttpOnly
Secure
SameSite=Lax or Strict
```

Tailscale + 個人用途であっても、最低限のCookie保護を行う。

## 5.7 CSRF対策

POST/PATCH/DELETE等の状態変更APIにはCSRF対策を入れる。

候補:

- CSRF token
- SameSite Cookie
- custom header
- double submit cookie

実装方式はフレームワークに合わせて決定する。

---

# 6. Session管理

## 6.1 sessions テーブル

主要項目:

```text
session_id
certificate_id
status
created_at
expires_at
last_seen_at
logged_out_at
revoked_at
ip_address
user_agent
device_name
failed_login_count_snapshot
```

status:

```text
active
expired
logged_out
revoked
locked
```

## 6.2 セッション失効条件

- 24時間経過
- ユーザーログアウト
- 証明書失効
- ロック発生
- 保守画面から明示失効
- サーバー側セッション削除

## 6.3 セッション表示

保守画面または認証管理画面に表示する。

表示項目:

- 端末名
- certificate_id
- ログイン時刻
- 有効期限
- 最終アクセス
- IP
- User-Agent
- status

## 6.4 監査ログ

ログイン・ログアウト・タイムアウト・ロック・証明書失効によるセッション無効化は監査ログ対象とする。

---

# 7. 権限モデル

## 7.1 単一ユーザーモデル

ユーザーは1人のみ。

そのため、一般的なRBACは作らない。

## 7.2 操作制御

権限ではなく、以下で制御する。

- 認証済みセッションか
- 有効な証明書か
- 操作が確認ダイアログ対象か
- 対象FileのLLM Policy
- External Operationの状態
- System Caseかどうか

## 7.3 System Case保護

以下のSystem Caseは削除不可・Archive不可。

- Inbox
- システムメンテナンス

Closedも原則不可または非推奨とする。

## 7.4 Case削除

Case削除は通常の業務導線としては提供しない。完了したCaseはClosed後にArchiveする。

ただし、誤作成や運用上のノイズとして未完了のまま消したいCaseに限り、目立たない確認付き導線から削除できるようにしてよい。

制約:

- System Caseは削除不可。
- 通常の完了操作から削除へ誘導しない。
- 削除操作は確認必須。
- 関連Taskは論理削除とし、監査ログや操作履歴は削除しない。

## 7.5 Task削除

Task削除は論理削除のみ。

物理削除は原則提供しない。

---

# 8. 監査ログ

## 8.1 目的

監査ログは、ユーザーがどの情報に接触した可能性があるかを追跡するために記録する。

内部デバッグログとは別である。

## 8.2 記録対象

必須:

- ログイン
- ログアウト
- セッション失効
- メール一覧表示
- メール本文表示
- Gmail送信
- Task作成
- Task Completed
- Task Canceled
- Case Closed
- Case Archive
- Case関連メール追加/解除
- Fileカード表示
- Fileプレビュー
- Fileダウンロード
- File LLM投入
- File LLM Policy変更
- Contact作成
- Contact skipped化
- 証明書発行
- 証明書失効
- Backup実行
- Restore実行
- External Operation unknown手動解決
- 設定変更
- LLM追加指示変更
- Prompt Version変更

## 8.3 メール一覧表示ログ

メール一覧に表示されたメールIDは、exposure batchとして記録する。

対象:

- 日別メール一覧
- 未処理メール一覧
- 検索結果一覧
- 対応済みメール一覧
- Skip一覧
- Case詳細内の関連メール一覧

## 8.4 Audit Log Writer

監査ログはAudit Log Writerに分離する。

理由:

- メール一覧表示など高頻度ログでSingle DB Writerを詰まらせないため
- 業務DB更新と監査ログINSERTを分離するため

## 8.5 保存内容

代表項目:

```text
audit_log_id
session_id
certificate_id
action_type
target_type
target_id
case_id
contact_id
mail_message_id
file_id
metadata_json
created_at
ip_address
user_agent
```

## 8.6 保存しないもの

監査ログには以下を保存しない。

- メール本文全文
- ファイル本文全文
- LLM入力全文

---

# 9. System Log / Event Log

## 9.1 System Log

システム内部の動作・エラー・保守イベントを記録する。

例:

- Worker起動/停止
- Job失敗
- stale job検出
- External Operation unknown
- DB migration
- Backup失敗
- LLM Cost Limit到達
- Gmail API error
- Calendar API error

## 9.2 Event Log

Caseの文脈として意味のあるイベントを記録する。

例:

- Case作成
- 関連メール追加
- Task作成
- Task Completed
- 予定作成
- ファイル追加
- Case Context更新
- 引継ぎログ生成

## 9.3 使い分け

```text
Audit Log:
  ユーザーが何に接触したか

System Log:
  システムがどう動いたか

Event Log:
  Caseの文脈として何が起きたか
```

---

# 10. 外部API資格情報管理

## 10.1 対象

- Gmail API OAuth token
- Google Calendar API OAuth token
- Google Tasks API token
- LLM provider API key
- Tailscale設定
- mTLS CA / server certificate
- client certificate

## 10.2 保存場所

原則として `.env` に直接ベタ書きしすぎない。

推奨:

```text
config/secrets/
OS file permissionで保護
必要に応じて暗号化
```

## 10.3 ファイル権限

Productionでは、secretsをアプリ実行ユーザーのみ読めるようにする。

例:

```bash
chmod 600
chown caseclosed:caseclosed
```

## 10.4 token更新

Google API tokenの期限切れや更新失敗は、システムメンテナンスCaseにTaskを作成する。

例:

```text
Google OAuth tokenの更新に失敗したため再認証する
```

## 10.5 API keyのログ出力禁止

ログ・監査ログ・LLM入力診断情報にAPI keyやtokenを含めない。

---

# 11. 外部副作用の安全管理

## 11.1 対象

- Gmail送信
- Gmailスター付与
- Google Calendar予定作成
- Google Calendar予定変更
- Google Tasksエクスポート
- 将来の外部連携

## 11.2 external_operations

外部副作用はすべて `external_operations` を通す。

直接API handlerから外部APIを呼ばない。

## 11.3 unknown状態

外部API実行中に通信断・timeout等で結果不明の場合、`unknown` にする。

unknownでは自動再実行しない。

理由:

- Gmail二重送信防止
- Calendar予定二重作成防止
- Google Tasks重複作成防止

## 11.4 手動解決

unknown発生時:

1. システムメンテナンスCaseに確認Taskを作成する。
2. Maintenance画面に表示する。
3. ユーザーがGmail/Calendar等を確認する。
4. succeeded / failed / canceled として手動解決する。

## 11.5 冪等性

external_operationsには以下を持つ。

```text
operation_type
idempotency_key
request_payload_hash
external_id
attempt_count
```

同一idempotency_keyのoperationを二重作成しない。

---

# 12. LLM利用安全管理

## 12.1 LLM入力

LLM入力全文はllm_runsに保存しない。

保存:

- input_hash
- input_source_json
- input_diagnostic_json

保存禁止:

- API key
- OAuth token
- パスワード
- 証明書秘密鍵
- メール本文の重複保存
- ファイル本文の重複保存

## 12.2 File LLM Policy

ファイル本文投入は `llm_policy` に従う。

```text
allowed:
  LLM投入可

confirm_required:
  確認後に投入可

forbidden:
  投入不可
```

`forbidden` からの変更は確認ダイアログ必須。

## 12.3 高機密情報

以下は原則として自動LLM投入しない。

- 個人情報を含む可能性が高い資料
- 医療・生体信号関連資料
- 倫理審査関連資料
- 契約関連資料
- 未公開論文
- 学生評価情報

## 12.4 Cost Limit

LLM Cost Limit超過または超過見込みでは、System Maintenance CaseにTaskを作成する。

自動LLM処理は必要に応じて停止する。

---

# 13. バックアップ設計

## 13.1 基本方針

ファイル正本をアプリ内ローカルストレージに置くため、バックアップは重要である。

ただし、実装優先度は中核機能より下げる。

## 13.2 バックアップ対象

- SQLite DB
- storage objects
- generated files
- trash
- config
- secrets metadata
- client certificate metadata
- audit logs
- system logs
- case events
- prompt_versions
- llm_instruction_rules
- Case Context
- Contact Context

注意:

- 証明書秘密鍵やAPI tokenのバックアップ方針は慎重に定める。
- バックアップに含める場合は暗号化必須。

## 13.3 バックアップ先

原則:

```text
外付けHDD/SSD
```

クラウドバックアップは原則利用しない。

## 13.4 暗号化

バックアップは暗号化して保存する。

具体方式は実装時に決めるが、以下を満たすこと。

- 復元可能である
- パスフレーズまたは鍵を安全に保管する
- バックアップメディア紛失時に内容を読まれない

## 13.5 頻度

設計上の標準:

```text
週1回の増分バックアップ
四半期に1回のフルバックアップ
```

実装優先度が低い間は、手動バックアップでもよい。

## 13.6 世代管理

容量が許す限り過去バックアップは削除しない。

外付けHDD/SSDが満杯に近づいた場合:

- 新しいメディアへ交換
- メディア管理情報を記録
- どのバックアップがどのメディアにあるか記録

## 13.7 backup_media

メディア管理情報を保持する。

項目例:

```text
media_id
label
type
capacity
location_memo
first_used_at
last_used_at
status
memo
```

## 13.8 backups

バックアップ履歴を保持する。

項目例:

```text
backup_id
backup_type
started_at
finished_at
status
media_id
path
encrypted
size_bytes
checksum
error_message
restore_test_status
restore_tested_at
memo
```

## 13.9 バックアップ失敗

失敗時:

- system_logsに記録
- システムメンテナンスCaseにTask作成
- Maintenance画面に表示

---

# 14. 復旧設計

## 14.1 基本方針

バックアップは取得するだけではなく、復元可能であることを確認する。

## 14.2 復元対象

任意のバックアップ日時を選んで復元できるようにする。

ただし、外部副作用との整合性に注意する。

## 14.3 復元前確認

復元は確認ダイアログ必須。

確認内容:

- 復元対象日時
- 現在DBが上書きされること
- 外部API連携を一時停止すること
- external_operationsの状態を確認すること
- 復元後にGmail送信等を自動再実行しないこと

## 14.4 復元手順

標準手順:

1. 新規Job受付停止
2. Worker停止
3. External Operation Worker停止
4. Single DB Writer停止
5. Audit Log Writer停止
6. 現在状態の緊急バックアップ取得
7. 指定バックアップを展開
8. DB・storageを復元
9. external_operationsのrunningをmanual_resolution_requiredへ変更
10. jobsのrunningをstaleへ変更
11. 起動
12. Maintenance画面で確認

## 14.5 復旧テスト

四半期に1回程度、復旧テストTaskを作成する。

実装優先度が低い期間でも、手動で復旧テスト記録を残せるようにする。

## 14.6 復元後の外部副作用

復元後、以下は自動再実行しない。

- Gmail送信
- Google Calendar予定作成
- Gmailスター付与
- Google Tasksエクスポート

必要ならユーザーが手動で確認・解決する。

---

# 15. 運用保守Case

## 15.1 System Maintenance Case

初期データとして以下の特殊Caseを作成する。

```text
Case name: システムメンテナンス
system_case_type: system_maintenance
```

## 15.2 対象

システムメンテナンスCaseには以下のTaskを作成する。

- 証明書更新
- バックアップ確認
- 復旧テスト
- LLM Cost Limit確認
- stale job確認
- unknown external operation確認
- Google OAuth token再認証
- Worker異常確認
- DB migration確認
- 外付けHDD/SSD交換

## 15.3 保護

System Maintenance Caseは削除不可・Archive不可。  
Closedも原則不可。

---

# 16. Maintenance画面

## 16.1 目的

運用保守・障害確認・復旧支援の入口。

## 16.2 表示項目

- システムメンテナンスCase
- failed jobs
- stale jobs
- unknown external operations
- Worker状態
- Queue長
- DB Writer状態
- Audit Log Writer状態
- LLM Cost Limit状態
- Google API token状態
- 証明書期限
- セッション一覧
- バックアップ状態
- 復旧テスト状態
- 最近のsystem_logs

## 16.3 必須操作

- Graceful Shutdown
- failed job確認
- stale job確認
- job手動再実行
- unknown external operation手動解決
- Worker状態確認
- 証明書発行
- 証明書失効
- セッション失効
- バックアップ実行
- 復元
- 復旧テスト記録
- LLM自動処理停止/再開
- Google token再認証導線

## 16.4 確認ダイアログ

以下は確認必須。

- Graceful Shutdown
- Worker停止
- 証明書失効
- セッション一括失効
- バックアップ復元
- unknown external operation手動解決
- LLM自動処理停止/再開
- 物理削除

---

# 17. Graceful Shutdown

## 17.1 目的

サーバー停止、アップデート、バックアップ、復元前に安全に処理を止める。

## 17.2 手順

1. 新規Job受付停止
2. 新規External Operation受付停止
3. 実行中Jobの完了待ち
4. 実行中External Operationの完了待ち
5. pending Write Request反映
6. Worker停止
7. External Operation Worker停止
8. Single DB Writer停止
9. Audit Log Writer停止
10. サービス停止可能状態へ

## 17.3 タイムアウト

一定時間内に完了しないJobは保守画面に表示する。

外部副作用中のoperationは慎重に扱う。  
強制停止で結果不明になる場合は `unknown` にする。

## 17.4 監査ログ

Graceful Shutdown開始・完了・失敗はsystem_logsに記録する。  
ユーザー操作として実行した場合はaudit_logsにも記録する。

---

# 18. Job / Worker運用

## 18.1 Worker種別

- Gmail Sync Worker
- LLM Worker
- Calendar Worker
- File Worker
- Context Update Worker
- Report / Handover Worker
- External Operation Worker
- Maintenance Worker

## 18.2 監視項目

- Worker生存状態
- running job数
- pending job数
- failed job数
- stale job数
- average runtime
- last heartbeat
- error rate

## 18.3 stale job

一定時間runningのまま更新されないJobはstaleとする。

stale時:

- 自動再実行しない
- System Maintenance Task作成
- Maintenance画面表示
- ユーザーが再実行またはキャンセル

## 18.4 failed job

failed jobは内容に応じて再実行可能。

JSON不正等のLLM構造エラーは自動リトライ後、上限到達でfailed。

## 18.5 Worker数

Worker数は設定可能。

設定項目:

```text
min_workers
max_workers
llm_worker_limit
external_operation_worker_limit
rate_limit
cost_limit
```

---

# 19. DB / Migration運用

## 19.1 migration必須

DB変更はmigrationとして管理する。

直接手編集は避ける。

## 19.2 migration前

実施前:

- Backup推奨
- Worker停止
- DB Writer停止
- migration内容確認

## 19.3 migration後

実施後:

- schema version記録
- system_logs記録
- smoke test
- Maintenance画面で状態確認

## 19.4 schema_versions

テーブル例:

```text
schema_version
applied_at
migration_name
checksum
status
error_message
```

---

# 20. ログ管理

## 20.1 ログ種別

- audit_logs
- system_logs
- case_events
- app process logs
- reverse proxy access logs
- reverse proxy error logs
- backup logs

## 20.2 ログ保存方針

監査ログは厚めに保存する。  
容量が増えたら圧縮・アーカイブする。

## 20.3 ログローテーション

app process logsとreverse proxy logsはログローテーションを行う。

## 20.4 ログに含めないもの

- パスワード
- API key
- OAuth token
- 証明書秘密鍵
- LLM入力全文
- ファイル本文全文

---

# 21. 通知・Task化方針

## 21.1 通知よりTaskを重視

CaseClosedでは、単なる通知よりも、システムメンテナンスCase配下のTask作成を重視する。

理由:

- 後で対応できる
- 対応漏れを防げる
- CaseClosed自身の運用履歴として残る

## 21.2 Task化対象

- 証明書期限7日前
- Backup失敗
- 復旧テスト期限
- LLM Cost Limit
- stale job
- unknown external operation
- Google token更新失敗
- Worker異常
- DB migration失敗

## 21.3 Top画面表示

重大なメンテナンスTaskはTop画面にも表示する。

---

# 22. 障害対応方針

## 22.1 Gmail送信unknown

対応:

1. Gmailを開いて送信済みを確認する。
2. 送信済みならexternal_operationをsucceededに手動解決する。
3. 未送信ならfailedまたはcanceledにする。
4. 必要なら再送信する。
5. Taskを完了する。

## 22.2 Calendar作成unknown

対応:

1. Google Calendarを確認する。
2. 予定が作成済みならexternal_idを登録しsucceededにする。
3. 未作成ならfailed/canceledにする。
4. 必要なら再作成する。

## 22.3 DB Writer停止

対応:

1. 新規Write Request受付を止める。
2. pending write_requestsを確認する。
3. system_logsを確認する。
4. 必要ならバックアップ取得。
5. DB Writer再起動。
6. failed write_requestsを確認する。

## 22.4 LLM Cost Limit

対応:

1. Maintenance画面でCost状況を確認。
2. 自動LLM処理を止めるか判断。
3. モデル変更・上限変更・一時停止を行う。
4. System Maintenance Taskを完了。

## 22.5 証明書期限切れ

対応:

1. 物理アクセスまたは既存有効端末から保守画面へ入る。
2. 新証明書を発行。
3. 端末へインストール。
4. 旧証明書を失効。
5. 更新Taskを完了。

## 22.6 ログインロック

対応:

1. サーバーへ物理アクセス。
2. 管理CLIでロック解除。
3. system_logs確認。
4. 必要なら証明書失効。

---

# 23. 実装優先度

本プロジェクトではMVPという用語は使わない。  
ただし、実装順序上の優先度を定義する。

## Priority A

最初に必要。

- Tailscale前提アクセス
- reverse proxy mTLS
- client_certificates
- app password login
- 5回失敗ロック
- 24時間セッション
- sessions
- audit_logs基本
- Maintenance最小画面
- System Maintenance Case
- unknown external operation表示
- stale job表示

## Priority B

次に必要。

- 証明書発行/失効画面
- 証明書期限Task生成
- Google token期限/失敗Task生成
- LLM Cost Limit Task生成
- Graceful Shutdown
- Backup履歴
- 手動Backup
- 復旧テスト記録
- schema_versions
- 詳細System Logs画面

## Priority C

後続。

- 自動増分バックアップ
- 四半期フルバックアップ
- 高度な復元UI
- backup media管理
- ログ圧縮・アーカイブ自動化
- Prometheus等の外部監視
- より高度な侵入検知
- PWAセキュリティ強化
- Google Tasks連携の詳細運用

---

# 24. 未確定事項

以下は実装時に決める。

- Caddy/Nginxのどちらを使うか
- mTLS証明書発行コマンド
- 証明書秘密鍵をサーバーに一時保存するか
- パスワードhash実装ライブラリ
- CSRF対策方式
- secrets暗号化方式
- バックアップ暗号化方式
- バックアップ自動化スクリプト
- 復旧手順の具体コマンド
- Google OAuth再認証フロー
- reverse proxy log保存期間
- audit log圧縮タイミング

---

# 25. 最重要ルール

```text
1. インターネットへ直接公開しない。
2. Tailscaleだけに依存せず、mTLSとアプリ内パスワードを併用する。
3. mTLS検証はリバースプロキシで行う。
4. アプリは証明書fingerprintをclient_certificatesと照合する。
5. パスワードは5回失敗でロックし、解除は物理アクセス前提。
6. セッションはログインから24時間で固定失効する。
7. Gmail送信・Calendar作成など外部副作用はexternal_operations経由。
8. unknown external operationは自動再実行しない。
9. Case削除は通常導線では提供しない。誤作成Case向けの目立たない確認付きDeleteのみ許可する。
10. Task削除は論理削除。
11. LLM入力全文・API key・token・秘密鍵をログに残さない。
12. ファイル本文のLLM投入はllm_policyに従う。
13. バックアップは暗号化する。
14. 復元時は外部副作用の自動再実行を止める。
15. 運用上の問題はシステムメンテナンスCaseにTask化する。
```
