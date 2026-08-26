# C@seClosed

C@seClosedは、メール、コンタクト、タスク、カレンダー、ファイルを「案件（Case）」を中心にまとめる、個人向けの業務支援Webアプリケーションです。

単なるメールクライアントやタスク管理ツールではなく、研究、教育、事務、委員会、出張などの仕事について、連絡漏れ、期限超過、作業の滞留を減らすことを目的としています。

> 案件を遅滞なく、連絡漏れなく、スムーズに完了させる手助けをすること。

## 主な機能

- Caseを中心としたメール、Contact、Task、Calendar、Storageの関連付け
- Gmailの取り込み、検索、送信、時刻指定送信
- Google Calendarとの同期とイベント作成
- OpenAI APIを利用したメール要約、重要度判定、下書き、Task・Case・予定の入力補助
- Case完了時の引継ぎ資料作成とZIP出力
- Pomodoro Timer
- USB外付けデバイスへのバックアップと復元

## 現在の構成

| 区分 | 技術 |
| --- | --- |
| Backend | Python 3.12以上、FastAPI、SQLAlchemy 2.x |
| Frontend | React 19、TypeScript、Vite 8 |
| Database | SQLite |
| Migration | Alembic |
| Test | pytest、Vitest |

このリポジトリは現時点では個人運用を主眼にしています。付属の起動スクリプトは開発サーバーを起動するものであり、そのままインターネットへ公開する用途を想定していません。LANやTailscaleなど、信頼できるネットワーク内で利用してください。

## 最短セットアップ（Ubuntu）

### 1. 必要なソフトウェア

次を用意してください。

- Git
- Python 3.12以上
- Node.js `^20.19.0` または `>=22.12.0`（Vite 8の要件）
- npm
- curl、`ss`コマンドを含むiproute2

### 2. リポジトリと依存関係の準備

```bash
git clone <repository-url>
cd CaseClosed

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e "backend[dev]"

cd frontend
npm install
cd ..
```

### 3. ローカル設定の作成

```bash
cp .env.example .env
```

`.env`をUTF-8で開き、少なくとも次を自分の環境に合わせてください。

```dotenv
CASECLOSED_ENV=development
CASECLOSED_DATABASE_URL=sqlite:///./data/caseclosed.sqlite3
CASECLOSED_BOOTSTRAP_PASSWORD=十分に長い初回ログイン用パスワード
```

通常ログイン用パスワードは8文字以上にしてください。`.env`にはAPIキーやOAuthクライアントシークレットが入るため、Gitへ追加しないでください。`.env`は既定で`.gitignore`の対象です。

### 4. systemdサービスのインストールと起動

```bash
./deploy/systemd/install.sh --start
```

このインストーラーはBackendとFrontendのsystemd Unitを生成・インストールし、OS起動時の自動起動を有効にします。同時に、CaseClosedの2サービスだけをパスワードなしで再起動できる限定sudoers設定も導入します。既定URLは次のとおりです。

- Frontend: `https://127.0.0.1:8443/`
- Backend: `http://127.0.0.1:8000`
- Health check: `http://127.0.0.1:8000/health`

初回起動時に、SQLiteデータベース、Storageディレクトリ、初期設定などが自動作成されます。新規インストールでは、通常は手動で`alembic upgrade`を実行する必要はありません。

コードや`.env`の変更を反映する場合は、次のリポジトリ内スクリプトを使用します。

```bash
./scripts/restart-caseclosed-services.ubuntu.sh
```

状態とログは次のコマンドで確認できます。

```bash
systemctl status caseclosed-backend.service caseclosed-frontend.service
journalctl -u caseclosed-backend.service -u caseclosed-frontend.service
```

インストールせず、ローカル用Unitとsudoers設定の生成・検証だけを行う場合は`--generate-only`を使用できます。生成物はGit管理対象外の`deploy/systemd/generated/`に置かれます。

```bash
./deploy/systemd/install.sh --generate-only
```

## Windowsでのセットアップと起動

PowerShellでリポジトリのルートを開きます。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e "backend[dev]"

Set-Location frontend
npm install
Set-Location ..

Copy-Item .env.example .env
```

`.env`を設定した後、仮想環境を有効にしたPowerShellから起動します。

```powershell
.\restart-caseclosed-dev.windows.ps1
```

証明書がなければFrontendはHTTP、`certs/caseclosed-dev.pfx`があればHTTPSで起動します。HTTPを明示する場合は次を使います。

```powershell
.\restart-caseclosed-dev.windows.ps1 -NoHttps
```

## 初回ログイン

1. ブラウザでFrontendのURLを開きます。
2. `.env`の`CASECLOSED_BOOTSTRAP_PASSWORD`に設定したパスワードでログインします。
3. ログイン後、`Maintenance` → `セキュリティ`を開き、通常ログイン用パスワードを任意のパスワードへ変更します。
4. 必要であれば、同じ画面でLow / Skipメール確認用の「簡易ページ用パスワード」も設定します。

重要な点として、初回ログイン時にBootstrap PasswordのハッシュがSQLiteへ保存されます。それ以降の通常ログインではDB内のハッシュが使われるため、`.env`の`CASECLOSED_BOOTSTRAP_PASSWORD`を書き換えても既存パスワードは変わりません。以後の変更は`Maintenance` → `セキュリティ`から行ってください。

パスワードを忘れた場合、ログイン画面の「新しいパスワードをメール送信」から乱数パスワードを発行できます。ただし、この機能を使うには、後述のGmail連携がすでに完了しており、接続先Gmailアドレスへ送信できる状態である必要があります。再発行には10分間のクールダウンがあります。

## Gmail・Google Calendarとの連携

C@seClosedはGoogle OAuth 2.0を利用します。メールパスワードをC@seClosedへ保存する方式ではありません。

### 1. Google Cloud側の準備

[Google Cloud Console](https://console.cloud.google.com/)で、次を設定します。

1. 利用するGoogle Cloudプロジェクトを作成または選択します。
2. Gmail APIとGoogle Calendar APIを有効にします。
3. Google Auth PlatformでOAuth同意画面を設定します。
4. テスト運用の場合は、実際に接続するGoogleアカウントをTest usersへ追加します。
5. OAuth Client IDを「Web application」として作成します。
6. Authorized redirect URIsへ、実際にブラウザで開くC@seClosedのURLにコールバックパスを付けたURIを登録します。

コールバックパスは常に次です。

```text
/api/v1/google/gmail/oauth/callback
```

例:

```text
http://127.0.0.1:5173/api/v1/google/gmail/oauth/callback
http://127.0.0.1:8443/api/v1/google/gmail/oauth/callback
https://caseclosed-host.example.ts.net:8443/api/v1/google/gmail/oauth/callback
```

Settings画面から接続すると、現在ブラウザで開いているFrontendのoriginがコールバック先になります。スキーム、ホスト名、ポートのいずれかがGoogle Cloud側の登録と違うと、`redirect_uri_mismatch`になります。

GoogleのOAuthとGmailスコープについては、[Web server OAuthガイド](https://developers.google.com/workspace/gmail/api/auth/web-server)および[Gmail APIスコープ一覧](https://developers.google.com/workspace/gmail/api/auth/scopes)も参照してください。

### 2. `.env`へOAuth情報を設定

Google Cloud Consoleで発行した値を設定します。

```dotenv
CASECLOSED_GOOGLE_OAUTH_CLIENT_ID=your-client-id
CASECLOSED_GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret
CASECLOSED_GOOGLE_OAUTH_REDIRECT_URI=http://127.0.0.1:8000/api/v1/google/gmail/oauth/callback
CASECLOSED_GOOGLE_GMAIL_SCOPES=https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/calendar.events
```

`CASECLOSED_GOOGLE_OAUTH_REDIRECT_URI`は、Frontend originが渡されなかった場合のフォールバックです。通常のSettings画面からの接続では、前節で説明したFrontend側のコールバックURIもGoogle Cloudへ登録してください。

スコープを変更した場合は、一度Google接続を解除し、再接続して新しい権限を許可する必要があります。

### 3. 再起動して画面から接続

```bash
./scripts/restart-caseclosed-services.ubuntu.sh
```

Windowsでは`restart-caseclosed-dev.windows.ps1`を実行します。その後、次の順に操作します。

1. C@seClosedへ通常ログインします。
2. `Settings` → `Google`を開きます。
3. Google接続の状態が「接続準備完了」になっていることを確認します。
4. 「Googleへ接続」を押し、対象アカウントを選び、必要な権限を許可します。
5. C@seClosedへ戻ったら、接続状態と表示されているスコープを確認します。
6. 必要に応じてGmail自動取込の間隔・上限、Google Calendar自動同期の間隔・対象期間を設定します。

`gmail.readonly`はメール取込、`gmail.send`は送信、Calendarの2スコープは予定の読込・作成・更新に使われます。Gmailの読取スコープはGoogle上でRestricted scopeに分類されるため、第三者へ公開するOAuthアプリではGoogleの検証要件を別途確認してください。個人用のテスト運用では、OAuth同意画面のTest usersを正しく設定してください。

## OpenAI APIとの連携

OpenAI連携はBackendから[Responses API](https://platform.openai.com/docs/api-reference/responses)を呼び出します。APIキーがブラウザへ渡る構造ではありません。

### 1. APIキーを用意する

[OpenAI PlatformのAPI keyページ](https://platform.openai.com/api-keys)で、このインストール用のSecret API keyを作成します。キーは作成時に安全な場所へ保存してください。

OpenAIも、APIキーをクライアント側へ埋め込まず、環境変数としてBackendで管理し、リポジトリへコミットしないことを推奨しています。詳細は[API key safetyの公式ガイド](https://help.openai.com/en/articles/5112595-best-practices-for-api-key-safety)を参照してください。

### 2. `.env`へ設定する

```dotenv
CASECLOSED_OPENAI_API_KEY=your-secret-api-key
```

モデル割当は`backend/llm_model_profiles/`のプロファイルを使います。`.env.example`では機能ごとの初期プロファイル例を示しています。環境変数が未設定の機能はmock設定となるか、実OpenAI処理を利用できません。

### 3. 再起動して確認する

Backendは起動時の環境変数を使うため、設定後にBackendとFrontendを再起動します。

```bash
./scripts/restart-caseclosed-services.ubuntu.sh
```

ログイン後、`Settings` → `LLM`で、機能ごとのプロファイル、モデル、参照するAPIキー環境変数を確認・変更できます。APIキーそのものは画面へ表示されません。`Settings` → `予算`では、C@seClosedが記録した利用量に基づく概算コストと月額予算を確認できます。実際の請求額とは差があり得るため、OpenAI Platform側のUsage・Billingも併せて確認してください。

メールやファイルにはLLMへの送信を除外する設定があります。機密情報を含むデータを扱う場合は、LLM block設定と各データのLLM入力可否を確認してから利用してください。

## HTTPS・別端末からの利用

Viteは`certs/caseclosed-dev.pfx`がある場合、自動的にHTTPSを使います。Windowsではローカル開発証明書を生成できます。

```powershell
.\scripts\new-dev-https-cert.ps1 `
  -DnsName @("localhost", "caseclosed-host.example.ts.net") `
  -IpAddress @("127.0.0.1", "::1", "100.x.y.z")
```

別のWindows PCで証明書警告をなくすには、生成された`certs/caseclosed-local-root-ca.cer`をそのPCのCurrent Userの`Trusted Root Certification Authorities`へインポートし、ブラウザを再起動します。証明書と秘密鍵はGit管理対象外です。

Tailscale等からアクセスする場合も、Backendは`127.0.0.1:8000`のままにし、Frontendだけを`0.0.0.0:8443`で公開する構成を推奨します。Viteが`/api`をローカルBackendへプロキシします。

## データとバックアップ

既定では、主要データは次に保存されます。

| 内容 | 既定の場所 |
| --- | --- |
| メインDB | `data/caseclosed.sqlite3` |
| メール下書きDB | `data/caseclosed.drafts.sqlite3` |
| Storageの実ファイル | `data/storage/` |
| HTTPS証明書 | `certs/` |
| ローカルExtension | `extensions/user-extensions/` |

これらと`.env`には個人情報、メール本文、OAuth token、APIキーなどが含まれ得ます。Gitへコミットせず、バックアップも秘密情報として取り扱ってください。

USBバックアップは、ログイン後の`Maintenance` → `ストレージ`にある「暗号化USBバックアップ」から作成・復元できます。`.env`はUSBバックアップへ意図的に含まれないため、復元先では別途用意してください。既存環境の更新やDB操作を行う前にも、必ずバックアップを取得してください。

## 手動起動

起動スクリプトを使わない場合は、リポジトリのルートからBackendを起動します。

```bash
.venv/bin/python -m uvicorn caseclosed.main:app \
  --app-dir backend/src \
  --env-file .env \
  --host 127.0.0.1 \
  --port 8000
```

別のターミナルでFrontendを起動します。

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

## テストとビルド

```bash
# Backend全体
.venv/bin/python -m pytest backend/tests -q

# Frontend全体
cd frontend
npm run test

# Frontendの型検査と本番用ビルド
npm run build
```

大きな変更では全体テスト、軽微な変更では関連テストを先に実行してください。

## よくある問題

### Google接続ボタンが無効

`CASECLOSED_GOOGLE_OAUTH_CLIENT_ID`と`CASECLOSED_GOOGLE_OAUTH_CLIENT_SECRET`がBackendへ読み込まれていません。`.env`の変数名を確認し、再起動してください。

### `redirect_uri_mismatch`になる

ブラウザのアドレスバーに表示されているoriginに`/api/v1/google/gmail/oauth/callback`を付けたURIを、Google Cloud ConsoleのAuthorized redirect URIsへ完全一致で登録してください。HTTP/HTTPS、ホスト名、ポートも一致が必要です。

### Gmailは読めるが送信できない

OAuthスコープに`https://www.googleapis.com/auth/gmail.send`が含まれているか確認します。スコープを追加した後は、SettingsでGoogle接続を解除して再接続してください。

### Google Calendarを読めない・更新できない

`calendar.readonly`と`calendar.events`を確認し、Google Calendar APIが有効か確認してください。権限変更後は再接続します。

### OpenAI機能がmockになる、または認証エラーになる

`CASECLOSED_OPENAI_API_KEY`、`Settings` → `LLM`の機能別プロファイル、Backendログを確認し、設定後に再起動してください。キーをログやIssueへ貼り付けないでください。

### ログイン後すぐログイン画面へ戻る

`CASECLOSED_ENV=production`ではSecure Cookieが使われるため、HTTPではセッションCookieが保存・送信されません。HTTPSでアクセスするか、ローカル開発では`CASECLOSED_ENV=development`を使用してください。

### 起動ログを確認したい

Ubuntuでは`journalctl -u caseclosed-backend.service -u caseclosed-frontend.service`を実行します。Windowsでは`.tmp/dev-server-logs/`へ標準出力・標準エラーが保存されます。

## セキュリティ上の注意

- `.env`、`data/`、`certs/`を公開リポジトリへ追加しないでください。
- OpenAI APIキーをFrontendコードやブラウザのlocalStorageへ置かないでください。
- Google OAuth tokenはDBに保存されるため、DBとUSBバックアップを機密情報として扱ってください。
- 外部公開する場合は、開発用Viteサーバーではなく、TLS終端、アクセス制御、ログ管理を含む本番向け構成を別途用意してください。
- APIキーやOAuth secretを誤って公開した場合は、該当サービス側で直ちに無効化・再発行してください。

## 設計資料

詳細な設計は`blueprint/`以下にあります。主要な資料は次のとおりです。

- `blueprint/Overview_Design.md`
- `blueprint/Screen_Design.md`
- `blueprint/API_Design.md`
- `blueprint/DB_Design.md`
- `blueprint/Security_Auth_Ops_Design.md`
- `blueprint/Test_Strategy.md`
