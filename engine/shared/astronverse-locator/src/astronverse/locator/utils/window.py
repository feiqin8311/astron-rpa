import ctypes
import sys
from dataclasses import dataclass
from typing import Any, Optional, Union

import pyautogui
from astronverse.baseline.logger.logger import logger
from astronverse.locator import PickerType, Rect
from astronverse.locator.utils.process import get_process_name

if sys.platform == "win32":
    import pygetwindow
    import uiautomation as auto
    import win32com
    import win32com.client
    import win32con
    import win32gui
    import win32process
    from pygetwindow._pygetwindow_win import Win32Window, isWindowVisible
    from uiautomation import Control, ControlFromHandle
else:
    Control = Any
    ControlFromHandle = Any
    Win32Window = Any
    isWindowVisible = Any  # noqa: N816
    auto = None


@dataclass
class DarwinWindowControl:
    NativeWindowHandle: int
    BoundingRectangle: Rect
    Name: str = ""
    ClassName: str = ""
    ProcessId: int = 0


def darwin_cls_is_ax(cls_name: str) -> bool:
    """Win32 class names have no AX equivalent; AX roles/subroles start with AX."""
    return bool(cls_name) and str(cls_name).startswith("AX")


def darwin_window_name_matches(handler_name: str, name: str) -> bool:
    if not name:
        return True
    return (handler_name or "") == name


def darwin_window_cls_matches(handler_cls: str, cls_name: str) -> bool:
    if not cls_name:
        return True
    if not darwin_cls_is_ax(cls_name):
        return True
    return (handler_cls or "") == cls_name


def _cg_val(window_info: dict, key: str, default: Any = None) -> Any:
    try:
        import Quartz

        const = getattr(Quartz, key, None)
        if const is not None:
            val = window_info.get(const)
            if val is not None:
                return val
    except Exception:
        pass
    return window_info.get(key, default)


def darwin_control_from_handle(handle: int) -> Optional[DarwinWindowControl]:
    """Build DarwinWindowControl from a CGWindowNumber."""
    if sys.platform != "darwin" or not handle:
        return None
    import Quartz

    options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    window_list = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []
    matched = None
    for w in window_list:
        win_num = _cg_val(w, "kCGWindowNumber", 0)
        if int(win_num or 0) == int(handle):
            matched = w
            break
    if matched is None:
        return None
    bounds = _cg_val(matched, "kCGWindowBounds", {}) or {}
    x = int(bounds.get("X", bounds.get("x", 0)))
    y = int(bounds.get("Y", bounds.get("y", 0)))
    w_val = int(bounds.get("Width", bounds.get("width", 0)))
    h_val = int(bounds.get("Height", bounds.get("height", 0)))
    pid = int(_cg_val(matched, "kCGWindowOwnerPID", 0) or 0)
    name = str(_cg_val(matched, "kCGWindowName", "") or "")
    owner = str(_cg_val(matched, "kCGWindowOwnerName", "") or "")
    cls_name = ""
    try:
        from astronverse.locator.core import ax_common

        app_el = ax_common.app_element(pid)
        for win in ax_common.app_windows(app_el):
            title = str(ax_common.ax_attr(win, "AXTitle") or "")
            rect = ax_common.ax_rect(win)
            if (title and title == name) or (rect is not None and abs(rect.left - x) <= 2 and abs(rect.top - y) <= 2):
                if title:
                    name = title
                cls_name = str(ax_common.ax_attr(win, "AXSubrole") or ax_common.ax_attr(win, "AXRole") or "")
                break
    except Exception:
        pass
    return DarwinWindowControl(
        NativeWindowHandle=int(handle),
        BoundingRectangle=Rect(x, y, x + w_val, y + h_val),
        Name=name,
        ClassName=cls_name or owner,
        ProcessId=pid,
    )


def _darwin_find_matches(cls_name: str, name: str, app_name: Optional[str] = None) -> list[tuple]:
    handles = find_app_handles(app_name or "")
    match_list = []
    for handle in handles:
        ctrl = darwin_control_from_handle(handle)
        if not ctrl:
            continue
        handler_name = ctrl.Name or ""
        handler_class_name = ctrl.ClassName or ""
        if not darwin_window_name_matches(handler_name, name):
            continue
        if not darwin_window_cls_matches(handler_class_name, cls_name):
            continue
        match_list.append(
            (
                handle,
                handler_name,
                handler_class_name,
                True,
                darwin_cls_is_ax(cls_name) and handler_class_name == cls_name,
            )
        )
    return match_list


def _darwin_pick_handle(match_list: list[tuple], is_desktop_win: bool = False) -> int:
    if not match_list:
        return 0
    if is_desktop_win and len(match_list) > 1:
        cls_match = [item for item in match_list if item[4]]
        if cls_match:
            match_list = cls_match
    match_list = sorted(match_list, key=lambda item: len(item[1]), reverse=True)
    return match_list[0][0]


def _darwin_pick_handles(match_list: list[tuple], is_desktop_win: bool = False) -> list[int]:
    if not match_list:
        return []
    result = []
    if is_desktop_win and len(match_list) > 1:
        cls_match = [item for item in match_list if item[4]]
        if cls_match:
            result.append(cls_match[0][0])
    match_list = sorted(match_list, key=lambda item: len(item[1]), reverse=True)
    target_name = match_list[0][1]
    for item in match_list:
        if item[1] == target_name and item[0] not in result:
            result.append(item[0])
    return result


def _darwin_show_desktop_rect(rect: Rect, desktop_handle=None):
    import os

    from astronverse.locator.core import ax_common

    self_pid = os.getpid()
    for handle in find_app_handles(""):
        if desktop_handle and handle == desktop_handle:
            continue
        if handle in DESKTOP_WINDOW_HANDLES:
            continue
        ctrl = darwin_control_from_handle(handle)
        if not ctrl:
            continue
        if ctrl.ProcessId == self_pid:
            continue
        if is_desktop_by_handle(handle, ctrl):
            continue
        win_rect = ctrl.BoundingRectangle
        if not win_rect or not win_rect.overlaps(rect):
            continue
        app_el = ax_common.app_element(ctrl.ProcessId)
        for win in ax_common.app_windows(app_el):
            wr = ax_common.ax_rect(win)
            if wr and wr.overlaps(rect):
                ax_common.ax_set_attr(win, "AXMinimized", True)


def get_screen_scale_rate_new():
    """
    根据dpi，获取屏幕的缩放比例
    :return:
    """
    if sys.platform == "win32":
        user32 = ctypes.windll.user32
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        sys_dpi = user32.GetDpiForSystem()
        return round(sys_dpi / 96, 2)
    elif sys.platform == "darwin":
        import AppKit

        screen = AppKit.NSScreen.mainScreen()
        if screen:
            return float(screen.backingScaleFactor())
        return 1.0
    return 1.0


def get_screen_scale_rate_runtime():
    """
    实时根据主屏dpi获取到主屏的缩放比
    :return:
    """
    if sys.platform == "win32":
        from ctypes import Structure, c_long, c_uint, pointer, windll

        import win32con

        try:

            class RECT(Structure):
                _fields_ = [
                    ("left", c_long),
                    ("top", c_long),
                    ("right", c_long),
                    ("bottom", c_long),
                ]

            rect = RECT()
            user32 = windll.user32
            rectp = pointer(rect)
            hmonitor = user32.MonitorFromRect(rectp, win32con.MONITOR_DEFAULTTOPRIMARY)
            dpix = c_uint()
            dpiy = c_uint()
            p_dpix = pointer(dpix)
            p_dpiy = pointer(dpiy)
            res = windll.shcore.GetDpiForMonitor(hmonitor, 0, p_dpix, p_dpiy)
            if res != 0:
                return get_screen_scale_rate_new()
            return round(p_dpix.contents.value / 96, 2)
        except Exception:
            return get_screen_scale_rate_new()
    elif sys.platform == "darwin":
        # Note on macOS: pyautogui / Quartz event coordinates are in logical points,
        # so the effective scale for coordinate conversion is 1.0.
        # Backing scale factor (e.g. 2.0 for Retina) can be read via get_screen_scale_rate_new()
        # or get_screen_backing_scale_factor().
        return 1.0
    return 1.0


def get_screen_backing_scale_factor() -> float:
    """获取 macOS 屏幕的物理/像素 backingScaleFactor (Retina 屏通常为 2.0)"""
    if sys.platform == "darwin":
        import AppKit

        screen = AppKit.NSScreen.mainScreen()
        if screen:
            return float(screen.backingScaleFactor())
    return 1.0


def get_system_display_size() -> tuple[int, int]:
    if sys.platform == "win32":
        user32 = ctypes.windll.user32
        width = user32.GetSystemMetrics(0)
        height = user32.GetSystemMetrics(1)
        return width, height
    sz = pyautogui.size()
    return sz.width, sz.height


def validate_ui_element_rect(left, top, right, bottom, max_width=2000, max_height=1200):
    """
    校验界面元素矩形框的合理性（坐标系原点在左上角）
    新增校验规则：
    1. 坐标不允许为负数[6,7](@ref)
    2. 宽度不超过max_width（默认2000px，基于4K屏的1/2宽度）
    3. 高度不超过max_height（默认1200px，基于4K屏的1/2高度）
    """
    try:
        # 类型校验（支持int/float类型）
        if not all(isinstance(v, (int, float)) for v in [left, top, right, bottom]):
            return False

        # 坐标有效性校验
        if any(v < 0 for v in [left, top, right, bottom]):
            return False

        # 逻辑位置校验
        if left >= right or top >= bottom:
            return False

        # 计算实际尺寸
        width = right - left
        height = bottom - top

        # 非退化校验（避免零尺寸元素）
        if width <= 0 or height <= 0:
            return False

        # 最大尺寸校验（基于常见界面元素尺寸规范[6,8](@ref)）
        if width > max_width or height > max_height:
            return False

        return True
    except TypeError:
        # 处理非数值类型输入（如字符串）
        return False


def validate_window_rect(left, top, right, bottom):
    max_width = pyautogui.size().width
    max_height = pyautogui.size().height
    try:
        # 类型校验（支持int/float类型）
        if not all(isinstance(v, (int, float)) for v in [left, top, right, bottom]):
            return False

        # 坐标有效性校验
        if any(v < 0 for v in [left, top, right, bottom]):
            return False

        # 逻辑位置校验
        if left >= right or top >= bottom:
            return False

        # 计算实际尺寸
        width = right - left
        height = bottom - top

        # 非退化校验（避免零尺寸元素）
        if width <= 0 or height <= 0:
            return False

        # 最大尺寸校验（基于常见界面元素尺寸规范[6,8](@ref)）
        if width > max_width or height > max_height:
            return False

        return True
    except TypeError:
        # 处理非数值类型输入（如字符串）
        return False


def is_desktop_by_cls_and_name(cls_name: str, name: str) -> bool:
    """
    判断是否是桌面窗口
    注意桌面窗口随时都会变动，cls和name都会变动
    """
    # 常见的桌面窗口类型
    desktop_types = [
        # Windows 10/11 桌面窗口
        ("WorkerW", ""),  # 桌面背景窗口
        ("Progman", "Program Manager"),  # 主桌面窗口
        # Windows 7 桌面窗口
        ("Shell_TrayWnd", "开始"),  # 开始菜单
        ("Shell_TrayWnd", "任务栏"),  # 任务栏
        # 其他可能的桌面窗口
        ("Shell_TrayWnd", ""),  # 空名称的任务栏
        ("WorkerW", "Program Manager"),  # 某些版本的桌面窗口
        ("Finder", "Desktop"),
        ("AXDesktop", ""),
    ]

    return (cls_name, name) in desktop_types


def is_desktop_by_handle(handle, ctrl: Control) -> bool:
    """
    判断是否是桌面窗口
    """
    if sys.platform == "win32":
        if not ctrl or win32gui.GetParent(handle) != 0:
            return False
        return is_desktop_by_cls_and_name(ctrl.ClassName, ctrl.Name)
    elif sys.platform == "darwin":
        if not ctrl:
            return False
        return is_desktop_by_cls_and_name(getattr(ctrl, "ClassName", ""), getattr(ctrl, "Name", ""))
    return False


RPA_HIGHLIGHT_PROCESSES = []
RPA_HIGHLIGHT_CHECKED = False


def is_rpa_highlight(ctrl: Control) -> bool:
    """判断control是否是高亮窗口"""
    if sys.platform != "win32":
        return False
    global RPA_HIGHLIGHT_CHECKED, RPA_HIGHLIGHT_PROCESSES
    if not RPA_HIGHLIGHT_CHECKED:
        RPA_HIGHLIGHT_CHECKED = True
        all_windows = pygetwindow.getWindowsWithTitle("")
        for window in all_windows:
            win_control = ControlFromHandle(window._hWnd)
            if getattr(win_control, "AutomationId", None) == "HighlightForm":
                RPA_HIGHLIGHT_PROCESSES.append(win_control.ProcessId)
    if ctrl and getattr(ctrl, "ProcessId", None) in RPA_HIGHLIGHT_PROCESSES:
        return True
    return False


def get_pid_by_handle(handle: int):
    """
    从窗口对象中获取程序pid
    """
    if sys.platform == "win32":
        _, proc_pid = win32process.GetWindowThreadProcessId(handle)
        return proc_pid
    elif sys.platform == "darwin":
        import Quartz

        options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
        window_list = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []
        for w in window_list:
            win_num = w.get(Quartz.kCGWindowNumber) if hasattr(Quartz, "kCGWindowNumber") else w.get("kCGWindowNumber")
            if win_num is None:
                win_num = w.get("kCGWindowNumber")
            if win_num == handle:
                pid = (
                    w.get(Quartz.kCGWindowOwnerPID)
                    if hasattr(Quartz, "kCGWindowOwnerPID")
                    else w.get("kCGWindowOwnerPID")
                )
                if pid is None:
                    pid = w.get("kCGWindowOwnerPID", 0)
                return int(pid or 0)
        return 0
    raise NotImplementedError("get_pid_by_handle is not supported on this platform yet")


def find_app_handles(app: str) -> list:
    """
    获取指定app所有可视窗口，过滤掉cmd命令
    """
    if sys.platform == "win32":
        handles = []
        # 获取所有的窗口并遍历
        # logger.info(f"获取窗口列表: {app}")
        if app == "iexplore":
            ie_win = auto.WindowControl(searchDepth=1, ClassName="IEFrame")
            return [ie_win.NativeWindowHandle]
        for window in pygetwindow.getWindowsWithTitle(""):
            try:
                # logger.info(f"窗口标题: {window.title}")
                hwnd = window._hWnd
                pid = get_pid_by_handle(handle=hwnd)
                if not pid:
                    continue

                app_name = get_process_name(pid)
                if app_name == "cmd":
                    # 处理命令行窗口
                    if app not in ["cmd", "conhost", "powershell", "bash"]:
                        continue
                elif app_name != app:
                    # 普通窗口名称匹配
                    continue

                if not isWindowVisible(hwnd):
                    continue

                handles.append(hwnd)
            except Exception as e:
                logger.error("获取窗口失败: {}".format(e))
                continue
        return handles
    elif sys.platform == "darwin":
        import Quartz

        options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
        window_list = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []
        handles = []
        for w in window_list:
            layer = w.get(Quartz.kCGWindowLayer) if hasattr(Quartz, "kCGWindowLayer") else w.get("kCGWindowLayer")
            if layer is None:
                layer = w.get("kCGWindowLayer", 0)
            if layer != 0:
                continue

            owner = str(
                (
                    w.get(Quartz.kCGWindowOwnerName)
                    if hasattr(Quartz, "kCGWindowOwnerName")
                    else w.get("kCGWindowOwnerName")
                )
                or ""
            )
            if app.lower() in owner.lower() or owner.lower() in app.lower():
                win_num = (
                    w.get(Quartz.kCGWindowNumber) if hasattr(Quartz, "kCGWindowNumber") else w.get("kCGWindowNumber", 0)
                )
                if win_num is None:
                    win_num = w.get("kCGWindowNumber", 0)
                handles.append(int(win_num))
        return handles
    raise NotImplementedError("find_app_handles is not supported on this platform yet")


DESKTOP_WINDOW_HANDLES = []


def show_desktop_rect(rect: Rect, desktop_handle=None):
    if sys.platform == "darwin":
        _darwin_show_desktop_rect(rect, desktop_handle)
        return
    if sys.platform != "win32":
        raise NotImplementedError("show_desktop_rect is not supported on this platform yet")
    all_windows = pygetwindow.getWindowsWithTitle("")
    for window in all_windows:
        win_control = ControlFromHandle(window._hWnd)

        # rpa高亮窗口，忽略
        if is_rpa_highlight(win_control):
            continue

        # 已经最小化了，忽略
        if window.isMinimized:
            continue

        # 桌面窗口不能最小化，最小化导致桌面被隐藏
        if (desktop_handle and window._hWnd == desktop_handle) or window._hWnd in DESKTOP_WINDOW_HANDLES:
            continue

        # 窗口挡住桌面元素，最小化窗口
        win_rect = Rect(window.left, window.top, window.right, window.bottom)
        if win_rect.overlaps(rect):
            window.minimize()


def find_window(cls_name: str, name: str, app_name: Optional[str] = None) -> int:
    if sys.platform == "darwin":
        return _darwin_pick_handle(
            _darwin_find_matches(cls_name, name, app_name), is_desktop_by_cls_and_name(cls_name, name)
        )
    if sys.platform != "win32":
        raise NotImplementedError("find_window is not supported on this platform yet")
    global DESKTOP_WINDOW_HANDLES
    is_desktop_win = is_desktop_by_cls_and_name(cls_name, name)

    # 通过app_name(进程名称)获取所有的顶层窗口, 并过滤cls_name和name
    match_list = []
    for handle in find_app_handles(app_name):
        handler_ctrl = ControlFromHandle(handle)
        handler_name = handler_ctrl.Name
        handler_class_name = handler_ctrl.ClassName

        # 使用是否是桌面元素过滤(桌面窗口的特殊性,不能直接通过cls过滤)
        match_desktop_win = is_desktop_by_cls_and_name(handler_class_name, handler_name)
        if match_desktop_win and handle not in DESKTOP_WINDOW_HANDLES:
            # 记录所有的桌面的handle
            DESKTOP_WINDOW_HANDLES.append(handle)
        if is_desktop_win and match_desktop_win:
            match_list.append(
                (
                    handle,
                    handler_name,
                    handler_class_name,
                    win32gui.GetParent(handle) == 0,
                    cls_name == handler_class_name,
                )
            )
            continue

        # 使用cls过滤
        if handler_class_name != cls_name:
            continue

        # 使用name过滤
        if handler_name != name:
            continue
        match_list.append(
            (
                handle,
                handler_name,
                handler_class_name,
                win32gui.GetParent(handle) == 0,
                True,
            )
        )

    # 优先检查win32gui.GetParent(handle) == 0，如果都为空就剔除这个优先选项
    match_list_lv2 = [item for item in match_list if item[3]]
    logger.info(f"优先检查win32gui.GetParent(handle) == 0，如果都为空就剔除这个优先选项: {match_list_lv2}")
    if not match_list_lv2:
        match_list_lv2 = match_list

    # 优先选择窗口cls一致的handle，如果有多个桌面窗口的情况
    if is_desktop_win and len(match_list_lv2) > 1:
        match_list_lv2 = [item for item in match_list_lv2 if item[4]]
        logger.info(f"优先选择窗口cls一致的handle: {match_list_lv2}")
        if match_list_lv2:
            return match_list_lv2[0][0]

    # 优先选择窗口name最长的handle
    if match_list_lv2:
        match_list_lv2.sort(key=lambda item: len(item[1]))
        logger.info(f"优先选择窗口name最长的handle: {match_list_lv2}")
        return match_list_lv2[0][0]

    # 如果都没有，则返回0
    return 0


def find_window_handles_list(cls_name: str, name: str, app_name: Optional[str] = None, picker_type=None) -> list[int]:
    """
    获取指定窗口的handle列表，包含cls完全一致的handle和窗口name最长并且一致的handle

    :param cls_name: 窗口类名
    :param name: 窗口名称
    :param app_name: 应用程序名称
    :return: handle列表，包含cls完全一致的handle和窗口name最长并且一致的handle
    """
    if sys.platform == "darwin":
        if picker_type == PickerType.WINDOW.value:
            return [find_window(cls_name, name, app_name)]
        return _darwin_pick_handles(
            _darwin_find_matches(cls_name, name, app_name), is_desktop_by_cls_and_name(cls_name, name)
        )
    if sys.platform != "win32":
        raise NotImplementedError("find_window_handles_list is not supported on this platform yet")
    if picker_type == PickerType.WINDOW.value:
        return [find_window(cls_name, name, app_name)]
    global DESKTOP_WINDOW_HANDLES
    is_desktop_win = is_desktop_by_cls_and_name(cls_name, name)

    # 通过app_name(进程名称)获取所有的顶层窗口, 并过滤cls_name和name
    match_list = []
    for handle in find_app_handles(app_name):
        handler_ctrl = ControlFromHandle(handle)
        handler_name = handler_ctrl.Name
        handler_class_name = handler_ctrl.ClassName

        # 使用是否是桌面元素过滤(桌面窗口的特殊性,不能直接通过cls过滤)
        match_desktop_win = is_desktop_by_cls_and_name(handler_class_name, handler_name)
        if match_desktop_win and handle not in DESKTOP_WINDOW_HANDLES:
            # 记录所有的桌面的handle
            DESKTOP_WINDOW_HANDLES.append(handle)
        if is_desktop_win and match_desktop_win:
            match_list.append(
                (
                    handle,
                    handler_name,
                    handler_class_name,
                    win32gui.GetParent(handle) == 0,
                    cls_name == handler_class_name,
                )
            )
            continue

        # 使用cls过滤
        if handler_class_name != cls_name:
            continue

        # 使用name过滤
        if handler_name != name:
            continue
        match_list.append(
            (
                handle,
                handler_name,
                handler_class_name,
                win32gui.GetParent(handle) == 0,
                True,
            )
        )

    # 优先检查win32gui.GetParent(handle) == 0，如果都为空就剔除这个优先选项
    match_list_lv2 = [item for item in match_list if item[3]]
    logger.info(f"优先检查win32gui.GetParent(handle) == 0，如果都为空就剔除这个优先选项: {match_list_lv2}")
    if not match_list_lv2:
        match_list_lv2 = match_list

    result_handles = []

    # 获取cls完全一致的handle
    if is_desktop_win and len(match_list_lv2) > 1:
        cls_match_list = [item for item in match_list_lv2 if item[4]]
        logger.info(f"cls完全一致的handle: {cls_match_list}")
        if cls_match_list:
            result_handles.append(cls_match_list[0][0])

    # 获取窗口name最长并且一致的handle
    if match_list_lv2:
        # 按name长度排序，取最长的
        match_list_lv2.sort(key=lambda item: len(item[1]), reverse=True)
        logger.info(f"窗口name最长并且一致的handle: {match_list_lv2}")

        # 获取第一个匹配项的name作为基准
        target_name = match_list_lv2[0][1]
        logger.info(f"目标窗口名称: {target_name}")

        # 遍历match_list_lv2，获取跟match_list_lv2[0][1]同名的所有handle
        for item in match_list_lv2:
            handle = item[0]
            handler_name = item[1]

            # 如果窗口名称与目标名称相同，且handle不重复，则添加到结果中
            if handler_name == target_name and handle not in result_handles:
                result_handles.append(handle)
                logger.info(f"添加同名handle: {handle}, 窗口名称: {handler_name}")

    # 这里筛选桌面窗口

    return result_handles


def find_window_by_enum(cls: str, name: str, app_name: Optional[str] = None) -> int:
    """
    通过枚举窗口 classname 和 name属性获得窗口，返回如果是0则窗口不存在
    与find_window的区别是使用EnumWindows枚举所有窗口，能找到更多窗口
    :param cls: 控件className
    :param name: 控件name
    :param app_name: 程序名字
    :return:
    """
    if sys.platform == "darwin":
        return find_window(cls, name, app_name)
    if sys.platform != "win32":
        raise NotImplementedError("find_window_by_enum is not supported on this platform yet")

    def get_all_windows_by_enum():
        """通过枚举获取所有窗口句柄"""
        handles = []

        def enum_win(hwnd, result):
            # 通过这种方式获取当前窗口是否是顶层窗口
            if not isWindowVisible(hwnd):
                return
            handles.append(hwnd)

        win32gui.EnumWindows(enum_win, handles)
        return handles

    # 获取枚举的窗口句柄列表
    enum_handles = get_all_windows_by_enum()
    logger.info(f"枚举的窗口句柄列表: {enum_handles}")
    # 如果指定了app_name，也加上find_app_handles的结果，确保不遗漏
    if app_name:
        try:
            app_handles = find_app_handles(app_name)
            # 合并句柄列表，去重
            all_handles = list(set(enum_handles + app_handles))
            logger.info(f"合并后的窗口句柄列表: {all_handles}")
        except Exception:
            all_handles = enum_handles
    else:
        all_handles = enum_handles

    # 复用find_window的匹配逻辑
    global DESKTOP_WINDOW_HANDLES
    is_desktop_win = is_desktop_by_cls_and_name(cls, name)

    match_list = []
    for handle in all_handles:
        handler_ctrl = ControlFromHandle(handle)
        if not handler_ctrl:
            continue

        handler_name = handler_ctrl.Name or ""
        handler_class_name = handler_ctrl.ClassName or ""

        # 使用是否是桌面元素过滤(桌面窗口的特殊性,不能直接通过cls过滤)
        match_desktop_win = is_desktop_by_cls_and_name(handler_class_name, handler_name)
        if match_desktop_win and handle not in DESKTOP_WINDOW_HANDLES:
            DESKTOP_WINDOW_HANDLES.append(handle)
        if is_desktop_win and match_desktop_win:
            match_list.append(
                (
                    handle,
                    handler_name,
                    handler_class_name,
                    win32gui.GetParent(handle) == 0,
                    cls == handler_class_name,
                )
            )
            continue

        # 使用cls过滤
        if handler_class_name != cls:
            continue

        # 使用name过滤 (支持双向模糊匹配)
        if handler_name != name:
            continue
        match_list.append(
            (
                handle,
                handler_name,
                handler_class_name,
                win32gui.GetParent(handle) == 0,
                True,
            )
        )

    # 复用find_window的优先级选择逻辑
    match_list_lv2 = [item for item in match_list if item[3]]
    logger.info(f"测试一开始的: {match_list_lv2}")
    if not match_list_lv2:
        match_list_lv2 = match_list

    if is_desktop_win and len(match_list_lv2) > 1:
        match_list_lv2 = [item for item in match_list_lv2 if item[4]]
        if match_list_lv2:
            return match_list_lv2[0][0]

    if match_list_lv2:
        match_list_lv2.sort(key=lambda item: len(item[1]), reverse=True)
        logger.info(f"优先选择窗口cls一致的handle: {match_list_lv2}")
        return match_list_lv2[0][0]

    return 0


def find_window_by_enum_list(cls: str, name: str, app_name: Optional[str] = None, picker_type=None):
    """
    通过枚举窗口 classname 和 name属性获得窗口，返回如果是0则窗口不存在
    与find_window的区别是使用EnumWindows枚举所有窗口，能找到更多窗口
    """
    if sys.platform == "darwin":
        return find_window_handles_list(cls, name, app_name, picker_type)
    if sys.platform != "win32":
        raise NotImplementedError("find_window_by_enum_list is not supported on this platform yet")
    if picker_type == PickerType.WINDOW.value:
        return [find_window_by_enum(cls, name, app_name)]

    def get_all_windows_by_enum():
        """通过枚举获取所有窗口句柄"""
        handles = []

        def enum_win(hwnd, result):
            # 通过这种方式获取当前窗口是否是顶层窗口
            if not isWindowVisible(hwnd):
                return
            handles.append(hwnd)

        win32gui.EnumWindows(enum_win, handles)
        return handles

    # 获取枚举的窗口句柄列表
    enum_handles = get_all_windows_by_enum()
    logger.info(f"枚举的窗口句柄列表: {enum_handles}")
    # 如果指定了app_name，也加上find_app_handles的结果，确保不遗漏
    if app_name:
        try:
            app_handles = find_app_handles(app_name)
            # 合并句柄列表，去重
            all_handles = list(set(enum_handles + app_handles))
            logger.info(f"合并后的窗口句柄列表: {all_handles}")
        except Exception:
            all_handles = enum_handles
    else:
        all_handles = enum_handles

    # 复用find_window的匹配逻辑
    global DESKTOP_WINDOW_HANDLES
    is_desktop_win = is_desktop_by_cls_and_name(cls, name)

    match_list = []
    for handle in all_handles:
        handler_ctrl = ControlFromHandle(handle)
        if not handler_ctrl:
            continue

        handler_name = handler_ctrl.Name or ""
        handler_class_name = handler_ctrl.ClassName or ""

        # 使用是否是桌面元素过滤(桌面窗口的特殊性,不能直接通过cls过滤)
        match_desktop_win = is_desktop_by_cls_and_name(handler_class_name, handler_name)
        if match_desktop_win and handle not in DESKTOP_WINDOW_HANDLES:
            DESKTOP_WINDOW_HANDLES.append(handle)
        if is_desktop_win and match_desktop_win:
            match_list.append(
                (
                    handle,
                    handler_name,
                    handler_class_name,
                    win32gui.GetParent(handle) == 0,
                    cls == handler_class_name,
                )
            )
            continue

        # 使用cls过滤
        if handler_class_name != cls:
            continue

        # 使用name过滤 (支持双向模糊匹配)
        if handler_name != name:
            continue
        match_list.append(
            (
                handle,
                handler_name,
                handler_class_name,
                win32gui.GetParent(handle) == 0,
                True,
            )
        )

    # 复用find_window的优先级选择逻辑
    match_list_lv2 = [item for item in match_list if item[3]]
    if not match_list_lv2:
        match_list_lv2 = match_list
    result_handles = []

    # 获取cls完全一致的handle
    if is_desktop_win and len(match_list_lv2) > 1:
        cls_match_list = [item for item in match_list_lv2 if item[4]]
        logger.info(f"cls完全一致的handle: {cls_match_list}")
        if cls_match_list:
            result_handles.append(cls_match_list[0][0])

    # 获取窗口name最长并且一致的handle
    if match_list_lv2:
        # 按name长度排序，取最长的
        match_list_lv2.sort(key=lambda item: len(item[1]), reverse=True)
        logger.info(f"窗口name最长并且一致的handle: {match_list_lv2}")

        # 获取第一个匹配项的name作为基准
        target_name = match_list_lv2[0][1]
        logger.info(f"目标窗口名称: {target_name}")

        # 遍历match_list_lv2，获取跟match_list_lv2[0][1]同名的所有handle
        for item in match_list_lv2:
            handle = item[0]
            handler_name = item[1]

            # 如果窗口名称与目标名称相同，且handle不重复，则添加到结果中
            if handler_name == target_name and handle not in result_handles:
                result_handles.append(handle)
                logger.info(f"添加同名handle: {handle}, 窗口名称: {handler_name}")

    return result_handles


def top_window(handle: int, ctrl: Control):
    if sys.platform == "win32":
        # 快速结束:桌面窗口不需要置顶
        if is_desktop_by_handle(handle, ctrl):
            return

        # 快速结束:IE判断需要添加焦点
        if ctrl and ctrl.ClassName == "IEFrame":
            ct = None
            root_control = auto.GetRootControl()
            for control, _ in auto.WalkControl(root_control, includeTop=True, maxDepth=1):
                if control.ClassName == "IEFrame":
                    ct = control
                    break
            if ct:
                ct.SetActive()
            return

        # 恢复和激活窗口
        try:
            cur_window = Win32Window(handle)
            if cur_window.isMinimized:
                cur_window.restore()
                cur_window.activate()
        except Exception:
            pass

        # 置顶
        if win32gui.IsIconic(handle):
            win32gui.ShowWindow(handle, win32con.SW_NORMAL)
        else:
            if ctrl and getattr(ctrl, "ClassName", "") == "SAP_FRONTEND_SESSION":
                return
            # 结合键盘事件
            shell = win32com.client.Dispatch("WScript.Shell")
            shell.SendKeys("%")
            win32gui.SetForegroundWindow(handle)
    elif sys.platform == "darwin":
        if is_desktop_by_handle(handle, ctrl):
            return
        pid = getattr(ctrl, "ProcessId", 0) if ctrl else 0
        if not pid and handle:
            pid = get_pid_by_handle(handle)
        from astronverse.locator.core import ax_common

        win_el = None
        name = getattr(ctrl, "Name", "") if ctrl else ""
        rect = getattr(ctrl, "BoundingRectangle", None) if ctrl else None
        if pid:
            app_el = ax_common.app_element(pid)
            for win in ax_common.app_windows(app_el):
                title = str(ax_common.ax_attr(win, "AXTitle") or "")
                wr = ax_common.ax_rect(win)
                if name and title == name:
                    win_el = win
                    break
                if (
                    rect is not None
                    and wr is not None
                    and abs(wr.left - rect.left) <= 2
                    and abs(wr.top - rect.top) <= 2
                ):
                    win_el = win
                    break
            if win_el is None:
                wins = ax_common.app_windows(app_el)
                win_el = wins[0] if wins else None
        if win_el is not None:
            ax_common.raise_window(win_el, pid)
            return
        app = ax_common.running_app(pid) if pid else None
        if app:
            from AppKit import NSApplicationActivateIgnoringOtherApps

            app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
            return
        raise NotImplementedError("top_window could not activate the target window on macOS")
    else:
        raise NotImplementedError("top_window is not supported on this platform yet")


def top_browser(
    handle: Union[int, str] = 0,
    ctrl: Any = None,
    app_name: Optional[str] = None,
    **kwargs: Any,
) -> Any:
    if sys.platform == "win32":
        # 快速结束:桌面窗口不需要置顶
        if is_desktop_by_handle(handle, ctrl):
            return

        # 快速结束:IE判断需要添加焦点
        if ctrl and ctrl.ClassName == "IEFrame":
            ct = None
            root_control = auto.GetRootControl()
            for control, _ in auto.WalkControl(root_control, includeTop=True, maxDepth=1):
                if control.ClassName == "IEFrame":
                    ct = control
                    break
            if ct:
                ct.SetActive()
            return

        # 恢复和激活窗口
        try:
            cur_window = Win32Window(handle)
            if cur_window.isMinimized:
                cur_window.restore()
                cur_window.activate()
        except Exception:
            pass

        # 置顶
        if win32gui.IsIconic(handle):
            win32gui.ShowWindow(handle, win32con.SW_NORMAL)
        else:
            win32gui.SetWindowPos(
                handle,
                win32con.HWND_TOPMOST,
                0,
                0,
                0,
                0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
            )
            win32gui.SetWindowPos(
                handle,
                win32con.HWND_NOTOPMOST,
                0,
                0,
                0,
                0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
            )
        return None
    elif sys.platform == "darwin":
        target_app = app_name or kwargs.get("app")
        if not target_app and isinstance(handle, str):
            target_app = handle
        if not target_app and ctrl is not None:
            target_app = getattr(ctrl, "ClassName", None) or getattr(ctrl, "Name", None)

        macos_browser_ax_ids = {
            "chrome": ("Google Chrome", "com.google.Chrome"),
            "edge": ("Microsoft Edge", "com.microsoft.edgemac"),
            "firefox": ("Firefox", "org.mozilla.firefox"),
            "chromium": ("Chromium", "org.chromium.Chromium"),
        }
        if target_app:
            ax_name, ax_bundle = macos_browser_ax_ids.get(str(target_app).lower(), (str(target_app), None))
            from astronverse.locator.core import ax_common

            for pid in ax_common.find_apps(ax_name, ax_bundle):
                app_el = ax_common.app_element(pid)
                for win in ax_common.app_windows(app_el):
                    if ax_common.ax_attr(win, "AXMinimized"):
                        continue
                    rect = ax_common.ax_rect(win)
                    if rect is None or rect.width() <= 0 or rect.height() <= 0:
                        continue
                    ax_common.raise_window(win, pid)
                    return DarwinWindowControl(
                        NativeWindowHandle=0,
                        BoundingRectangle=rect,
                        Name=str(ax_common.ax_attr(win, "AXTitle") or ""),
                        ClassName=str(ax_name),
                        ProcessId=int(pid),
                    )

        macos_browser_owners_map = {
            "chrome": ["Google Chrome", "Chrome"],
            "edge": ["Microsoft Edge"],
            "firefox": ["Firefox"],
            "chromium": ["Chromium"],
            "360se": ["360安全浏览器", "360se"],
            "360chromex": ["360极速浏览器X", "360ChromeX"],
        }
        default_macos_browser_owners = [
            "Google Chrome",
            "Microsoft Edge",
            "Firefox",
            "Chromium",
            "Chrome",
        ]

        if target_app:
            owners = macos_browser_owners_map.get(str(target_app).lower(), [str(target_app)])
        else:
            owners = default_macos_browser_owners

        import AppKit
        import Quartz

        options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
        window_list = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []

        matched_window = None
        for w in window_list:
            # Check layer 0 only
            layer = w.get(Quartz.kCGWindowLayer) if hasattr(Quartz, "kCGWindowLayer") else w.get("kCGWindowLayer")
            if layer is None:
                layer = w.get("kCGWindowLayer", 0)
            if layer != 0:
                continue

            owner = str(
                (
                    w.get(Quartz.kCGWindowOwnerName)
                    if hasattr(Quartz, "kCGWindowOwnerName")
                    else w.get("kCGWindowOwnerName")
                )
                or ""
            )
            if not any(target.lower() == owner.lower() or target.lower() in owner.lower() for target in owners):
                continue

            bounds = (
                w.get(Quartz.kCGWindowBounds) if hasattr(Quartz, "kCGWindowBounds") else w.get("kCGWindowBounds")
            ) or {}
            width = bounds.get("Width", bounds.get("width", 0))
            height = bounds.get("Height", bounds.get("height", 0))
            if width <= 50 or height <= 50:
                continue

            matched_window = w
            break

        if not matched_window:
            return None

        pid = (
            matched_window.get(Quartz.kCGWindowOwnerPID)
            if hasattr(Quartz, "kCGWindowOwnerPID")
            else matched_window.get("kCGWindowOwnerPID")
        )
        if pid is None:
            pid = matched_window.get("kCGWindowOwnerPID")
        if pid:
            try:
                running_app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
                if running_app:
                    running_app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
            except Exception:
                pass

        bounds = (
            matched_window.get(Quartz.kCGWindowBounds)
            if hasattr(Quartz, "kCGWindowBounds")
            else matched_window.get("kCGWindowBounds")
        ) or {}
        x = int(bounds.get("X", bounds.get("x", 0)))
        y = int(bounds.get("Y", bounds.get("y", 0)))
        w_val = int(bounds.get("Width", bounds.get("width", 0)))
        h_val = int(bounds.get("Height", bounds.get("height", 0)))

        win_num = (
            matched_window.get(Quartz.kCGWindowNumber)
            if hasattr(Quartz, "kCGWindowNumber")
            else matched_window.get("kCGWindowNumber")
        )
        if win_num is None:
            win_num = matched_window.get("kCGWindowNumber", 0)

        win_name = (
            matched_window.get(Quartz.kCGWindowName)
            if hasattr(Quartz, "kCGWindowName")
            else matched_window.get("kCGWindowName")
        )
        if win_name is None:
            win_name = matched_window.get("kCGWindowName", "")

        win_owner = (
            matched_window.get(Quartz.kCGWindowOwnerName)
            if hasattr(Quartz, "kCGWindowOwnerName")
            else matched_window.get("kCGWindowOwnerName")
        )
        if win_owner is None:
            win_owner = matched_window.get("kCGWindowOwnerName", "")

        return DarwinWindowControl(
            NativeWindowHandle=int(win_num or 0),
            BoundingRectangle=Rect(x, y, x + w_val, y + h_val),
            Name=str(win_name or ""),
            ClassName=str(win_owner or ""),
            ProcessId=int(pid or 0),
        )
    else:
        raise NotImplementedError("top_browser is not supported on this platform yet")
