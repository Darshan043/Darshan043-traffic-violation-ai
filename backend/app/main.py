"""FastAPI application main entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.core.config import settings
from backend.app.core.errors import register_error_handlers
from backend.app.core.logging_config import setup_logging
from backend.app.routers import (
    auth,
    cameras,
    health,
    settings as settings_router,
    stats,
    stream,
    users,
    violations,
    ws,
)

logger = setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Traffic AI Backend initialized with storage_dir=%s", settings.storage_path)
    yield
    logger.info("Traffic AI Backend shutting down")


app = FastAPI(
    title="Traffic AI Backend",
    version="1.0.0",
    description="Traffic violation detection and camera management backend",
    lifespan=lifespan,
)

# Uniform error handlers
register_error_handlers(app)

# CORS middleware
origins = [o.strip() for o in settings.CORS_ORIGIN.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(cameras.router)
app.include_router(stream.router)
app.include_router(violations.router)
app.include_router(stats.router)
app.include_router(settings_router.router)
app.include_router(ws.router)
