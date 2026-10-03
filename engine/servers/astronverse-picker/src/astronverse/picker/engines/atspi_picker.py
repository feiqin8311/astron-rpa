import copy
from typing import Any, Optional

import pyautogui
from astronverse.locator.core import atspi_common
from astronverse.picker import IElement, PickerType, Rect
from astronverse.picker.logger import logger

TAG_MAP = {
    "push button": "按钮",
    "button": "按钮",
    "entry": "编辑框",
    "text": "编辑框",
    "password text": "编辑框",
    "edit": "编辑框",
    "label": "文本",
    "static": "文本",
    "check box": "复选框",
    "radio button": "单选框",
    "combo box": "下拉框",
    "menu item": "菜单项",
    "menu": "菜单",
    "menu bar": "菜单",
    "table": "表格",
    "table row": "行",
    "table cell": "单元格",
    "image": "图片",
    "link": "链接",
    "page tab": "标签页",
    "page tab list": "标签页",
    "frame": "窗口",
    "window": "窗口",
    "dialog": "窗口",
    "panel": "分组",
    "filler": "分组",
    "scroll pane": "滚动区域",
    "list": "列表",
    "list item": "列表项",
    "slider": "滑块",
    "document web": "网页",
    "document": "网页",
}


def _as_rect(r: Any) -> Optional[Rect]:
    if r is None:
        return None
    if isinstance(r, Rect):
        return r
    return Rect(getattr(r, "left", 0), getattr(r, "top", 0), getattr(r, "right", 0), getattr(r, "bottom", 0))


def _point_xy(point: Any) -> tuple[int, int]:
    x = getattr(point, "x", point[0] if isinstance(point, (list, tuple)) else 0)
    y = getattr(point, "y", point[1] if isinstance(point, (list, tuple)) else 0)
    return int(round(x)), int(round(y))


def screenshot(rect: Rect) -> str:
    if not rect or rect.area() == 0:
        return ""
    w, h = rect.width(), rect.height()
    if w <= 0 or h <= 0:
        return ""
    from astronverse.picker.utils.cv import screenshot as cv_screenshot

    return cv_screenshot(rect)


class ATSPIElement(IElement):
    """Linux AT-SPI 元素封装"""

    def __init__(self, control: Any = None, element: Any = None):
        self.control = control if control is not None else element
        self.__index: Optional[int] = None
        self.__rect: Optional[Rect] = None
        self.__tag: Optional[str] = None

    def rect(self) -> Rect:
        if self.__rect is None:
            self.__rect = _as_rect(atspi_common.atspi_rect(self.control)) or Rect(0, 0, 0, 0)
        return self.__rect

    def tag(self) -> str:
        if self.__tag is None:
            role = (atspi_common._role_name(self.control) or "").lower()
            self.__tag = TAG_MAP.get(role, role)
        return self.__tag

    def index(self) -> int:
        if self.__index is None:
            node = atspi_common.node_of(self.control)
            self.__index = node.get("index", 0)
        return self.__index

    def path(self, svc=None, strategy_svc=None) -> dict:
        res = atspi_common.build_path(self.control)
        res["img"] = {
            "self": screenshot(self.rect()),
        }

        pick_type = None
        if strategy_svc and getattr(strategy_svc, "data", None):
            pick_type = strategy_svc.data.get("pick_type")

        if pick_type in (PickerType.SIMILAR, PickerType.SIMILAR.value):
            from astronverse.locator.locator import LocatorManager

            similar_path = ATSPIPicker.get_similar_path(strategy_svc, res)
            if similar_path is None:
                raise Exception("找不到相识元素")
            res["path"] = similar_path
            res["img"]["self"] = strategy_svc.data.get("data", {}).get("img", {}).get("self", "")
            res["picker_type"] = PickerType.SIMILAR.value
            similar_list = LocatorManager().locator(res, timeout=10)
            if isinstance(similar_list, list):
                similar_count = len(similar_list)
                if similar_count == 0:
                    raise Exception("找不到相识元素")
            else:
                raise Exception("找不到相识元素")
            res["similar_count"] = similar_count
        elif pick_type in (PickerType.WINDOW, PickerType.WINDOW.value):
            if res.get("path"):
                res["path"] = [res["path"][0]]
            res["picker_type"] = PickerType.WINDOW.value
        else:
            if pick_type:
                res["picker_type"] = pick_type.value if hasattr(pick_type, "value") else str(pick_type)
            else:
                res["picker_type"] = PickerType.ELEMENT.value

        return res


class ATSPIPicker:
    """Linux AT-SPI 拾取操作"""

    __atspi_control_cache__: Optional[ATSPIElement] = None

    @classmethod
    def get_similar_path(cls, strategy_svc: Any, curr_path: dict) -> Optional[list]:
        old_ele = strategy_svc.data.get("data", {})
        new_ele = curr_path

        if old_ele.get("app", "") != new_ele.get("app", ""):
            return None
        if old_ele.get("type", "") != "atspi" or new_ele.get("type", "") != "atspi":
            return None
        raw_path1 = old_ele.get("path", [])
        raw_path2 = new_ele.get("path", [])
        if not raw_path1 or not raw_path2 or len(raw_path1) != len(raw_path2):
            return None

        path1 = copy.deepcopy(raw_path1)
        path2 = raw_path2

        match_similar = False
        is_first = True
        for i in range(len(path1)):
            if i == 0:
                attrs = ["tag_name", "cls", "name", "value"]
                for attr in attrs:
                    self_attr = path1[i].get(attr, None)
                    other_attr = path2[i].get(attr, None)
                    if self_attr and other_attr and self_attr != other_attr:
                        return None
                path1[i]["similar_parent"] = True
            else:
                is_eq = True
                attrs = ["tag_name", "cls", "name", "value", "index"]
                for attr in attrs:
                    self_attr = path1[i].get(attr, None)
                    other_attr = path2[i].get(attr, None)
                    if self_attr is not None and other_attr is not None and self_attr != other_attr:
                        is_eq = False
                        break
                if is_eq and not match_similar:
                    path1[i]["similar_parent"] = True
                else:
                    match_similar = True
                    if is_first:
                        is_first = False
                        path1[i]["disable_keys"] = ["cls", "name", "value", "index"]
                    else:
                        path1[i]["disable_keys"] = ["name", "value"]

        if not match_similar:
            return None
        return path1

    @classmethod
    def get_element(cls, start_el: Any, point: Any, **kwargs) -> Optional[ATSPIElement]:
        used_cache = kwargs.get("used_cache", False)

        if used_cache and cls.__atspi_control_cache__:
            try:
                res = cls.__atspi_control_cache__
                if res and res.rect().contains(point):
                    return res
            except Exception:
                cls.__atspi_control_cache__ = None

        target_el = None
        if point is not None:
            x, y = _point_xy(point)
            try:
                target_el = atspi_common.element_at_point(x, y)
            except Exception as e:
                logger.debug("element_at_point failed: %s", e)
                target_el = None

        if target_el is None and start_el is not None:
            target_el = getattr(start_el, "control", start_el)

        if target_el is None:
            return None

        element = ATSPIElement(control=target_el)
        cls.__atspi_control_cache__ = element
        return element


class ATSPIOperate:
    """Linux AT-SPI 操作工具类"""

    @classmethod
    def get_cursor_pos(cls) -> tuple[int, int]:
        pos = pyautogui.position()
        return int(round(pos.x)), int(round(pos.y))

    @classmethod
    def get_process_id(cls, el: Any) -> Optional[int]:
        if hasattr(el, "control"):
            el = el.control
        return atspi_common.pid_of(el)

    @classmethod
    def get_app_window(cls, el: Any) -> Any:
        if hasattr(el, "control"):
            el = el.control
        if not el:
            return None
        win = atspi_common.window_of(el)
        if win is not None:
            return win
        return el


atspi_picker = ATSPIPicker()
