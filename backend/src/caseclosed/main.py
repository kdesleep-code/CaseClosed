from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="CaseClosed")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

