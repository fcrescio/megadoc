import uuid

from starlette.middleware.base import BaseHTTPMiddleware

from common.logging import request_id_context


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        token = request_id_context.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_context.reset(token)
        response.headers["x-request-id"] = request_id
        return response

