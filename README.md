# Case-Closed

## Local startup

This project uses a FastAPI backend and a Vite/React frontend.

### Backend

Run from the repository root:

```powershell
python -m uvicorn caseclosed.main:app --app-dir backend/src --env-file .env --host 127.0.0.1 --port 8000
```

Backend URL:

```text
http://127.0.0.1:8000
```

### Frontend

Run from the `frontend` directory:

```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

Frontend URL:

```text
http://127.0.0.1:5173
```

### HTTPS access from another device

For access from another PC on Tailscale, keep the backend bound to localhost and expose
the Vite frontend over HTTPS. Vite proxies `/api` to the local backend, so the
browser-to-CaseClosed connection is encrypted.

Generate a local development certificate. Include the Tailscale MagicDNS name and
Tailscale IP of the CaseClosed host:

```powershell
.\scripts\new-dev-https-cert.ps1 `
  -DnsName @("localhost", "desktop-r043eh2.tail913207.ts.net") `
  -IpAddress @("127.0.0.1", "::1", "100.85.42.30")
```

Then start the servers:

```powershell
python -m uvicorn caseclosed.main:app --app-dir backend/src --env-file .env --host 127.0.0.1 --port 8000
cd frontend
npm run dev -- --host 0.0.0.0 --port 8443
```

Or restart both dev servers with:

```powershell
.\restart-caseclosed-dev.windows.ps1
```

Open CaseClosed from the other PC by MagicDNS name:

```text
https://desktop-r043eh2.tail913207.ts.net:8443
```

When connecting Google from another PC, add the proxied callback URL to the
Google OAuth client's authorized redirect URIs:

```text
https://desktop-r043eh2.tail913207.ts.net:8443/api/v1/google/gmail/oauth/callback
```

The frontend passes its current origin to the backend when creating the Google
OAuth URL, so OAuth returns to the same HTTPS/Tailscale origin instead of
`127.0.0.1`.

The generated server certificate is signed by a CaseClosed local root CA. To remove
browser warnings on another Windows PC, copy `certs/caseclosed-local-root-ca.cer` to
that PC and import it into `Trusted Root Certification Authorities` for the current
user. After importing it, restart the browser and access CaseClosed by the MagicDNS
name above.

The backend reads local secrets from `.env`. Do not commit real API keys or OAuth secrets.

本Webアプリは、大学教員として日々発生する研究・教育・事務・委員会・出張・生活上の大型作業を、**案件:Case**単位で管理し、連絡漏れ・対応漏れ・期限超過・作業の滞留を防ぐことを目的とする。

最大の目標は以下である。

> 案件を遅滞なく、連絡漏れなく、スムーズに完了させる手助けをすること。

本アプリは、単なるメールソフト、タスク管理ツール、カレンダーアプリ、ファイル管理システムではなく、これらを**案件中心に統合する個人用業務支援システム**として位置づける。

## 開発開始

現在は設計書に従って Phase 0 の土台から実装している。初期構成は以下を前提とする。

- Backend: FastAPI
- Frontend: React
- DB: SQLite
- ORM: SQLAlchemy 2.x
- Migration: Alembic
- Test: pytest

Backend のローカル環境例:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e "backend[dev]"
pytest
```

開発用 API サーバー起動例:

```powershell
uvicorn caseclosed.main:app --app-dir backend/src --env-file .env --reload
```

Frontend のローカル環境例:

```powershell
cd frontend
npm install
npm run test
npm run dev
```

Phase 0 の疎通確認:

```text
GET /health
```

ローカル設定の雛形は `.env.example` に置く。本番 secret はリポジトリへ含めない。
