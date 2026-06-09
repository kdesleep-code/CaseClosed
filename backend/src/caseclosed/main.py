from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from caseclosed.auth import router as auth_router
from caseclosed.cases import router as cases_router
from caseclosed.contacts import router as contacts_router
from caseclosed.db.runtime import bootstrap_database
from caseclosed.db.runtime import rebuild_runtime_database
from caseclosed.external_operations import router as external_operations_router
from caseclosed.google_integration import router as google_integration_router
from caseclosed.jobs import router as jobs_router
from caseclosed.mail_drafts import bootstrap_mail_drafts_database
from caseclosed.mail_drafts import router as mail_drafts_router
from caseclosed.mails import router as mails_router
from caseclosed.maintenance import router as maintenance_router
from caseclosed.profile import router as profile_router
from caseclosed.services.background_worker import BackgroundWorkerSupervisor
from caseclosed.services.gmail_auto_import import GmailAutoImportSupervisor
from caseclosed.settings import is_background_worker_enabled
from caseclosed.storage import router as storage_router
from caseclosed.storage import storage_root
from caseclosed.tasks import router as tasks_router

FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    rebuild_runtime_database()
    bootstrap_database()
    bootstrap_mail_drafts_database()
    storage_root()
    background_worker = None
    gmail_auto_import = GmailAutoImportSupervisor()
    gmail_auto_import.start()
    if is_background_worker_enabled():
        background_worker = BackgroundWorkerSupervisor()
        background_worker.start()
    try:
        yield
    finally:
        if background_worker is not None:
            await background_worker.stop()
        await gmail_auto_import.stop()


app = FastAPI(title="CaseClosed", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(cases_router)
app.include_router(contacts_router)
app.include_router(jobs_router)
app.include_router(external_operations_router)
app.include_router(google_integration_router)
app.include_router(maintenance_router)
app.include_router(mail_drafts_router)
app.include_router(mails_router)
app.include_router(profile_router)
app.include_router(storage_router)
app.include_router(tasks_router)

if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.exception_handler(HTTPException)
def api_http_exception_handler(
    request: Request,
    exc: HTTPException,
) -> JSONResponse:
    if isinstance(exc.detail, dict) and "ok" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "ok": False,
            "error": {"code": "HTTP_ERROR", "message": str(exc.detail)},
        },
    )

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def frontend_root() -> FileResponse:
    return frontend_file_response("index.html")


@app.get("/{path:path}")
def frontend_fallback(path: str) -> FileResponse:
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")
    return frontend_file_response(path)


def frontend_file_response(path: str) -> FileResponse:
    requested_path = FRONTEND_DIST / path
    if (
        requested_path.is_file()
        and requested_path.resolve().is_relative_to(FRONTEND_DIST.resolve())
    ):
        return FileResponse(requested_path)
    index_path = FRONTEND_DIST / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Frontend build not found.")
