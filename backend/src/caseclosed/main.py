from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import JSONResponse

from caseclosed.auth import router as auth_router
from caseclosed.contacts import router as contacts_router
from caseclosed.db.runtime import bootstrap_database
from caseclosed.db.runtime import rebuild_runtime_database
from caseclosed.external_operations import router as external_operations_router
from caseclosed.jobs import router as jobs_router
from caseclosed.mails import router as mails_router
from caseclosed.maintenance import router as maintenance_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    rebuild_runtime_database()
    bootstrap_database()
    yield


app = FastAPI(title="CaseClosed", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(contacts_router)
app.include_router(jobs_router)
app.include_router(external_operations_router)
app.include_router(maintenance_router)
app.include_router(mails_router)


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
