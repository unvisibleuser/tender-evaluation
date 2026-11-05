"""FastAPI application factory."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import router
from app.container import Container, ThreadTaskRunner, build_container
from app.core.config import Settings, get_settings
from app.core.errors import DomainError
from app.core.logging import configure_logging

log = logging.getLogger(__name__)


def _error(
    status: int, code: str, message: str, request: Request, details: object | None = None
) -> JSONResponse:
    body: dict[str, object] = {
        "code": code,
        "message": message,
        "correlation_id": getattr(request.state, "correlation_id", None),
    }
    if details is not None:
        body["details"] = details
    return JSONResponse(status_code=status, content=body, headers={"cache-control": "no-store"})


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not hasattr(app.state, "container"):
            app.state.container = build_container(settings)
        yield
        tasks = app.state.container.tasks
        if isinstance(tasks, ThreadTaskRunner):
            tasks.shutdown()

    app = FastAPI(
        title="Tender Scrutiny & Evaluation Portal API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.environment != "production" else None,
        openapi_url="/api/openapi.json" if settings.environment != "production" else None,
    )
    if container is not None:
        app.state.container = container

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["authorization", "content-type", "idempotency-key"],
    )

    @app.middleware("http")
    async def correlation_and_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-correlation-id", "")
        request.state.correlation_id = (
            incoming if incoming.isalnum() and len(incoming) <= 64 else uuid.uuid4().hex
        )
        response = await call_next(request)
        response.headers["x-correlation-id"] = request.state.correlation_id
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["x-frame-options"] = "DENY"
        response.headers["referrer-policy"] = "no-referrer"
        if request.url.path.startswith("/api/v1") and "cache-control" not in response.headers:
            response.headers["cache-control"] = "no-store"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return _error(exc.status_code, exc.code, exc.message, request, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg", "")} for e in exc.errors()]
        return _error(422, "VALIDATION_FAILED", "Request validation failed", request, details)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error correlation_id=%s", getattr(request.state, "correlation_id", None))
        return _error(500, "INTERNAL_ERROR", "An internal error occurred", request)

    @app.get("/api/health", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings.environment}

    app.include_router(router)
    return app


def _default_app() -> FastAPI:
    configure_logging()
    return create_app()


app = _default_app()
