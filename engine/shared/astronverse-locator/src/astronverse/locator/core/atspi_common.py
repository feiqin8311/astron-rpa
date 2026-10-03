"""Linux AT-SPI helpers shared by picker and locator.

Hit-test: X11 window under pointer -> _NET_WM_PID -> AT-SPI application
-> Component.get_accessible_at_point.

GTK4 AT-SPI SCREEN extents are often window-relative. Compensate with the
X11 toplevel origin and _GTK_FRAME_EXTENTS (CSD).

AT-SPI is synchronous D-Bus. Calls go through Atspi.set_timeout plus a
worker thread with a hard timeout so a stuck target app cannot freeze pick.
"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any, Optional

from astronverse.baseline.logger.logger import logger
from astronverse.locator import Rect

ATSPI_CALL_TIMEOUT_MS = 1000
ATSPI_THREAD_TIMEOUT_S = 1.2
WEB_ROLES = frozenset({"document web", "document", "html container"})

_inited = False
_init_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="atspi")
_window_meta: dict[int, tuple[int, tuple[int, int], tuple[int, int]]] = {}


def _ensure_linux() -> None:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("AT-SPI is only supported on Linux")


def _atspi():
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    return Atspi


def ensure_init() -> None:
    global _inited
    if _inited:
        return
    with _init_lock:
        if _inited:
            return
        _ensure_linux()
        atspi = _atspi()
        atspi.init()
        atspi.set_timeout(ATSPI_CALL_TIMEOUT_MS, ATSPI_CALL_TIMEOUT_MS)
        _inited = True


def call_with_timeout(fn, timeout: float = ATSPI_THREAD_TIMEOUT_S, default=None):
    """Run fn on the AT-SPI worker thread; return default on timeout/error."""
    try:
        return _executor.submit(fn).result(timeout=timeout)
    except (FuturesTimeout, Exception) as exc:
        logger.debug("atspi call timeout/error: %s", exc)
        return default


def parse_xdotool_location(text: str) -> tuple[int, int, int]:
    vals: dict[str, int] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        try:
            vals[key.strip()] = int(value.strip())
        except ValueError:
            continue
    return vals.get("X", 0), vals.get("Y", 0), vals.get("WINDOW", 0)


def parse_xprop_pid(text: str) -> int:
    match = re.search(r"_NET_WM_PID\(CARDINAL\)\s*=\s*(\d+)", text)
    return int(match.group(1)) if match else 0


def parse_gtk_frame_extents(text: str) -> tuple[int, int]:
    """Return (left, top) CSD extents from xprop _GTK_FRAME_EXTENTS."""
    match = re.search(r"_GTK_FRAME_EXTENTS\(CARDINAL\)\s*=\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)", text)
    if not match:
        return 0, 0
    left, _right, top, _bottom = (int(match.group(i)) for i in range(1, 5))
    return left, top


def parse_xwininfo_origin(text: str) -> tuple[int, int]:
    abs_x = re.search(r"Absolute upper-left X:\s*(-?\d+)", text)
    abs_y = re.search(r"Absolute upper-left Y:\s*(-?\d+)", text)
    return int(abs_x.group(1) if abs_x else 0), int(abs_y.group(1) if abs_y else 0)


def compensate_gtk4_rect(
    ext_x: int,
    ext_y: int,
    ext_w: int,
    ext_h: int,
    origin_x: int,
    origin_y: int,
    frame_left: int = 0,
    frame_top: int = 0,
) -> Rect:
    """Map GTK4 window-relative SCREEN extents to global screen coords."""
    left = origin_x + ext_x - frame_left
    top = origin_y + ext_y - frame_top
    return Rect(left, top, left + ext_w, top + ext_h)


def gtk4_point_to_window(
    screen_x: int,
    screen_y: int,
    origin_x: int,
    origin_y: int,
    frame_left: int = 0,
    frame_top: int = 0,
) -> tuple[int, int]:
    return screen_x - origin_x + frame_left, screen_y - origin_y + frame_top


def is_gtk4_toolkit(name: str, version: str) -> bool:
    toolkit = (name or "").strip().lower()
    if toolkit not in ("gtk", "gtk4", "gail"):
        return False
    if toolkit == "gtk4":
        return True
    ver = (version or "").strip()
    return ver.startswith("4")


# ponytail: xdotool/xprop per hover is ~10-30ms; ctypes libX11 if pick lag shows
def pointer_window() -> tuple[int, int, int]:
    try:
        out = subprocess.check_output(
            ["xdotool", "getmouselocation", "--shell"],
            encoding="utf-8",
            errors="replace",
            timeout=1,
        )
        return parse_xdotool_location(out)
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as exc:
        logger.debug("pointer_window: %s", exc)
        return 0, 0, 0


def _xprop(window_id: int, atom: str) -> str:
    try:
        return subprocess.check_output(
            ["xprop", "-id", str(window_id), atom],
            encoding="utf-8",
            errors="replace",
            timeout=1,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return ""


def window_pid(window_id: int) -> int:
    if not window_id:
        return 0
    return parse_xprop_pid(_xprop(window_id, "_NET_WM_PID"))


def window_origin_and_frame(window_id: int) -> tuple[tuple[int, int], tuple[int, int]]:
    if not window_id:
        return (0, 0), (0, 0)
    try:
        info = subprocess.check_output(
            ["xwininfo", "-id", str(window_id)],
            encoding="utf-8",
            errors="replace",
            timeout=1,
        )
        origin = parse_xwininfo_origin(info)
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        origin = (0, 0)
    frame = parse_gtk_frame_extents(_xprop(window_id, "_GTK_FRAME_EXTENTS"))
    return origin, frame


def window_meta(window_id: int) -> tuple[int, tuple[int, int], tuple[int, int]]:
    cached = _window_meta.get(window_id)
    if cached:
        return cached
    pid = window_pid(window_id)
    origin, frame = window_origin_and_frame(window_id)
    meta = (pid, origin, frame)
    if window_id:
        _window_meta[window_id] = meta
        if len(_window_meta) > 64:
            _window_meta.pop(next(iter(_window_meta)))
    return meta


def origin_frame_for_pid(pid: int) -> tuple[tuple[int, int], tuple[int, int]]:
    """X11 origin + CSD frame for an AT-SPI process, from pointer cache or xdotool."""
    if not pid:
        return (0, 0), (0, 0)
    for _xid, (cached_pid, origin, frame) in _window_meta.items():
        if cached_pid == pid:
            return origin, frame
    try:
        out = subprocess.check_output(
            ["xdotool", "search", "--pid", str(pid)],
            encoding="utf-8",
            errors="replace",
            timeout=1,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return (0, 0), (0, 0)
    for token in out.split():
        try:
            xid = int(token)
        except ValueError:
            continue
        if xid:
            _pid, origin, frame = window_meta(xid)
            return origin, frame
    return (0, 0), (0, 0)


def _role_name(el: Any) -> str:
    if el is None:
        return ""
    try:
        name = el.get_role_name()
        return str(name or "")
    except Exception:
        return ""


def _toolkit_of(el: Any) -> tuple[str, str]:
    try:
        app = el.get_application() if hasattr(el, "get_application") else el
        if app is None:
            return "", ""
        name = app.get_toolkit_name() if hasattr(app, "get_toolkit_name") else ""
        version = app.get_toolkit_version() if hasattr(app, "get_toolkit_version") else ""
        return str(name or ""), str(version or "")
    except Exception:
        return "", ""


def atspi_rect(
    el: Any,
    origin: Optional[tuple[int, int]] = None,
    frame: Optional[tuple[int, int]] = None,
) -> Optional[Rect]:
    if el is None:
        return None
    try:
        atspi = _atspi()
        comp = el.get_component()
        if comp is None:
            return None
        ext = comp.get_extents(atspi.CoordType.SCREEN)
        if ext is None:
            return None
        x, y, w, h = int(ext.x), int(ext.y), int(ext.width), int(ext.height)
        toolkit, version = _toolkit_of(el)
        if is_gtk4_toolkit(toolkit, version):
            if origin is None or frame is None:
                looked_o, looked_f = origin_frame_for_pid(pid_of(el))
                if origin is None:
                    origin = looked_o
                if frame is None:
                    frame = looked_f
            ox, oy = origin
            fl, ft = frame
            if (ox, oy) != (0, 0) or (fl, ft) != (0, 0):
                return compensate_gtk4_rect(x, y, w, h, ox, oy, fl, ft)
        return Rect(x, y, x + w, y + h)
    except Exception as exc:
        logger.debug("atspi_rect: %s", exc)
        return None


def atspi_name(el: Any) -> str:
    if el is None:
        return ""
    try:
        return str(el.get_name() or "")
    except Exception:
        return ""


def atspi_value(el: Any) -> str:
    if el is None:
        return ""
    try:
        text = el.get_text_iface() if hasattr(el, "get_text_iface") else None
        if text is None and hasattr(el, "get_text"):
            try:
                return str(el.get_text(0, -1) or "")
            except Exception:
                pass
        if text is not None:
            return str(text.get_text(0, -1) or "")
    except Exception:
        pass
    try:
        return str(el.get_description() or "")
    except Exception:
        return ""


def atspi_identifier(el: Any) -> str:
    try:
        attrs = el.get_attributes()
        if not attrs:
            return ""
        if hasattr(attrs, "get"):
            for key in ("id", "accessible-id", "class"):
                val = attrs.get(key)
                if val:
                    return str(val)
        if isinstance(attrs, dict):
            return str(attrs.get("id") or attrs.get("accessible-id") or "")
    except Exception:
        pass
    return ""


def atspi_cls(el: Any) -> str:
    try:
        attrs = el.get_attributes()
        if hasattr(attrs, "get"):
            return str(attrs.get("class") or attrs.get("class-name") or "")
        if isinstance(attrs, dict):
            return str(attrs.get("class") or "")
    except Exception:
        pass
    return ""


def atspi_parent(el: Any) -> Any:
    if el is None:
        return None
    try:
        return el.get_parent()
    except Exception:
        return None


def atspi_children(el: Any) -> list:
    if el is None:
        return []
    try:
        count = int(el.get_child_count() or 0)
    except Exception:
        return []
    children = []
    for i in range(min(count, 200)):
        try:
            child = el.get_child_at_index(i)
        except Exception:
            continue
        if child is not None:
            children.append(child)
    return children


def pid_of(el: Any) -> int:
    if el is None:
        return 0
    try:
        pid = el.get_process_id()
        return int(pid) if pid else 0
    except Exception:
        return 0


def desktop():
    ensure_init()
    return _atspi().get_desktop(0)


def iter_applications() -> list:
    root = desktop()
    if root is None:
        return []
    return atspi_children(root)


def app_by_pid(pid: int) -> Any:
    if not pid:
        return None
    for app in iter_applications():
        if pid_of(app) == pid:
            return app
    return None


app_element = app_by_pid


def _is_same_element(e1: Any, e2: Any) -> bool:
    if e1 is e2:
        return True
    if e1 is None or e2 is None:
        return False
    try:
        if e1 == e2:
            return True
    except Exception:
        pass
    try:
        id1 = e1.get_accessible_id() if hasattr(e1, "get_accessible_id") else None
        id2 = e2.get_accessible_id() if hasattr(e2, "get_accessible_id") else None
        if id1 and id2 and id1 == id2 and pid_of(e1) == pid_of(e2):
            return True
    except Exception:
        pass
    r1 = atspi_rect(e1)
    r2 = atspi_rect(e2)
    return (
        pid_of(e1) == pid_of(e2) and _role_name(e1) == _role_name(e2) and atspi_name(e1) == atspi_name(e2) and r1 == r2
    )


def find_apps(app_name: str, bundle_id: Optional[str] = None) -> list[int]:
    target = (app_name or bundle_id or "").strip().lower()
    pids = []
    for app in iter_applications():
        pid = pid_of(app)
        if not pid:
            continue
        if not target:
            pids.append(pid)
            continue
        name = atspi_name(app).strip().lower()
        try:
            import psutil

            proc_name = psutil.Process(pid).name().lower()
        except Exception:
            proc_name = ""
        if target in (name, proc_name) or target in name or target in proc_name:
            pids.append(pid)
    return pids


def app_windows(app_el: Any) -> list:
    wins = []
    for child in atspi_children(app_el):
        role = _role_name(child).lower()
        if role in ("frame", "window", "dialog", "file chooser"):
            wins.append(child)
        else:
            # some toolkits nest the frame one level down
            for nested in atspi_children(child):
                nrole = _role_name(nested).lower()
                if nrole in ("frame", "window", "dialog"):
                    wins.append(nested)
    return wins or atspi_children(app_el)


def window_of(el: Any) -> Any:
    curr = el
    seen: set[int] = set()
    while curr is not None and id(curr) not in seen:
        seen.add(id(curr))
        role = _role_name(curr).lower()
        if role in ("frame", "window", "dialog", "application"):
            return curr
        curr = atspi_parent(curr)
    return el


def raise_window(win_el: Any, pid: Optional[int] = None) -> None:
    if not pid:
        pid = pid_of(win_el)
    if not pid:
        return
    try:
        subprocess.run(
            ["xdotool", "search", "--pid", str(pid), "windowactivate"],
            check=False,
            timeout=1,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass


def _point_in_app(app_el: Any, x: int, y: int, origin: tuple[int, int], frame: tuple[int, int]) -> Any:
    atspi = _atspi()
    toolkit, version = _toolkit_of(app_el)
    px, py = x, y
    coord = atspi.CoordType.SCREEN
    if is_gtk4_toolkit(toolkit, version) and origin != (0, 0):
        px, py = gtk4_point_to_window(x, y, origin[0], origin[1], frame[0], frame[1])
        coord = atspi.CoordType.WINDOW
    try:
        comp = app_el.get_component()
        if comp is not None:
            hit = comp.get_accessible_at_point(px, py, coord)
            if hit is not None:
                return hit
    except Exception as exc:
        logger.debug("get_accessible_at_point app: %s", exc)
    for win in app_windows(app_el):
        try:
            comp = win.get_component()
            if comp is None:
                continue
            hit = comp.get_accessible_at_point(px, py, coord)
            if hit is not None:
                return hit
        except Exception:
            continue
    return None


def element_at_point(x: float, y: float) -> Any:
    """X11 window -> pid -> AT-SPI app -> accessible at point."""

    def _run():
        ensure_init()
        sx, sy = int(round(x)), int(round(y))
        _, _, xid = pointer_window()
        pid, origin, frame = window_meta(xid) if xid else (0, (0, 0), (0, 0))
        app = app_by_pid(pid) if pid else None
        if app is None:
            # fallback: scan apps (slow; last resort)
            for candidate in iter_applications():
                hit = _point_in_app(candidate, sx, sy, origin, frame)
                if hit is not None:
                    return hit
            return None
        return _point_in_app(app, sx, sy, origin, frame) or app

    return call_with_timeout(_run)


def node_of(el: Any, siblings: Optional[list] = None) -> dict:
    tag_name = _role_name(el)
    name = atspi_name(el)
    cls = atspi_cls(el)
    value = atspi_value(el)
    identifier = atspi_identifier(el)
    index = 0
    parent = atspi_parent(el)
    kids = siblings if siblings is not None else (atspi_children(parent) if parent else [])
    same = [c for c in kids if _role_name(c) == tag_name]
    for i, child in enumerate(same):
        if child is el:
            index = i
            break
    node = {"tag_name": tag_name, "name": name, "index": index, "checked": True}
    if cls:
        node["cls"] = cls
    if value:
        node["value"] = value
    if identifier:
        node["identifier"] = identifier
    return node


def build_path(el: Any) -> dict:
    pid = pid_of(el)
    app_name = ""
    try:
        import psutil

        if pid:
            app_name = psutil.Process(pid).name()
    except Exception:
        pass
    if not app_name:
        app = None
        try:
            app = el.get_application()
        except Exception:
            app = None
        app_name = atspi_name(app) if app is not None else ""

    chain = []
    curr = el
    seen: set[int] = set()
    while curr is not None and id(curr) not in seen:
        seen.add(id(curr))
        chain.append(curr)
        role = _role_name(curr).lower()
        if role in ("frame", "window", "dialog", "application"):
            break
        parent = atspi_parent(curr)
        if parent is None or parent is curr:
            break
        curr = parent
    chain.reverse()

    path_list = []
    for i, item in enumerate(chain):
        parent = chain[i - 1] if i else None
        siblings = atspi_children(parent) if parent is not None else None
        node = node_of(item, siblings=siblings)
        node["disable_keys"] = []
        path_list.append(node)

    return {
        "version": "1",
        "type": "atspi",
        "app": app_name,
        "path": path_list,
    }


def find_web_document(el: Any, max_depth: int = 30) -> Any:
    curr = el
    seen: set[int] = set()
    depth = 0
    while curr is not None and id(curr) not in seen and depth < max_depth:
        seen.add(id(curr))
        if _role_name(curr).lower() in WEB_ROLES:
            return curr
        curr = atspi_parent(curr)
        depth += 1
    if el is None:
        return None
    from collections import deque

    queue = deque([(el, 0)])
    seen = {id(el)}
    while queue:
        curr, d = queue.popleft()
        if _role_name(curr).lower() in WEB_ROLES:
            return curr
        if d >= max_depth:
            continue
        for child in atspi_children(curr):
            if id(child) in seen:
                continue
            seen.add(id(child))
            queue.append((child, d + 1))
    return None


class ATSPIControl:
    """Returned by ATSPILocator.control(); shape matches AXControl / UIA control."""

    def __init__(self, element: Any):
        self._element = element

    @property
    def Name(self) -> str:  # noqa: N802
        return atspi_name(self._element)

    @property
    def value(self) -> Optional[str]:
        val = atspi_value(self._element)
        return val or None

    @property
    def role(self) -> str:
        return _role_name(self._element)

    @property
    def ControlTypeName(self) -> str:  # noqa: N802
        role = self.role.lower()
        if role in ("entry", "text", "password text", "edit"):
            return "EditControl"
        if role in ("push button", "button"):
            return "ButtonControl"
        return self.role

    def set_value(self, text: str) -> bool:
        if self._element is None:
            return False
        try:
            editable = self._element.get_editable_text()
            if editable is not None:
                editable.set_text_contents("" if text is None else str(text))
                return True
        except Exception:
            pass
        return False

    def press(self) -> bool:
        try:
            action = self._element.get_action()
            if action is None:
                return False
            n = action.get_n_actions()
            for i in range(n):
                name = (action.get_name(i) or "").lower()
                if name in ("click", "press", "activate"):
                    return bool(action.do_action(i))
            if n:
                return bool(action.do_action(0))
        except Exception:
            return False
        return False

    def focus(self) -> bool:
        try:
            comp = self._element.get_component()
            if comp is not None and hasattr(comp, "grab_focus"):
                return bool(comp.grab_focus())
        except Exception:
            return False
        return False
