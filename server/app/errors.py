"""Error envelope from api-spec.md: {"error": {"code", "message", "request_id"}}."""

import logging
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger("huda")

STATUS_CODES = {
    400: "VALIDATION_ERROR",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "VALIDATION_ERROR",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    503: "UPSTREAM_UNAVAILABLE",
}


class ApiError(Exception):
    def __init__(self, status: int, message: str, code: str | None = None):
        self.status = status
        self.code = code or STATUS_CODES.get(status, "INTERNAL")
        self.message = message


def not_found(what: str = "Resource") -> ApiError:
    return ApiError(404, f"{what} not found")


def _envelope(request: Request, status: int, code: str, message: str) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
        headers={"X-Request-ID": request_id or ""},
    )


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex[:12]
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return _envelope(request, exc.status, exc.code, exc.message)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return _envelope(request, exc.status_code, STATUS_CODES.get(exc.status_code, "INTERNAL"), str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        message = f"{loc}: {first.get('msg', 'invalid')}" if loc else first.get("msg", "invalid request")
        return _envelope(request, 422, "VALIDATION_ERROR", message)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error (request_id=%s)", getattr(request.state, "request_id", None))
        return _envelope(request, 500, "INTERNAL", "Internal server error")
