"""In-process local HTTP+WebSocket router used on non-Windows platforms."""

import argparse
import asyncio
import logging
import re
import threading
from contextlib import asynccontextmanager

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus

_HOP_HEADERS = {
    b"connection",
    b"keep-alive",
    b"proxy-authenticate",
    b"proxy-authorization",
    b"te",
    b"trailer",
    b"transfer-encoding",
    b"upgrade",
}
_WS_HEADERS = {b"sec-websocket-key", b"sec-websocket-version", b"sec-websocket-extensions", b"sec-websocket-protocol"}
_ACAO = b"access-control-allow-origin"
_MODULE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _headers(raw_headers, *, request=False, websocket=False):
    excluded = set(_HOP_HEADERS)
    for name, value in raw_headers:
        if name.lower() == b"connection":
            excluded.update(part.strip().lower() for part in value.split(b","))
    if request:
        excluded.add(b"host")
    if websocket:
        excluded.update(_WS_HEADERS)
    return [(name, value) for name, value in raw_headers if name.lower() not in excluded]


def _with_acao(headers):
    headers = list(headers)
    if not any(name.lower() == _ACAO for name, _ in headers):
        headers.append((_ACAO, b"*"))
    return headers


def _preflight(request: Request):
    if request.method != "OPTIONS":
        return None
    if "origin" not in request.headers or "access-control-request-method" not in request.headers:
        return None
    requested = request.headers.get("access-control-request-headers", "")
    return Response(
        status_code=204,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": requested,
            "Access-Control-Max-Age": "86400",
        },
    )


def _ok():
    return Response("OK", media_type="text/plain", headers={"Access-Control-Allow-Origin": "*"})


def _bad_gateway():
    return JSONResponse(
        {"code": "502", "msg": "upstream unreachable"},
        status_code=502,
        headers={"Access-Control-Allow-Origin": "*"},
    )


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def create_app(http_protocol, ws_protocol, remote_host) -> Starlette:
    for name in ("httpx", "httpcore", "websockets.client"):
        logging.getLogger(name).setLevel(logging.WARNING)
    registry = {}
    lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(600, connect=10),
        ) as client:
            app.state.client = client
            yield

    def target(scope, *, websocket=False):
        path = scope.get("raw_path", scope["path"].encode()).decode("ascii")
        query = scope.get("query_string", b"").decode("ascii")
        suffix = "?" + query if query else ""
        first, _, remainder = path.lstrip("/").partition("/")
        with lock:
            port = registry.get(first)
        if port:
            local_path = "/" + remainder
            scheme = "ws" if websocket else "http"
            return f"{scheme}://127.0.0.1:{port}{local_path}{suffix}"
        scheme = ws_protocol if websocket else http_protocol
        return f"{scheme}://{remote_host}{path}{suffix}"

    async def health(request: Request):
        preflight = _preflight(request)
        if preflight is not None:
            return preflight
        return _ok()

    async def registry_handler(request: Request):
        if "origin" in request.headers:
            return JSONResponse({"code": "403", "msg": "forbidden"}, status_code=403)
        content_type = request.headers.get("content-type", "")
        if not content_type.lower().startswith("application/json"):
            return JSONResponse({"code": "415", "msg": "unsupported media type"}, status_code=415)
        try:
            data = await request.json()
        except (ValueError, TypeError):
            return JSONResponse({"code": "400", "msg": "invalid json"}, status_code=400)
        if not isinstance(data, dict):
            return JSONResponse({"code": "400", "msg": "invalid json"}, status_code=400)
        name = str(data.get("module_name") or "").strip()
        if not _MODULE_NAME.fullmatch(name):
            return JSONResponse({"code": "400", "msg": "invalid module_name"}, status_code=400)
        try:
            port = int(str(data.get("port")).strip())
        except (TypeError, ValueError):
            return JSONResponse({"code": "400", "msg": "invalid port"}, status_code=400)
        if not 1 <= port <= 65535:
            return JSONResponse({"code": "400", "msg": "invalid port"}, status_code=400)
        with lock:
            registry[name] = str(port)
        return Response("OK", media_type="text/plain")

    async def http_forward(request: Request):
        if request.url.path == "/rpa-local-route/registry":
            return Response(status_code=405)
        preflight = _preflight(request)
        if preflight is not None:
            return preflight
        client = request.app.state.client
        upstream = None
        try:
            forwarded = client.build_request(
                request.method,
                target(request.scope),
                headers=_headers(request.headers.raw, request=True),
                content=request.stream(),
            )
            upstream = await client.send(forwarded, stream=True)
        except (httpx.HTTPError, OSError, ValueError):
            if upstream is not None:
                await upstream.aclose()
            return _bad_gateway()

        async def chunks():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            except httpx.HTTPError:
                raise RuntimeError("Upstream response stream interrupted") from None
            finally:
                await upstream.aclose()

        response = StreamingResponse(chunks(), status_code=upstream.status_code)
        response.raw_headers = _with_acao(_headers(upstream.headers.raw))
        return response

    async def websocket_forward(websocket: WebSocket):
        headers = [
            (name.decode(), value.decode())
            for name, value in _headers(websocket.headers.raw, request=True, websocket=True)
        ]
        try:
            async with connect(
                target(websocket.scope, websocket=True),
                additional_headers=headers,
                subprotocols=websocket.scope.get("subprotocols") or None,
                proxy=None,
                open_timeout=10,
                close_timeout=5,
                max_size=None,
            ) as upstream:
                await websocket.accept(subprotocol=upstream.subprotocol)

                async def outbound():
                    while True:
                        message = await websocket.receive()
                        if message["type"] == "websocket.disconnect":
                            return
                        await upstream.send(
                            message.get("bytes") if message.get("bytes") is not None else message["text"]
                        )

                async def inbound():
                    async for message in upstream:
                        if isinstance(message, bytes):
                            await websocket.send_bytes(message)
                        else:
                            await websocket.send_text(message)

                tasks = [asyncio.create_task(outbound()), asyncio.create_task(inbound())]
                try:
                    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except InvalidStatus as exc:
            status = exc.response.status_code
            await websocket.send_denial_response(Response(status_code=502 if 300 <= status < 400 else status))
            return
        except (OSError, InvalidHandshake, TimeoutError, WebSocketDisconnect, ConnectionClosed):
            pass
        finally:
            if websocket.application_state.name != "DISCONNECTED":
                await websocket.close(code=1001)

    return Starlette(
        lifespan=lifespan,
        routes=[
            Route("/rpa-local-route/health", health, methods=["GET", "OPTIONS"]),
            Route("/rpa-local-route/registry", registry_handler, methods=["POST"]),
            Route("/{path:path}", http_forward, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]),
            WebSocketRoute("/{path:path}", websocket_forward),
        ],
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--httpProtocol", dest="http_protocol", required=True)
    parser.add_argument("--wsProtocol", dest="ws_protocol", required=True)
    parser.add_argument("--remoteHost", dest="remote_host", required=True)
    args = parser.parse_args()
    app = create_app(
        _unquote(args.http_protocol),
        _unquote(args.ws_protocol),
        _unquote(args.remote_host),
    )
    uvicorn.run(app, host="127.0.0.1", port=int(_unquote(args.port)), log_level="warning")


if __name__ == "__main__":
    main()
