from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.database import Base, engine
from app.routers import (
    auth,
    records,
    attachments,
    chat,
    history,
    importexport,
    users,
    meta,
)
from app.routers.auth import limiter

app = FastAPI(title="DocuTrack Registry API", version="1.0.0")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    # For v1 we create tables on startup. Alembic migrations are also provided
    # (see backend/alembic) for controlled schema evolution in production.
    Base.metadata.create_all(bind=engine)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(meta.router)
app.include_router(records.router)
app.include_router(attachments.router)
app.include_router(importexport.router)
app.include_router(chat.router)
app.include_router(history.router)
