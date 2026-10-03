"""Linux AT-SPI / xdotool 窗口操作，语义对齐 win32gui.window_find/info/top。"""

from dataclasses import dataclass
from typing import Any

from astronverse.actionlib.types import WinPick
from astronverse.input.code import ControlInfo
from astronverse.locator.core import atspi_common


@dataclass
class LinuxWindow:
    pid: int
    atspi_window: Any
    title: str
    xid: int = 0


def _window_title(el: Any) -> str:
    return str(atspi_common.atspi_name(el) or "")


def _iter_windows(app_name: str):
    pids = atspi_common.find_apps(app_name) if app_name else []
    if not pids:
        pids = atspi_common.find_apps("")
    for pid in pids:
        app_el = atspi_common.app_element(pid)
        if not app_el:
            continue
        for win in atspi_common.app_windows(app_el):
            yield pid, win


def window_find(pick: WinPick) -> Any:
    element = pick.get("elementData", {}) or {}
    path = element.get("path", []) or []
    node = path[0] if path else {}
    wnd_name = node.get("name", "") or pick.get("name") or ""
    wnd_cls = node.get("cls", "") or ""
    app_name = element.get("app", "") or ""

    exact = []
    contains = []
    for pid, win in _iter_windows(app_name):
        if wnd_cls:
            cls = atspi_common.atspi_cls(win) or ""
            if str(cls) != wnd_cls:
                continue
        title = _window_title(win)
        handler = LinuxWindow(pid=pid, atspi_window=win, title=title)
        if not wnd_name:
            exact.append(handler)
            continue
        if title == wnd_name:
            exact.append(handler)
        elif wnd_name in title:
            contains.append(handler)
    if exact:
        return exact[0]
    if contains:
        return contains[0]
    raise Exception("未找到目标窗口{}".format(pick))


def window_info(handler: Any) -> ControlInfo:
    win = handler.atspi_window
    rect = atspi_common.atspi_rect(win)
    position = (rect.left, rect.top, rect.right, rect.bottom) if rect else (0, 0, 0, 0)
    return ControlInfo(
        name=handler.title,
        classname=str(atspi_common.atspi_cls(win) or ""),
        position=position,
        client_position=position,
        handler=handler,
    )


def window_top(handler):
    if handler is None:
        return
    atspi_common.raise_window(handler.atspi_window, handler.pid)
