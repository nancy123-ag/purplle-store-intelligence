from __future__ import annotations

import json
import logging
import re
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


logger = logging.getLogger("store_intelligence.requests")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        trace_id = request.headers.get("x-trace-id", str(uuid4()))
        request.state.trace_id = trace_id
        request.state.event_count = None

        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.exception(
                json.dumps(
                    self._payload(request, trace_id, latency_ms, status_code),
                    separators=(",", ":"),
                )
            )
            raise

        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["x-trace-id"] = trace_id
        logger.info(json.dumps(self._payload(request, trace_id, latency_ms, status_code), separators=(",", ":")))
        return response

    @staticmethod
    def _payload(request: Request, trace_id: str, latency_ms: float, status_code: int) -> dict:
        store_id = None
        match = re.search(r"/stores/([^/]+)", request.url.path)
        if match:
            store_id = match.group(1)

        return {
            "trace_id": trace_id,
            "store_id": store_id,
            "endpoint": request.url.path,
            "method": request.method,
            "latency_ms": latency_ms,
            "event_count": getattr(request.state, "event_count", None),
            "status_code": status_code,
        }

