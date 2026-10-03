"""手动试高亮 overlay：向 localhost:<port> 发一串 start/picking/validate/initialize。

用法: python hl_demo.py [port]
默认端口 11001。末尾发送 Exit 让 highlighter 退出。
"""

from __future__ import annotations

import json
import socket
import sys
import time

DEFAULT_PORT = 11001


def send(sock: socket.socket, port: int, payload: dict) -> None:
    sock.sendto(json.dumps(payload, ensure_ascii=False).encode("utf-8"), ("127.0.0.1", port))
    time.sleep(0.05)


def main() -> None:
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        send(sock, port, {"Operation": "start", "Type": "normal"})
        send(
            sock,
            port,
            {
                "Operation": "picking",
                "Type": "normal",
                "Boxes": [{"Left": 120, "Top": 140, "Right": 420, "Bottom": 320, "Msg": "Button"}],
            },
        )
        time.sleep(0.6)
        send(sock, port, {"Operation": "start", "Type": "CV"})
        send(
            sock,
            port,
            {
                "Operation": "picking",
                "Type": "normal",
                "Boxes": [
                    {"Left": 80, "Top": 80, "Right": 220, "Bottom": 140, "Msg": "A"},
                    {"Left": 360, "Top": 180, "Right": 560, "Bottom": 360, "Msg": "B"},
                ],
            },
        )
        time.sleep(3.2)
        send(
            sock,
            port,
            {
                "Operation": "validate",
                "Boxes": [{"Left": 200, "Top": 160, "Right": 520, "Bottom": 400, "Msg": ""}],
            },
        )
        time.sleep(2.0)
        send(sock, port, {"Operation": "initialize", "Type": "ESC"})
        time.sleep(0.2)
        send(sock, port, {"Operation": "initialize", "Type": "Exit"})
    finally:
        sock.close()


if __name__ == "__main__":
    main()
