"""The response envelope from contracts/openapi.yaml and the errors that map onto it."""

import logging
from datetime import datetime
from enum import StrEnum
from typing import Any

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.clock import to_iso

logger = logging.getLogger(__name__)


class ErrorCode(StrEnum):
    UNAUTHENTICATED = "unauthenticated"
    AGE_NOT_CONFIRMED = "age_not_confirmed"
    ON_BREAK = "on_break"
    DAILY_LIMIT_REACHED = "daily_limit_reached"
    RATE_LIMITED = "rate_limited"
    BUDGET_EXHAUSTED = "budget_exhausted"
    NOT_FOUND = "not_found"
    INVALID_INPUT = "invalid_input"
    INTERNAL = "internal"


INTERNAL_MESSAGE = "Something went wrong on our side. Please try again in a moment."
NOT_FOUND_MESSAGE = "We couldn't find that."
INVALID_INPUT_MESSAGE = "That request wasn't quite right. Please check it and try again."
UNAUTHENTICATED_MESSAGE = "Please sign in again."


class ApiError(Exception):
    def __init__(
        self, status: int, code: ErrorCode, message: str, retry_at: datetime | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retry_at = retry_at


def unauthenticated() -> ApiError:
    return ApiError(401, ErrorCode.UNAUTHENTICATED, UNAUTHENTICATED_MESSAGE)


def not_found(message: str = NOT_FOUND_MESSAGE) -> ApiError:
    return ApiError(404, ErrorCode.NOT_FOUND, message)


def internal() -> ApiError:
    return ApiError(500, ErrorCode.INTERNAL, INTERNAL_MESSAGE)


def ok(data: Any = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"success": True, "data": data, "error": None}
    if meta is not None:
        body["meta"] = meta
    return body


def error_payload(err: ApiError) -> dict[str, Any]:
    return {"code": err.code.value, "message": err.message, "retry_at": to_iso(err.retry_at)}


def error_response(err: ApiError) -> JSONResponse:
    body = {"success": False, "data": None, "error": error_payload(err)}
    return JSONResponse(status_code=err.status, content=body)


_STATUS_TO_ERROR = {
    401: unauthenticated,
    404: not_found,
}


async def _handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc)


async def _handle_validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
    # loc and type only: the errors also carry the submitted input (questions, tokens).
    logger.info("invalid input: %s", [(e["loc"], e["type"]) for e in exc.errors()])
    return error_response(ApiError(422, ErrorCode.INVALID_INPUT, INVALID_INPUT_MESSAGE))


async def _handle_http(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    make = _STATUS_TO_ERROR.get(exc.status_code)
    if make is not None:
        return error_response(make())
    if exc.status_code >= 500:
        return error_response(internal())
    return error_response(ApiError(exc.status_code, ErrorCode.INVALID_INPUT, INVALID_INPUT_MESSAGE))


class UnhandledErrorMiddleware:
    """Turns any uncaught exception into the internal-error envelope.

    Pure ASGI and added before CORSMiddleware, so CORS wraps it and a browser can read the 500.
    (A plain exception handler runs outside CORS, and the browser would see a network error.)
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def send_tracking(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, receive, send_tracking)
        except Exception as exc:
            logger.exception("unhandled error on %s %s", scope["method"], scope["path"])
            sentry_sdk.capture_exception(exc)
            if started:
                raise
            await error_response(internal())(scope, receive, send)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _handle_api_error)
    app.add_exception_handler(RequestValidationError, _handle_validation)
    app.add_exception_handler(StarletteHTTPException, _handle_http)
