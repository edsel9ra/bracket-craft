"""CORS propio de la API pública v1 (spec 051, RF-008–RF-010).

Las lecturas del catálogo y su documento aceptan cualquier origen, solo GET y
sin credenciales. Los orígenes configurados del sitio y el resto de rutas pasan
intactos al CORS general de la aplicación.
"""

from collections.abc import Iterable

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.modules.public_api.catalog import is_public_read

SAFELISTED_REQUEST_HEADERS = frozenset({"accept", "accept-language", "content-language"})
MAX_AGE = "600"


def _with_vary_origin(headers: MutableHeaders) -> None:
    vary = [value.strip() for value in headers.get("vary", "").split(",") if value.strip()]
    if "origin" not in {value.lower() for value in vary}:
        vary.append("Origin")
    headers["Vary"] = ", ".join(vary)


class PublicReadCorsMiddleware:
    def __init__(self, app: ASGIApp, *, site_origins: Iterable[str]) -> None:
        self.app = app
        self.site_origins = frozenset(site_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_public_read(scope["method"], scope["path"]):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if origin is not None and origin in self.site_origins:
            await self.app(scope, receive, send)
            return
        if scope["method"] == "OPTIONS":
            if origin is None or "access-control-request-method" not in headers:
                await self.app(scope, receive, send)
                return
            await self._preflight(headers)(scope, receive, send)
            return

        async def send_open(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                del response_headers["access-control-allow-credentials"]
                response_headers["Access-Control-Allow-Origin"] = "*"
                _with_vary_origin(response_headers)
            await send(message)

        await self.app(scope, receive, send_open)

    @staticmethod
    def _preflight(headers: Headers) -> PlainTextResponse:
        method = headers["access-control-request-method"].strip().upper()
        requested = {
            value.strip().lower()
            for value in headers.get("access-control-request-headers", "").split(",")
            if value.strip()
        }
        if method != "GET":
            return PlainTextResponse("Disallowed CORS method", status_code=400, headers={"Vary": "Origin"})
        if not requested <= SAFELISTED_REQUEST_HEADERS:
            return PlainTextResponse("Disallowed CORS headers", status_code=400, headers={"Vary": "Origin"})
        return PlainTextResponse(
            None,
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET",
                "Access-Control-Max-Age": MAX_AGE,
                "Vary": "Origin",
            },
        )
