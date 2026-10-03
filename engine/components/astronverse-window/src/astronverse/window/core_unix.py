import subprocess
from typing import Any

from astronverse.actionlib.types import WinPick
from astronverse.locator.core import atspi_common
from astronverse.window import ControlInfo, WalkControlInfo, WindowSizeType
from astronverse.window.core import IUITreeCore, IWindowsCore


def _xdotool(*args) -> str:
    return subprocess.check_output(["xdotool", *args], encoding="utf-8", errors="replace")


class WindowsCore(IWindowsCore):
    @staticmethod
    def info(handler: Any) -> ControlInfo:
        if not isinstance(handler, int):
            el = getattr(handler, "_element", handler)
            rect = atspi_common.atspi_rect(el)
            position = (rect.left, rect.top, rect.right, rect.bottom) if rect else (0, 0, 0, 0)
            return ControlInfo(
                name=atspi_common.atspi_name(el),
                classname=atspi_common.atspi_cls(el),
                position=position,
                handler=handler,
            )
        win_id = handler
        name = _xdotool("getwindowname", str(win_id)).strip()
        geom = {}
        output = _xdotool("getwindowgeometry", "--shell", str(win_id))
        for line in output.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            try:
                geom[key] = int(value)
            except ValueError:
                continue
        return ControlInfo(
            name=name,
            classname="",
            position=(geom.get("X", 0), geom.get("Y", 0), geom.get("WIDTH", 0), geom.get("HEIGHT", 0)),
            handler=handler,
        )

    @staticmethod
    def find(pick: WinPick) -> Any:
        element = pick.get("elementData", {}) or {}
        path = element.get("path", []) or []
        node = path[0] if path else {}
        wnd_name = node.get("name") or pick.get("name") or ""
        app_name = element.get("app") or ""
        if app_name or wnd_name:
            pids = atspi_common.find_apps(app_name) if app_name else atspi_common.find_apps("")
            exact = []
            contains = []
            for pid in pids:
                app_el = atspi_common.app_element(pid)
                for win in atspi_common.app_windows(app_el):
                    title = atspi_common.atspi_name(win) or ""
                    if not wnd_name or title == wnd_name:
                        exact.append(win)
                    elif wnd_name in title:
                        contains.append(win)
            if exact:
                return exact[0]
            if contains:
                return contains[0]
        if not wnd_name:
            return None
        try:
            output = _xdotool("search", "--name", wnd_name)
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            return None
        window_id = ""
        for line in output.splitlines():
            window_id = line
        return int(window_id) if window_id else None

    @staticmethod
    def top(handler: Any):
        if isinstance(handler, int):
            _xdotool("windowraise", str(handler))
            try:
                subprocess.run(
                    ["wmctrl", "-i", "-a", hex(handler) if handler else "0"],
                    check=False,
                    timeout=1,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except (subprocess.SubprocessError, FileNotFoundError, OSError):
                pass
            return
        pid = atspi_common.pid_of(getattr(handler, "_element", handler))
        atspi_common.raise_window(getattr(handler, "_element", handler), pid)

    @staticmethod
    def close(handler: Any):
        if isinstance(handler, int):
            _xdotool("windowclose", str(handler))
            return
        try:
            action = getattr(handler, "_element", handler).get_action()
            if action is not None:
                n = action.get_n_actions()
                for i in range(n):
                    if (action.get_name(i) or "").lower() in ("close", "press"):
                        action.do_action(i)
                        return
        except Exception:
            pass

    @staticmethod
    def size(
        handler: Any,
        size_type: WindowSizeType = WindowSizeType.MAX,
        width: int = 0,
        height: int = 0,
    ):
        if not isinstance(handler, int):
            raise NotImplementedError("AT-SPI window resize uses an X11 window id")
        win_id = handler
        if size_type == WindowSizeType.CUSTOM:
            _xdotool("windowsize", str(win_id), str(width), str(height))
        elif size_type == WindowSizeType.MAX:
            _xdotool("windowsize", str(win_id), "100%", "100%")
        elif size_type == WindowSizeType.MIN:
            _xdotool("windowminimize", str(win_id))

    @staticmethod
    def toControl(handler: Any) -> Any:  # noqa: N802
        if handler is None:
            return None
        if isinstance(handler, atspi_common.ATSPIControl):
            return handler
        if isinstance(handler, int):
            pid = atspi_common.window_pid(handler)
            app = atspi_common.app_by_pid(pid) if pid else None
            wins = atspi_common.app_windows(app) if app else []
            return atspi_common.ATSPIControl(wins[0]) if wins else None
        el = getattr(handler, "_element", handler)
        return atspi_common.ATSPIControl(el)


class UITreeCore(IUITreeCore):
    @staticmethod
    def GetRootControl() -> Any:  # noqa: N802
        return atspi_common.ATSPIControl(atspi_common.desktop())

    @staticmethod
    def WalkControl(control: Any, includeTop: bool = False, maxDepth: int = 0xFFFFFFFF):  # noqa: N802, N803
        el = getattr(control, "_element", control)

        def _info(node, depth: int) -> WalkControlInfo:
            wrapped = node if isinstance(node, atspi_common.ATSPIControl) else atspi_common.ATSPIControl(node)
            rect = atspi_common.atspi_rect(getattr(wrapped, "_element", node))
            position = (rect.left, rect.top, rect.right, rect.bottom) if rect else (0, 0, 0, 0)
            return WalkControlInfo(
                name=wrapped.Name,
                classname=atspi_common.atspi_cls(getattr(wrapped, "_element", node)),
                position=position,
                control=wrapped,
                depth=depth,
                control_type=wrapped.role,
                control_type_name=wrapped.ControlTypeName,
                automation_id=atspi_common.atspi_identifier(getattr(wrapped, "_element", node)),
            )

        def walk(node, depth: int):
            if includeTop or depth > 0:
                yield _info(node, depth)
            if depth >= maxDepth:
                return
            for child in atspi_common.atspi_children(getattr(node, "_element", node)):
                if child is None:
                    continue
                yield from walk(child, depth + 1)

        if includeTop:
            yield from walk(el, 0)
        else:
            for child in atspi_common.atspi_children(el):
                if child is None:
                    continue
                yield from walk(child, 1)

    @staticmethod
    def toHandler(control) -> Any:  # noqa: N802
        el = getattr(control, "_element", control)
        return atspi_common.window_of(el) or el

    @staticmethod
    def setAction(control) -> bool:  # noqa: N802
        if isinstance(control, atspi_common.ATSPIControl):
            return control.press()
        wrapped = atspi_common.ATSPIControl(control)
        return wrapped.press()
