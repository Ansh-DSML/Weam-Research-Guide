import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.logging_config import get_logger, request_id_var

logger = get_logger("app.request")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request_id, logs one structured line per request with method/path/status/duration."""

    async def dispatch(self, request: Request, call_next):
        rid = str(uuid.uuid4())
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.error(
                "request_failed",
                extra={"method": request.method, "path": request.url.path, "duration_ms": duration_ms},
                exc_info=True,
            )
            raise
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "request_completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        response.headers["X-Request-ID"] = rid
        request_id_var.reset(token)
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejects oversized request bodies with a clean 413 before they reach parsing —
    one huge pasted field can't take the API down."""

    def __init__(self, app, max_bytes: int):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    return JSONResponse(status_code=413, content={"detail": "request body too large"})
            except ValueError:
                pass
        return await call_next(request)
