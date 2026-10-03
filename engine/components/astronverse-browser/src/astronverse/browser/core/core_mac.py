import os
import time
from collections import deque
from typing import Any, Optional

from astronverse.browser import BROWSER_MAC_APP_NAME, BROWSER_MAC_BUNDLE_ID
from astronverse.browser.error import DOWNLOAD_WINDOW_NO_FIND, UPLOAD_WINDOW_NO_FIND, BaseException


def _browser_type_value(browser_type: Any) -> str:
    if browser_type is None:
        return ""
    return browser_type.value if hasattr(browser_type, "value") else str(browser_type)


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


def _is_standard_window(el: Any) -> bool:
    from astronverse.locator.core.ax_common import ax_attr

    if ax_attr(el, "AXRole") != "AXWindow":
        return False
    subrole = ax_attr(el, "AXSubrole") or ""
    return subrole in ("", "AXStandardWindow")


def _is_file_panel(el: Any) -> bool:
    from astronverse.locator.core.ax_common import ax_attr

    role = ax_attr(el, "AXRole") or ""
    sub = ax_attr(el, "AXSubrole") or ""
    if role == "AXSheet":
        return True
    return role == "AXWindow" and sub in ("AXDialog", "AXSystemDialog")


def _find_file_panel(window: Any) -> Any:
    from astronverse.locator.core.ax_common import ax_attr, ax_children

    if window is None:
        return None
    sheets = ax_attr(window, "AXSheets") or []
    if isinstance(sheets, (list, tuple)):
        for s in sheets:
            if s:
                return s
    q: deque = deque([(window, 0)])
    seen: set[int] = set()
    while q:
        el, depth = q.popleft()
        eid = id(el)
        if eid in seen:
            continue
        seen.add(eid)
        if el is not window and _is_file_panel(el):
            return el
        if depth < 4:
            for child in ax_children(el):
                q.append((child, depth + 1))
    return None


def _find_save_name_field(sheet: Any) -> Any:
    from astronverse.locator.core.ax_common import ax_attr, ax_children

    if sheet is None:
        return None
    fallback = None
    q: deque = deque([(sheet, 0)])
    seen: set[int] = set()
    while q:
        el, depth = q.popleft()
        eid = id(el)
        if eid in seen:
            continue
        seen.add(eid)
        if ax_attr(el, "AXRole") == "AXTextField":
            ident = ax_attr(el, "AXIdentifier") or ""
            if ident == "saveAsNameTextField":
                return el
            if fallback is None:
                fallback = el
        if depth < 12:
            for child in ax_children(el):
                q.append((child, depth + 1))
    return fallback


def _paste_path(path: str) -> None:
    import pyautogui
    import pyperclip

    old = None
    try:
        old = pyperclip.paste()
    except Exception:
        old = None
    try:
        pyautogui.hotkey("command", "shift", "g")
        time.sleep(0.3)
        pyperclip.copy(str(path))
        time.sleep(0.2)
        pyautogui.hotkey("command", "v")
        time.sleep(0.2)
        pyautogui.press("enter")
        time.sleep(0.3)
    finally:
        if old is not None:
            try:
                pyperclip.copy(old)
            except Exception:
                pass


def _confirm_panel(sheet: Any) -> None:
    import pyautogui
    from astronverse.locator.core.ax_common import ax_attr, ax_perform

    btn = ax_attr(sheet, "AXDefaultButton") if sheet else None
    if btn:
        ax_perform(btn)
        return
    pyautogui.press("enter")


def _wait_for_panel(browser_type: str, timeout: float = 10) -> Any:
    start_time = time.time()
    panel = None
    while time.time() - start_time < timeout:
        control = BrowserCore.get_browser_control(browser_type)
        panel = _find_file_panel(control)
        if panel:
            time.sleep(0.5)
            break
        time.sleep(0.1)
    return panel


def _split_origin_name(origin_name: str) -> tuple:
    if origin_name.find(".") != -1:
        name = origin_name.split(".")[0]
        suffix = origin_name.rsplit(".", 1)[-1]
        if not suffix.isalpha():
            name = origin_name
            suffix = ""
    else:
        name = origin_name
        suffix = ""
    return name, suffix


class BrowserCore:
    @staticmethod
    def get_browser_path(browser_type: str) -> str:
        """获取浏览器绝对地址（.app 路径）"""
        app_name = BROWSER_MAC_APP_NAME.get(browser_type, "")
        if not app_name:
            return ""
        from astronverse.software.software import Software

        return Software.get_app_path(app_name)

    @staticmethod
    def browser_top_and_max(control):
        if control is None:
            return
        from astronverse.locator.core.ax_common import ax_set_attr, pid_of, raise_window

        raise_window(control, pid_of(control))
        vf = _visible_frame_ax()
        if not vf:
            return
        x, y, w, h = vf
        ax_set_attr(control, "AXPosition", _ax_point(x, y))
        ax_set_attr(control, "AXSize", _ax_size(w, h))

    @staticmethod
    def get_browser_point(browser_type: str) -> Any:
        """获取浏览器网页区域左上角坐标 (top, left)"""
        from astronverse.locator.core.ax_common import ax_attr, ax_children, ax_rect

        base_ctrl = BrowserCore.get_browser_control(browser_type)
        if not base_ctrl:
            return None

        q: deque = deque([(base_ctrl, 0)])
        seen: set[int] = set()
        while q:
            el, depth = q.popleft()
            eid = id(el)
            if eid in seen:
                continue
            seen.add(eid)
            if ax_attr(el, "AXRole") == "AXWebArea":
                bounding_rect = ax_rect(el)
                if bounding_rect and (bounding_rect.right - bounding_rect.left) > 0:
                    if (bounding_rect.bottom - bounding_rect.top) > 0:
                        return bounding_rect.top, bounding_rect.left
            if depth < 12:
                for child in ax_children(el):
                    q.append((child, depth + 1))
        return None

    @staticmethod
    def get_browser_control(browser_type: str) -> Any:
        """获取浏览器的控制器（前台标准窗口 AX 元素）"""
        from astronverse.locator.core.ax_common import app_element, app_windows, ax_attr, find_apps

        bundle_id = BROWSER_MAC_BUNDLE_ID.get(browser_type, "")
        app_name = BROWSER_MAC_APP_NAME.get(browser_type, "")
        if not bundle_id and not app_name:
            return None
        pids = find_apps(app_name, bundle_id or None)
        if not pids:
            return None
        for pid in pids:
            app_el = app_element(pid)
            windows = app_windows(app_el)
            if not windows:
                continue
            standard = [w for w in windows if _is_standard_window(w)]
            if not standard:
                standard = [w for w in windows if ax_attr(w, "AXRole") == "AXWindow"] or list(windows)
            non_min = [w for w in standard if not ax_attr(w, "AXMinimized")]
            if non_min:
                return non_min[0]
            return standard[0]
        return None

    @staticmethod
    def download_window_operate(**kwargs) -> Any:
        """获取浏览器下载文件另存为窗口。

        Chrome 默认直接下载、不弹窗；仅在开启“下载前询问每个文件的保存位置”
        时才会出现另存为面板（与 Windows 行为一致）。
        """
        from astronverse.locator.core.ax_common import ax_attr, ax_set_attr

        file_name = kwargs.get("file_name")
        browser_type = _browser_type_value(kwargs.get("browser_type"))
        is_wait = kwargs.get("is_wait")
        time_out = kwargs.get("time_out")

        panel = _wait_for_panel(browser_type, timeout=10)
        if not panel:
            raise BaseException(DOWNLOAD_WINDOW_NO_FIND, "未弹出下载窗口")

        edit = _find_save_name_field(panel)
        origin_name = str(ax_attr(edit, "AXValue") or "") if edit else ""
        name, suffix = _split_origin_name(origin_name)
        if kwargs.get("custom_flag"):
            name = file_name
        if suffix:
            dest_path = os.path.join(kwargs.get("save_path"), name + "." + suffix)
        else:
            dest_path = os.path.join(kwargs.get("save_path"), name)

        _paste_path(kwargs.get("save_path") or os.path.dirname(dest_path))
        if edit:
            ax_set_attr(edit, "AXValue", os.path.basename(dest_path))
            ax_set_attr(edit, "AXFocused", True)
        time.sleep(0.2)
        _confirm_panel(panel)

        if is_wait:
            if not (time_out == 0 or time_out == ""):
                try:
                    wait_time_download = int(time_out)
                except Exception:
                    wait_time_download = 60
                while wait_time_download > 0:
                    wait_time_download = wait_time_download - 3
                    if os.path.exists(dest_path):
                        break
                    time.sleep(3)
                if wait_time_download <= 0 and not os.path.exists(dest_path):
                    raise Exception("等待下载完成超时")
        return dest_path

    @staticmethod
    def upload_window_operate(**kwargs) -> Any:
        """获取浏览器上传文件窗口操作"""
        browser_type = _browser_type_value(kwargs.get("browser_type"))
        upload_path = kwargs.get("upload_path")

        panel = _wait_for_panel(browser_type, timeout=10)
        if not panel:
            raise BaseException(UPLOAD_WINDOW_NO_FIND, "未弹出上传窗口")

        dest_path = ""
        if isinstance(upload_path, str) and upload_path.find("|") != -1:
            upload_path = upload_path.split("|")
        if isinstance(upload_path, list):
            dest_path = upload_path[0].strip() if upload_path else ""
        else:
            dest_path = upload_path

        _paste_path(dest_path)
        _confirm_panel(panel)
        return dest_path
