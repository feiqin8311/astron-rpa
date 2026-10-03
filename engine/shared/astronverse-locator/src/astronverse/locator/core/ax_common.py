import operator
import sys
from typing import Any, Optional

from astronverse.baseline.logger.logger import logger
from astronverse.locator import Point, Rect


def _ensure_darwin() -> None:
    if sys.platform != "darwin":
        raise RuntimeError("macOS Accessibility is only supported on macOS (darwin)")


def _is_same_element(e1: Any, e2: Any) -> bool:
    if e1 is e2:
        return True
    if e1 is None or e2 is None:
        return False
    try:
        return bool(e1 == e2)
    except Exception:
        return False


def is_trusted(prompt: bool = False) -> bool:
    """Check if the process is trusted for macOS Accessibility.
    Returns False on non-darwin systems without raising.
    """
    if sys.platform != "darwin":
        return False
    try:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )

        options = {kAXTrustedCheckOptionPrompt: bool(prompt)} if prompt else None
        return bool(AXIsProcessTrustedWithOptions(options))
    except Exception as e:
        logger.debug(f"is_trusted check failed: {e}")
        return False


def ax_attr(el: Any, name: str, default: Any = None) -> Any:
    """AXUIElementCopyAttributeValue wrapper returning python values
    (AXValue CGPoint/CGSize/CGRect unpacked via AXValueGetValue),
    never raising for missing attributes.
    """
    if el is None:
        return default
    _ensure_darwin()
    try:
        from ApplicationServices import (
            AXUIElementCopyAttributeValue,
            AXValueGetType,
            AXValueGetTypeID,
            AXValueGetValue,
            kAXValueCGPointType,
            kAXValueCGRectType,
            kAXValueCGSizeType,
        )
        from CoreFoundation import CFGetTypeID

        err, val = AXUIElementCopyAttributeValue(el, name, None)
        if err != 0 or val is None:
            return default

        try:
            if CFGetTypeID(val) == AXValueGetTypeID():
                vtype = AXValueGetType(val)
                if vtype in (kAXValueCGPointType, kAXValueCGSizeType, kAXValueCGRectType):
                    ok, unpacked = AXValueGetValue(val, vtype, None)
                    if ok:
                        return unpacked
        except Exception:
            pass

        return val
    except Exception as e:
        logger.debug(f"ax_attr error for {name}: {e}")
        return default


def ax_set_attr(el: Any, name: str, value: Any) -> bool:
    """Set attribute value on AXUIElement. Returns True on success."""
    if el is None:
        return False
    _ensure_darwin()
    try:
        from ApplicationServices import AXUIElementSetAttributeValue

        err = AXUIElementSetAttributeValue(el, name, value)
        return err == 0
    except Exception as e:
        logger.debug(f"ax_set_attr error for {name}: {e}")
        return False


def ax_perform(el: Any, action: str = "AXPress") -> bool:
    """Perform action on AXUIElement (default AXPress). Returns True on success."""
    if el is None:
        return False
    _ensure_darwin()
    try:
        from ApplicationServices import AXUIElementPerformAction

        err = AXUIElementPerformAction(el, action)
        return err == 0
    except Exception as e:
        logger.debug(f"ax_perform error for {action}: {e}")
        return False


def ax_actions(el: Any) -> list[str]:
    """Copy action names supported by AXUIElement."""
    if el is None:
        return []
    _ensure_darwin()
    try:
        from ApplicationServices import AXUIElementCopyActionNames

        err, names = AXUIElementCopyActionNames(el, None)
        if err == 0 and names:
            return list(names)
        return []
    except Exception as e:
        logger.debug(f"ax_actions error: {e}")
        return []


def ax_children(el: Any) -> list:
    """Return child elements of AXUIElement."""
    if el is None:
        return []
    _ensure_darwin()
    try:
        children = ax_attr(el, "AXChildren", default=[])
        if children and isinstance(children, (list, tuple)):
            return list(children)
        return []
    except Exception as e:
        logger.debug(f"ax_children error: {e}")
        return []


def ax_parent(el: Any) -> Any:
    """Return parent element of AXUIElement."""
    if el is None:
        return None
    _ensure_darwin()
    return ax_attr(el, "AXParent")


def ax_rect(el: Any) -> Optional[Rect]:
    """Return locator Rect (left/top/right/bottom ints) from AXPosition and AXSize."""
    if el is None:
        return None
    _ensure_darwin()
    try:
        pos = ax_attr(el, "AXPosition")
        size = ax_attr(el, "AXSize")
        if pos is None or size is None:
            return None

        x = getattr(pos, "x", pos[0] if isinstance(pos, (list, tuple)) and len(pos) >= 1 else None)
        y = getattr(pos, "y", pos[1] if isinstance(pos, (list, tuple)) and len(pos) >= 2 else None)
        w = getattr(size, "width", size[0] if isinstance(size, (list, tuple)) and len(size) >= 1 else None)
        h = getattr(size, "height", size[1] if isinstance(size, (list, tuple)) and len(size) >= 2 else None)

        if x is None or y is None or w is None or h is None:
            return None

        left = int(round(x))
        top = int(round(y))
        right = int(round(x + w))
        bottom = int(round(y + h))
        return Rect(left, top, right, bottom)
    except Exception as e:
        logger.debug(f"ax_rect error: {e}")
        return None


def element_at_point(x: float, y: float, max_depth: int = 50) -> Any:
    """Deepest AXUIElement at point using AXUIElementCopyElementAtPosition,
    then refined by walking children whose rect contains the point to pick
    the smallest-area one (mirrors UIA min-area rule).
    """
    _ensure_darwin()
    try:
        from ApplicationServices import (
            AXUIElementCopyElementAtPosition,
            AXUIElementCreateSystemWide,
        )

        sys_wide = AXUIElementCreateSystemWide()
        err, el = AXUIElementCopyElementAtPosition(sys_wide, float(x), float(y), None)
        if err != 0 or el is None:
            return None

        pt = Point(int(round(x)), int(round(y)))
        curr = el
        visited = set()

        for _ in range(max_depth):
            curr_id = id(curr)
            if curr_id in visited:
                break
            visited.add(curr_id)

            children = ax_children(curr)
            if not children:
                break

            candidates = []
            for child in children:
                r = ax_rect(child)
                if r and r.contains(pt):
                    candidates.append((r.area(), child))

            if not candidates:
                break

            candidates.sort(key=operator.itemgetter(0))
            curr = candidates[0][1]

        return curr
    except Exception as e:
        logger.debug(f"element_at_point error at ({x}, {y}): {e}")
        return None


def app_element(pid: int) -> Any:
    """Create AXUIElement for application by PID with messaging timeout."""
    if not pid:
        return None
    _ensure_darwin()
    try:
        from ApplicationServices import (
            AXUIElementCreateApplication,
            AXUIElementSetMessagingTimeout,
        )

        el = AXUIElementCreateApplication(pid)
        if el is not None:
            AXUIElementSetMessagingTimeout(el, 1.0)
        return el
    except Exception as e:
        logger.debug(f"app_element error for pid {pid}: {e}")
        return None


def pid_of(el: Any) -> Optional[int]:
    """Get process PID of AXUIElement."""
    if el is None:
        return None
    _ensure_darwin()
    try:
        from ApplicationServices import AXUIElementGetPid

        err, pid = AXUIElementGetPid(el, None)
        if err == 0:
            return int(pid)
        return None
    except Exception as e:
        logger.debug(f"pid_of error: {e}")
        return None


def running_app(pid: int) -> Any:
    """Return NSRunningApplication for PID."""
    if not pid:
        return None
    _ensure_darwin()
    try:
        from AppKit import NSRunningApplication

        return NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    except Exception as e:
        logger.debug(f"running_app error for pid {pid}: {e}")
        return None


def app_windows(app_el: Any) -> list:
    """Return list of top-level AXWindows for application element."""
    if app_el is None:
        return []
    _ensure_darwin()
    try:
        wins = ax_attr(app_el, "AXWindows", default=[])
        if wins and isinstance(wins, (list, tuple)):
            return list(wins)
        return []
    except Exception as e:
        logger.debug(f"app_windows error: {e}")
        return []


def window_of(el: Any) -> Any:
    """Walk AXParent / AXWindow attribute up to the AXWindow."""
    if el is None:
        return None
    _ensure_darwin()
    try:
        if ax_attr(el, "AXRole") == "AXWindow":
            return el

        win = ax_attr(el, "AXWindow")
        if win is not None and ax_attr(win, "AXRole") == "AXWindow":
            return win

        curr = el
        visited = set()
        while curr:
            curr_id = id(curr)
            if curr_id in visited:
                break
            visited.add(curr_id)

            role = ax_attr(curr, "AXRole")
            if role == "AXWindow":
                return curr

            parent = ax_parent(curr)
            if not parent or _is_same_element(parent, curr):
                break
            curr = parent

        return None
    except Exception as e:
        logger.debug(f"window_of error: {e}")
        return None


def find_apps(app_name: str, bundle_id: Optional[str] = None) -> list[int]:
    """NSWorkspace.runningApplications match by localizedName / bundleIdentifier / executable name,
    case-insensitive.
    """
    _ensure_darwin()
    try:
        from AppKit import NSWorkspace

        apps = NSWorkspace.sharedWorkspace().runningApplications()
        if not apps:
            return []

        matched_bundle = []
        matched_name = []

        target_bid = bundle_id.strip().lower() if bundle_id else None
        target_name = app_name.strip().lower() if app_name else None

        for app in apps:
            bid = (app.bundleIdentifier() or "").strip()
            loc_name = (app.localizedName() or "").strip()
            exe_name = (app.executableURL().lastPathComponent() or "").strip() if app.executableURL() else ""

            pid = app.processIdentifier()
            if pid is None or pid <= 0:
                continue

            if target_bid and bid.lower() == target_bid:
                if pid not in matched_bundle:
                    matched_bundle.append(pid)

            if target_name:
                if loc_name.lower() == target_name or exe_name.lower() == target_name or bid.lower() == target_name:
                    if pid not in matched_name:
                        matched_name.append(pid)

        if matched_bundle:
            return matched_bundle
        return matched_name
    except Exception as e:
        logger.debug(f"find_apps error for {app_name}, {bundle_id}: {e}")
        return []


def raise_window(win_el: Any, pid: Optional[int] = None) -> None:
    """AXRaise + set AXMain/AXFocused +
    NSRunningApplication.activateWithOptions_(NSApplicationActivateIgnoringOtherApps);
    un-minimise if AXMinimized.
    """
    if win_el is None:
        return
    _ensure_darwin()
    try:
        if ax_attr(win_el, "AXMinimized"):
            ax_set_attr(win_el, "AXMinimized", False)

        ax_perform(win_el, "AXRaise")
        ax_set_attr(win_el, "AXMain", True)
        ax_set_attr(win_el, "AXFocused", True)

        if pid is None:
            pid = pid_of(win_el)
        if pid:
            app = running_app(pid)
            if app:
                from AppKit import NSApplicationActivateIgnoringOtherApps

                app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
    except Exception as e:
        logger.debug(f"raise_window error: {e}")


def node_of(el: Any, siblings: Optional[list] = None) -> dict:
    """Build a path node per the contract (without disable_keys)."""
    _ensure_darwin()
    tag_name = ax_attr(el, "AXRole") or ""
    cls = ax_attr(el, "AXSubrole") or ""
    name = ax_attr(el, "AXTitle") or ax_attr(el, "AXDescription") or ax_attr(el, "AXHelp") or ""
    if not isinstance(name, str):
        name = str(name)

    val = ax_attr(el, "AXValue")
    value = None
    if val is not None and isinstance(val, (str, int, float)):
        s_val = str(val).strip()
        if s_val:
            value = str(val)

    ident = ax_attr(el, "AXIdentifier")
    identifier = None
    if ident is not None and str(ident).strip():
        identifier = str(ident).strip()

    index = 0
    if tag_name == "AXWindow":
        if siblings is None:
            pid = pid_of(el)
            app_el = app_element(pid) if pid else None
            wins = app_windows(app_el) if app_el else []
        else:
            wins = siblings

        same_name_wins = [
            w
            for w in wins
            if (ax_attr(w, "AXTitle") or ax_attr(w, "AXDescription") or ax_attr(w, "AXHelp") or "") == name
        ]
        for i, w in enumerate(same_name_wins):
            if _is_same_element(w, el):
                index = i
                break
    else:
        if siblings is None:
            p = ax_parent(el)
            ch = ax_children(p) if p else []
        else:
            ch = siblings

        same_role_ch = [c for c in ch if (ax_attr(c, "AXRole") or "") == tag_name]
        for i, c in enumerate(same_role_ch):
            if _is_same_element(c, el):
                index = i
                break

    node = {
        "tag_name": tag_name,
        "name": name,
        "index": index,
        "checked": True,
    }
    if cls and str(cls).strip():
        node["cls"] = str(cls).strip()
    if value is not None:
        node["value"] = value
    if identifier is not None:
        node["identifier"] = identifier

    return node


def _calculate_disable_keys_progressive(
    current_attrs: dict,
    siblings: Optional[list],
    current_el: Any,
    is_root_level: bool = False,
) -> list[str]:
    """Port of uia_picker._calculate_disable_keys_progressive."""
    priority_attrs = ["tag_name", "cls", "name", "value", "index"]

    empty_attrs = []
    for attr in priority_attrs:
        val = current_attrs.get(attr)
        if val is None or str(val).strip() == "":
            empty_attrs.append(attr)

    available_attrs = [attr for attr in priority_attrs if attr not in empty_attrs]

    if not available_attrs:
        return priority_attrs.copy()

    if siblings is None:
        if is_root_level:
            return empty_attrs.copy()
        else:
            if "tag_name" not in empty_attrs:
                return [attr for attr in priority_attrs if attr != "tag_name"]
            return priority_attrs.copy()

    tag_name = current_attrs.get("tag_name")
    same_type_siblings = []
    for s in siblings:
        if _is_same_element(s, current_el):
            continue
        s_tag = ax_attr(s, "AXRole") or ""
        if s_tag == tag_name:
            same_type_siblings.append(s)

    if not same_type_siblings:
        disable_keys = empty_attrs.copy()
        disable_keys.extend([attr for attr in priority_attrs if attr != "tag_name" and attr not in empty_attrs])
        return disable_keys

    sibling_attrs_list = []
    for s in same_type_siblings:
        s_node = node_of(s, siblings=siblings)
        sibling_attrs_list.append(s_node)

    for i in range(len(available_attrs)):
        check_attrs = available_attrs[: i + 1]

        has_conflict = False
        for s_attrs in sibling_attrs_list:
            all_match = True
            for attr in check_attrs:
                c_val = str(current_attrs.get(attr, "")).strip()
                s_val = str(s_attrs.get(attr, "")).strip()
                if c_val != s_val:
                    all_match = False
                    break
            if all_match:
                has_conflict = True
                break

        if not has_conflict:
            disable_keys = empty_attrs.copy()
            disable_keys.extend(available_attrs[i + 1 :])
            return disable_keys

    return empty_attrs.copy()


def build_path(el: Any) -> dict:
    """Full element JSON (type "ax", app, bundle_id, path with disable_keys, no img)."""
    _ensure_darwin()
    pid = pid_of(el)
    app = running_app(pid) if pid else None
    app_name = (app.localizedName() or "") if app else ""
    bundle_id = (app.bundleIdentifier() or "") if app else ""

    chain = []
    curr = el
    visited = set()
    while curr:
        curr_id = id(curr)
        if curr_id in visited:
            break
        visited.add(curr_id)
        chain.append(curr)

        role = ax_attr(curr, "AXRole")
        if role in ("AXWindow", "AXApplication"):
            break

        parent = ax_parent(curr)
        if not parent or _is_same_element(parent, curr):
            win = window_of(el)
            if win and not any(_is_same_element(win, item) for item in chain):
                chain.append(win)
            break
        curr = parent

    chain.reverse()

    if not chain:
        return {
            "version": "1",
            "type": "ax",
            "app": app_name,
            "bundle_id": bundle_id,
            "path": [],
        }

    path_list = []
    root_el = chain[0]
    root_role = ax_attr(root_el, "AXRole")

    if root_role == "AXApplication":
        root_node = {
            "tag_name": "AXApplication",
            "name": app_name or (ax_attr(root_el, "AXTitle") or ""),
            "index": 0,
            "checked": True,
            "disable_keys": [],
        }
        path_list.append(root_node)
    else:
        app_el = app_element(pid) if pid else None
        wins = app_windows(app_el) if app_el else []
        root_node = node_of(root_el, siblings=wins)
        root_node["disable_keys"] = _calculate_disable_keys_progressive(root_node, wins, root_el, is_root_level=True)
        path_list.append(root_node)

    for idx in range(1, len(chain)):
        parent_el = chain[idx - 1]
        current_el = chain[idx]
        siblings = ax_children(parent_el)
        node = node_of(current_el, siblings=siblings)
        node["disable_keys"] = _calculate_disable_keys_progressive(node, siblings, current_el, is_root_level=False)
        path_list.append(node)

    return {
        "version": "1",
        "type": "ax",
        "app": app_name,
        "bundle_id": bundle_id,
        "path": path_list,
    }


class AXControl:
    """Wrapper class returned by AXLocator.control()."""

    def __init__(self, element: Any):
        self._element = element

    @property
    def Name(self) -> str:  # noqa: N802
        name = (
            ax_attr(self._element, "AXTitle")
            or ax_attr(self._element, "AXDescription")
            or ax_attr(self._element, "AXHelp")
            or ""
        )
        return str(name) if not isinstance(name, str) else name

    @property
    def value(self) -> Optional[str]:
        v = ax_attr(self._element, "AXValue")
        if v is not None and isinstance(v, (str, int, float)):
            return str(v)
        return None

    @property
    def role(self) -> str:
        return str(ax_attr(self._element, "AXRole") or "")

    @property
    def subrole(self) -> str:
        return str(ax_attr(self._element, "AXSubrole") or "")

    @property
    def identifier(self) -> str:
        return str(ax_attr(self._element, "AXIdentifier") or "")

    @property
    def enabled(self) -> bool:
        return bool(ax_attr(self._element, "AXEnabled", default=True))

    @property
    def focused(self) -> bool:
        return bool(ax_attr(self._element, "AXFocused", default=False))

    @property
    def rect(self) -> Optional[Rect]:
        return ax_rect(self._element)

    @property
    def ControlTypeName(self) -> str:  # noqa: N802
        r = self.role
        if r in ("AXTextField", "AXTextArea", "AXComboBox", "AXSearchField"):
            return "EditControl"
        elif r == "AXButton":
            return "ButtonControl"
        return r

    def set_value(self, text: str) -> bool:
        if self._element is None:
            return False
        _ensure_darwin()
        try:
            from ApplicationServices import AXUIElementIsAttributeSettable

            err, settable = AXUIElementIsAttributeSettable(self._element, "AXValue", None)
            if err == 0 and not settable:
                return False
        except Exception:
            pass
        return ax_set_attr(self._element, "AXValue", text)

    def press(self) -> bool:
        return ax_perform(self._element, "AXPress")

    def focus(self) -> bool:
        return ax_set_attr(self._element, "AXFocused", True)

    def children(self) -> list["AXControl"]:
        return [AXControl(c) for c in ax_children(self._element)]

    def parent(self) -> Optional["AXControl"]:
        p = ax_parent(self._element)
        return AXControl(p) if p else None

    def __repr__(self) -> str:
        return f"<AXControl role={self.role!r} Name={self.Name!r}>"

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, AXControl):
            return _is_same_element(self._element, other._element)
        return False
