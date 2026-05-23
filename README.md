# Case-Closed

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
