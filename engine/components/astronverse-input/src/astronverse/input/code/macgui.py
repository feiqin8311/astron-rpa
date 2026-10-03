"""macOS AX 窗口操作，语义对齐 win32gui.window_find/info/top。

client_position 在 mac 上等于窗口 rect 去掉标题栏：优先用第一个
AXScrollArea / AXGroup 子节点的 frame（相对窗口左上），拿不到时退回
整窗 (0, 0, width, height)。
"""

from dataclasses import dataclass
from typing import Any

from astronverse.actionlib.types import WinPick
from astronverse.input.code import ControlInfo
from astronverse.locator.core import ax_common


@dataclass
class MacWindow:
    pid: int
    ax_window: Any
    title: str


def _window_title(el: Any) -> str:
    name = (
        ax_common.ax_attr(el, "AXTitle")
        or ax_common.ax_attr(el, "AXDescription")
        or ax_common.ax_attr(el, "AXHelp")
        or ""
    )
    return str(name) if not isinstance(name, str) else name


def _regular_app_pids() -> list[int]:
    from AppKit import NSWorkspace

    pids = []
    apps = NSWorkspace.sharedWorkspace().runningApplications() or []
    for app in apps:
        try:
            if app.activationPolicy() != 0:  # NSApplicationActivationPolicyRegular
                continue
        except Exception:
            continue
        pid = app.processIdentifier()
        if pid and pid > 0:
            pids.append(int(pid))
    return pids


def _candidate_pids(app_name: str, bundle_id: str) -> list[int]:
    if app_name or bundle_id:
        return ax_common.find_apps(app_name, bundle_id or None)
    return _regular_app_pids()


def _iter_windows(app_name: str, bundle_id: str):
    for pid in _candidate_pids(app_name, bundle_id):
        app_el = ax_common.app_element(pid)
        if not app_el:
            continue
        for win in ax_common.app_windows(app_el):
            yield pid, win


def _client_position(win: Any, win_rect) -> tuple:
    """相对窗口左上的客户区 (l, t, r, b)。"""
    if win_rect is None:
        return (0, 0, 0, 0)
    full = (0, 0, win_rect.width(), win_rect.height())
    for child in ax_common.ax_children(win):
        role = ax_common.ax_attr(child, "AXRole") or ""
        if role not in ("AXScrollArea", "AXGroup"):
            continue
        crect = ax_common.ax_rect(child)
        if not crect:
            continue
        return (
            crect.left - win_rect.left,
            crect.top - win_rect.top,
            crect.right - win_rect.left,
            crect.bottom - win_rect.top,
        )
    return full


def window_find(pick: WinPick) -> Any:
    element = pick.get("elementData", {}) or {}
    path = element.get("path", []) or []
    node = path[0] if path else {}
    wnd_name = node.get("name", "") or ""
    wnd_cls = node.get("cls", "") or ""
    app_name = element.get("app", "") or ""
    bundle_id = element.get("bundle_id", "") or ""

    exact = []
    contains = []
    for pid, win in _iter_windows(app_name, bundle_id):
        if wnd_cls:
            sub = ax_common.ax_attr(win, "AXSubrole") or ""
            if str(sub) != wnd_cls:
                continue
        title = _window_title(win)
        handler = MacWindow(pid=pid, ax_window=win, title=title)
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
    win = handler.ax_window
    rect = ax_common.ax_rect(win)
    position = (rect.left, rect.top, rect.right, rect.bottom) if rect else (0, 0, 0, 0)
    return ControlInfo(
        name=handler.title,
        classname=str(ax_common.ax_attr(win, "AXSubrole") or ""),
        position=position,
        client_position=_client_position(win, rect),
        handler=handler,
    )


def window_top(handler):
    if handler is None:
        return
    ax_common.raise_window(handler.ax_window, handler.pid)
