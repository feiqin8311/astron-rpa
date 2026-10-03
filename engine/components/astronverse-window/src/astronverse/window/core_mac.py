from dataclasses import dataclass
from typing import Any, Optional

from astronverse.actionlib.types import WinPick
from astronverse.locator.core import ax_common
from astronverse.window import ControlInfo, WalkControlInfo, WindowSizeType
from astronverse.window.core import IUITreeCore, IWindowsCore
from astronverse.window.error import WINDOW_NO_FIND, BaseException


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


def _ax_point(x: float, y: float):
    from ApplicationServices import AXValueCreate, kAXValueCGPointType
    from Quartz import CGPoint

    return AXValueCreate(kAXValueCGPointType, CGPoint(float(x), float(y)))


def _ax_size(w: float, h: float):
    from ApplicationServices import AXValueCreate, kAXValueCGSizeType
    from Quartz import CGSize

    return AXValueCreate(kAXValueCGSizeType, CGSize(float(w), float(h)))


def _visible_frame_ax() -> Optional[tuple]:
    """Cocoa visibleFrame -> AX 左上原点 (left, top, width, height)。"""
    from AppKit import NSScreen

    screen = NSScreen.mainScreen()
    if not screen:
        return None
    frame = screen.frame()
    vis = screen.visibleFrame()
    ax_left = vis.origin.x
    ax_top = frame.size.height - vis.origin.y - vis.size.height
    return ax_left, ax_top, vis.size.width, vis.size.height


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
    pids = _candidate_pids(app_name, bundle_id)
    for pid in pids:
        app_el = ax_common.app_element(pid)
        if not app_el:
            continue
        for win in ax_common.app_windows(app_el):
            yield pid, win


def _unwrap(control: Any) -> Any:
    if isinstance(control, ax_common.AXControl):
        return control._element
    return control


class WindowsCore(IWindowsCore):
    @staticmethod
    def find(pick: WinPick) -> Any:
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
        raise BaseException(WINDOW_NO_FIND, "未找到目标窗口{}".format(pick))

    @staticmethod
    def top(handler: Any):
        if handler is None:
            return
        ax_common.raise_window(handler.ax_window, handler.pid)

    @staticmethod
    def info(handler: Any) -> ControlInfo:
        win = handler.ax_window
        rect = ax_common.ax_rect(win)
        position = (rect.left, rect.top, rect.right, rect.bottom) if rect else (0, 0, 0, 0)
        return ControlInfo(
            name=handler.title,
            classname=str(ax_common.ax_attr(win, "AXSubrole") or ""),
            position=position,
            handler=handler,
        )

    @staticmethod
    def close(handler: Any):
        if handler is None:
            return
        btn = ax_common.ax_attr(handler.ax_window, "AXCloseButton")
        if btn:
            ax_common.ax_perform(btn)
            return
        ax_common.ax_perform(handler.ax_window, "AXPress")

    @staticmethod
    def size(
        handler: Any,
        size_type: WindowSizeType = WindowSizeType.MAX,
        width: int = 0,
        height: int = 0,
    ):
        if handler is None:
            return
        win = handler.ax_window
        if ax_common.ax_attr(win, "AXMinimized"):
            ax_common.ax_set_attr(win, "AXMinimized", False)

        if size_type == WindowSizeType.MIN:
            ax_common.ax_set_attr(win, "AXMinimized", True)
            return

        if size_type == WindowSizeType.CUSTOM:
            ax_common.ax_set_attr(win, "AXSize", _ax_size(width, height))
            return

        # MAX：优先 AXZoomButton；已缩放则落到 visibleFrame
        zoomed = bool(ax_common.ax_attr(win, "AXFullScreen") or ax_common.ax_attr(win, "AXZoomed"))
        zoom_btn = ax_common.ax_attr(win, "AXZoomButton")
        if zoom_btn and not zoomed:
            ax_common.ax_perform(zoom_btn)
            return
        frame = _visible_frame_ax()
        if not frame:
            return
        left, top, w, h = frame
        ax_common.ax_set_attr(win, "AXPosition", _ax_point(left, top))
        ax_common.ax_set_attr(win, "AXSize", _ax_size(w, h))

    @staticmethod
    def toControl(handler: Any) -> Any:  # noqa: N802
        return ax_common.AXControl(handler.ax_window)


class UITreeCore(IUITreeCore):
    @staticmethod
    def GetRootControl() -> Any:  # noqa: N802
        from ApplicationServices import AXUIElementCreateSystemWide

        return ax_common.AXControl(AXUIElementCreateSystemWide())

    @staticmethod
    def WalkControl(control: Any, includeTop: bool = False, maxDepth: int = 0xFFFFFFFF):  # noqa: N802, N803
        el = _unwrap(control)

        def _info(node, depth: int) -> WalkControlInfo:
            wrapped = node if isinstance(node, ax_common.AXControl) else ax_common.AXControl(node)
            rect = wrapped.rect
            position = (rect.left, rect.top, rect.right, rect.bottom) if rect else (0, 0, 0, 0)
            return WalkControlInfo(
                name=wrapped.Name,
                classname=wrapped.subrole,
                position=position,
                control=wrapped,
                depth=depth,
                control_type=wrapped.role,
                control_type_name=wrapped.ControlTypeName,
                automation_id=wrapped.identifier,
            )

        def _children(node) -> list:
            raw = _unwrap(node)
            kids = ax_common.ax_children(raw)
            if kids:
                return kids
            # system-wide 无 AXChildren：退到常规 app 列表
            pid = ax_common.pid_of(raw)
            if pid:
                return []
            return [ax_common.app_element(p) for p in _regular_app_pids() if ax_common.app_element(p)]

        def walk(node, depth: int):
            if includeTop or depth > 0:
                yield _info(node, depth)
            if depth >= maxDepth:
                return
            for child in _children(node):
                if child is None:
                    continue
                yield from walk(child, depth + 1)

        if includeTop:
            yield from walk(el, 0)
        else:
            for child in _children(el):
                if child is None:
                    continue
                yield from walk(child, 1)

    @staticmethod
    def toHandler(control) -> Any:  # noqa: N802
        el = _unwrap(control)
        win = ax_common.window_of(el) or el
        pid = ax_common.pid_of(win) or 0
        return MacWindow(pid=pid, ax_window=win, title=_window_title(win))

    @staticmethod
    def setAction(control) -> bool:  # noqa: N802
        if isinstance(control, ax_common.AXControl):
            return control.press()
        return ax_common.ax_perform(_unwrap(control))
