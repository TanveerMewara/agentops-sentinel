"""Response protections and value-free request validation diagnostics."""
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ExternalTraceBodyLimit:
    """Bound traces and evaluation datasets before JSON parsing, including chunks."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        dataset = (scope['type'] == 'http' and scope.get('method') == 'POST'
                   and scope.get('path') == '/v1/evaluations/datasets')
        otlp_path = scope.get('path', '') in ('/v1/traces', '/v1/metrics', '/v1/logs')
        trace_path = (otlp_path or
                      scope.get('path', '').endswith('/external-trace') or
                      scope.get('path', '').endswith('/external-trace/otlp') or
                      scope.get('path', '').endswith('/external-trace/otlp/finalize'))
        limited = dataset or (scope['type'] == 'http' and scope.get('method') == 'POST'
                              and trace_path)
        if not limited:
            return await self.app(scope, receive, send)
        size = 0
        limit = 524288 if dataset else (1048576 if otlp_path else 131072)
        chunks = []
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            size += len(chunk)
            if size > limit:
                return await JSONResponse(status_code=413, content={
                    'detail': ('Dataset request exceeds the 512 KiB transport limit.' if dataset else
                               ('OTLP request exceeds the 1 MiB compressed transport limit.' if otlp_path else
                                'External evidence request exceeds the 128 KiB transport limit.'))})(scope, receive, send)
            chunks.append(chunk)
            if not message.get('more_body', False):
                break
        body = b''.join(chunks)
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()

        await self.app(scope, bounded_receive, send)


async def validation_error_response(request, exception: RequestValidationError):
    # Input, validator messages, context and even arbitrary mapping keys may
    # contain contact data or credentials. Return only the transport location.
    detail = []
    for error in exception.errors():
        location = error.get("loc", ())
        root = location[0] if location and location[0] in ("body", "query", "path", "header", "cookie") else "request"
        detail.append({"loc": [root], "msg": "Request validation failed.", "type": "invalid_request"})
    return JSONResponse(status_code=422, content={"detail": detail})


class ResponseSecurity:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def protected_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                policies = {b"x-content-type-options": b"nosniff",
                            b"referrer-policy": b"no-referrer",
                            b"x-frame-options": b"DENY"}
                if scope.get("path", "").startswith("/v1/"):
                    policies[b"cache-control"] = b"no-store"
                headers = [(key, value) for key, value in headers if key.lower() not in policies]
                headers.extend(policies.items())
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, protected_send)
