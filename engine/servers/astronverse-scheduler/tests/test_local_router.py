import asyncio
import socket
import threading
import time
from contextlib import contextmanager

from astronverse.scheduler.core.route.local_router import create_app
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from uvicorn import Config, Server


@contextmanager
def serve(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = Server(Config(app, log_level="warning", access_log=False, timeout_graceful_shutdown=1))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        yield port
    finally:
        server.should_exit = True
        thread.join(4)
        sock.close()


def closed_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def echo_app():
    async def echo(request):
        return JSONResponse(
            {
                "path": request.url.path,
                "query": request.url.query,
                "body": (await request.body()).decode(),
                "method": request.method,
            }
        )

    async def stream(request):
        async def chunks():
            yield b"first\n"
            await asyncio.sleep(0.01)
            yield b"second\n"

        return StreamingResponse(chunks())

    async def corsed(request):
        return Response("ok", headers={"Access-Control-Allow-Origin": "https://example.com"})

    async def ws(websocket):
        await websocket.accept()
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    await websocket.send_bytes(message["bytes"])
                else:
                    await websocket.send_text(message["text"])
        except WebSocketDisconnect:
            pass

    return Starlette(
        routes=[
            Route("/task/health", echo, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]),
            Route("/api/echo", echo, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]),
            Route("/api/stream", stream),
            Route("/api/corsed", corsed),
            WebSocketRoute("/ws", ws),
        ]
    )


def test_health_and_registry():
    app = create_app("http", "ws", f"127.0.0.1:{closed_port()}")
    with TestClient(app) as client:
        health = client.get("/rpa-local-route/health")
        assert health.status_code == 200
        assert "OK" in health.text
        registered = client.post("/rpa-local-route/registry", json={"module_name": "scheduler", "port": "12345"})
        assert registered.status_code == 200
        assert "OK" in registered.text
        again = client.post("/rpa-local-route/registry", json={"module_name": "scheduler", "port": "23456"})
        assert "OK" in again.text
        assert "access-control-allow-origin" not in again.headers


def test_prefix_fallback_post_stream_and_cors():
    with serve(echo_app()) as port:
        app = create_app("http", "ws", f"127.0.0.1:{port}")
        with TestClient(app) as client:
            assert (
                "OK"
                in client.post("/rpa-local-route/registry", json={"module_name": "trigger", "port": str(port)}).text
            )

            prefixed = client.get("/trigger/task/health?q=1&x=2")
            assert prefixed.status_code == 200
            assert prefixed.json()["path"] == "/task/health"
            assert prefixed.json()["query"] == "q=1&x=2"

            fallback = client.get("/api/echo?z=9")
            assert fallback.status_code == 200
            assert fallback.json()["path"] == "/api/echo"
            assert fallback.json()["query"] == "z=9"

            posted = client.post("/api/echo", content=b"hello-body")
            assert posted.json()["body"] == "hello-body"
            assert posted.json()["method"] == "POST"

            streamed = client.get("/api/stream")
            assert streamed.content == b"first\nsecond\n"

            preflight = client.options(
                "/api/echo",
                headers={
                    "Origin": "http://localhost:1420",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )
            assert preflight.status_code == 204
            assert preflight.headers["access-control-allow-origin"] == "*"
            assert preflight.headers["access-control-allow-methods"] == "*"
            assert preflight.headers["access-control-allow-headers"] == "content-type"
            assert preflight.headers["access-control-max-age"]

            corsed = client.get("/api/corsed")
            assert corsed.headers.get_list("access-control-allow-origin") == ["https://example.com"]
            echoed = client.get("/api/echo")
            assert echoed.headers.get_list("access-control-allow-origin") == ["*"]


def test_registry_rejects_web_origin():
    app = create_app("http", "ws", f"127.0.0.1:{closed_port()}")
    with TestClient(app) as client:
        response = client.post(
            "/rpa-local-route/registry",
            json={"module_name": "scheduler", "port": "12345"},
            headers={"Origin": "http://localhost:1420"},
        )
        assert response.status_code == 403
        assert "access-control-allow-origin" not in response.headers


def test_registry_rejects_text_plain():
    app = create_app("http", "ws", f"127.0.0.1:{closed_port()}")
    with TestClient(app) as client:
        response = client.post(
            "/rpa-local-route/registry",
            content=b'{"module_name":"scheduler","port":"12345"}',
            headers={"Content-Type": "text/plain"},
        )
        assert response.status_code == 415
        assert "access-control-allow-origin" not in response.headers


def test_registry_rejects_bad_module_name():
    app = create_app("http", "ws", f"127.0.0.1:{closed_port()}")
    with TestClient(app) as client:
        response = client.post("/rpa-local-route/registry", json={"module_name": "api/foo", "port": "12345"})
        assert response.status_code == 400


def test_registry_rejects_bad_port():
    app = create_app("http", "ws", f"127.0.0.1:{closed_port()}")
    with TestClient(app) as client:
        assert (
            client.post("/rpa-local-route/registry", json={"module_name": "scheduler", "port": "0"}).status_code == 400
        )
        assert (
            client.post("/rpa-local-route/registry", json={"module_name": "scheduler", "port": "65536"}).status_code
            == 400
        )
        assert (
            client.post("/rpa-local-route/registry", json={"module_name": "scheduler", "port": "abc"}).status_code
            == 400
        )


def test_502_when_upstream_down():
    dead = closed_port()
    app = create_app("http", "ws", f"127.0.0.1:{dead}")
    with TestClient(app) as client:
        remote = client.get("/api/echo")
        assert remote.status_code == 502
        assert remote.json()["code"] == "502"
        assert "msg" in remote.json()
        assert "OK" in client.post("/rpa-local-route/registry", json={"module_name": "trigger", "port": str(dead)}).text
        local = client.get("/trigger/task/health")
        assert local.status_code == 502
        assert local.json()["code"] == "502"


def test_websocket_proxy_echo():
    with serve(echo_app()) as port:
        app = create_app("http", "ws", f"127.0.0.1:{port}")
        with TestClient(app) as client:
            assert (
                "OK"
                in client.post(
                    "/rpa-local-route/registry",
                    json={"module_name": "browser_connector", "port": str(port)},
                ).text
            )
            with client.websocket_connect("/browser_connector/ws") as ws:
                ws.send_text("hello")
                assert ws.receive_text() == "hello"
                ws.send_bytes(b"bin")
                assert ws.receive_bytes() == b"bin"
            with client.websocket_connect("/ws") as ws:
                ws.send_text("remote")
                assert ws.receive_text() == "remote"
                ws.send_bytes(b"raw")
                assert ws.receive_bytes() == b"raw"
