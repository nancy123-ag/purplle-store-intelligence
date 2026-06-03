from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError


def structured_error(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        }
    }
    return JSONResponse(status_code=status_code, content=body)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) else {"detail": exc.detail}
    code = detail.get("code", "HTTP_ERROR")
    message = detail.get("message", str(exc.detail))
    return structured_error(exc.status_code, code, message, detail)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return structured_error(
        422,
        "VALIDATION_ERROR",
        "Request validation failed.",
        {"errors": exc.errors()},
    )


async def database_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    return structured_error(
        503,
        "DATABASE_UNAVAILABLE",
        "The analytics database is unavailable.",
        {"trace_id": getattr(request.state, "trace_id", None)},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return structured_error(
        500,
        "INTERNAL_ERROR",
        "An unexpected server error occurred.",
        {"trace_id": getattr(request.state, "trace_id", None)},
    )

