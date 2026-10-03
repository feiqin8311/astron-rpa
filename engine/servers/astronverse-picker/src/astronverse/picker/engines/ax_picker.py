import base64
import collections
import copy
import io
import sys
from typing import Any, Optional

import pyautogui
from astronverse.locator.core import ax_common
from astronverse.picker import IElement, PickerType, Point, Rect
from astronverse.picker.logger import logger

TAG_MAP = {
    "AXButton": "按钮",
    "AXTextField": "编辑框",
    "AXTextArea": "编辑框",
    "AXStaticText": "文本",
    "AXCheckBox": "复选框",
    "AXRadioButton": "单选框",
    "AXPopUpButton": "下拉框",
    "AXComboBox": "下拉框",
    "AXMenuItem": "菜单项",
    "AXMenuBarItem": "菜单",
    "AXTable": "表格",
    "AXOutline": "表格",
    "AXRow": "行",
    "AXCell": "单元格",
    "AXImage": "图片",
    "AXLink": "链接",
    "AXTabGroup": "标签页",
    "AXWindow": "窗口",
    "AXGroup": "分组",
    "AXScrollArea": "滚动区域",
    "AXList": "列表",
    "AXSlider": "滑块",
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
    """截取元素图片。cv.screenshot 在 macOS Retina 上返回物理像素，这里缩放到 point 分辨率。"""
    if not rect or rect.area() == 0:
        return ""
    w, h = rect.width(), rect.height()
    if w <= 0 or h <= 0:
        return ""
    if sys.platform != "darwin":
        from astronverse.picker.utils.cv import screenshot as cv_screenshot

        return cv_screenshot(rect)
    try:
        st = pyautogui.screenshot(region=(rect.left, rect.top, w, h))
        if st.size != (w, h):
            st = st.resize((w, h))
        img_byte_arr = io.BytesIO()
        st.save(img_byte_arr, format="PNG")
        return base64.b64encode(img_byte_arr.getvalue()).decode("utf-8")
    except Exception as e:
        logger.debug("screenshot error: %s", e)
        return ""


class AXElement(IElement):
    """macOS Accessibility 元素封装"""

    def __init__(self, control: Any = None, element: Any = None):
        self.control = control if control is not None else element
        self.__index: Optional[int] = None
        self.__rect: Optional[Rect] = None
        self.__tag: Optional[str] = None

    def rect(self) -> Rect:
        if self.__rect is None:
            self.__rect = _as_rect(ax_common.ax_rect(self.control)) or Rect(0, 0, 0, 0)
        return self.__rect

    def tag(self) -> str:
        if self.__tag is None:
            role = ax_common.ax_attr(self.control, "AXRole") or ""
            if role in TAG_MAP:
                self.__tag = TAG_MAP[role]
            elif role.startswith("AX"):
                self.__tag = role[2:]
            else:
                self.__tag = role
        return self.__tag

    def index(self) -> int:
        if self.__index is None:
            node = ax_common.node_of(self.control)
            self.__index = node.get("index", 0)
        return self.__index

    def path(self, svc=None, strategy_svc=None) -> dict:
        res = ax_common.build_path(self.control)
        res["img"] = {
            "self": screenshot(self.rect()),
        }

        pick_type = None
        if strategy_svc and getattr(strategy_svc, "data", None):
            pick_type = strategy_svc.data.get("pick_type")

        if pick_type in (PickerType.SIMILAR, PickerType.SIMILAR.value):
            from astronverse.locator.locator import LocatorManager

            similar_path = AXPicker.get_similar_path(strategy_svc, res)
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


class AXPicker:
    """macOS AX 拾取操作"""

    __ax_control_cache__: Optional[AXElement] = None

    @classmethod
    def get_similar_path(cls, strategy_svc: Any, curr_path: dict) -> Optional[list]:
        """用户给定两个相似元素 (macOS AX)"""
        old_ele = strategy_svc.data.get("data", {})
        new_ele = curr_path

        # 过滤
        if old_ele.get("app", "") != new_ele.get("app", ""):
            return None
        if old_ele.get("type", "") != "ax" or new_ele.get("type", "") != "ax":
            return None
        raw_path1 = old_ele.get("path", [])
        raw_path2 = new_ele.get("path", [])
        if not raw_path1 or not raw_path2 or len(raw_path1) != len(raw_path2):
            return None

        path1 = copy.deepcopy(raw_path1)
        path2 = raw_path2

        # 比较
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
                        # 这一层子元素只基于 tag_name 做区分
                        is_first = False
                        path1[i]["disable_keys"] = ["cls", "name", "value", "index"]
                    else:
                        # 后续的子节点剔除 name 做区分
                        path1[i]["disable_keys"] = ["name", "value"]

        if not match_similar:
            return None
        return path1

    @classmethod
    def _refine_smallest_element(cls, root_el: Any, point: Any, max_depth: int = 15, max_nodes: int = 200) -> Any:
        """从 root_el 开始向下搜索包含 point 的最小面积元素 (忽略面积为 0 的元素)"""
        if point is None:
            return root_el

        x, y = _point_xy(point)
        pt = Point(x, y)

        best_el = root_el
        best_area = float("inf")
        best_depth = -1

        r = _as_rect(ax_common.ax_rect(root_el))
        if r and r.area() > 0 and r.contains(pt):
            best_area = r.area()
            best_el = root_el
            best_depth = 0

        queue = collections.deque([(root_el, 0)])
        visited = set()
        node_count = 0

        while queue and node_count < max_nodes:
            curr, depth = queue.popleft()
            curr_id = id(curr)
            if curr_id in visited:
                continue
            visited.add(curr_id)
            node_count += 1

            if curr is not root_el:
                curr_rect = _as_rect(ax_common.ax_rect(curr))
                if curr_rect and curr_rect.area() > 0:
                    if curr_rect.contains(pt):
                        area = curr_rect.area()
                        if area < best_area or (area == best_area and depth > best_depth):
                            best_area = area
                            best_el = curr
                            best_depth = depth
                    else:
                        # 非零尺寸且不包含点：跳过该子树以限制搜索宽度
                        continue

            if depth < max_depth:
                try:
                    children = ax_common.ax_children(curr)
                    if children:
                        for child in children[:50]:
                            queue.append((child, depth + 1))
                except Exception as e:
                    logger.debug("ax_children error: %s", e)

        return best_el

    @classmethod
    def get_element(cls, start_el: Any, point: Any, **kwargs) -> Optional[AXElement]:
        used_cache = kwargs.get("used_cache", False)

        if used_cache and cls.__ax_control_cache__:
            try:
                res = cls.__ax_control_cache__
                if res and res.rect().contains(point):
                    return res
            except Exception:
                cls.__ax_control_cache__ = None

        target_el = None
        if point is not None:
            x, y = _point_xy(point)
            try:
                target_el = ax_common.element_at_point(x, y)
            except Exception as e:
                logger.debug("element_at_point failed: %s", e)
                target_el = None

        if target_el is None and start_el is not None:
            target_el = getattr(start_el, "control", start_el)

        if target_el is None:
            return None

        best_el = cls._refine_smallest_element(target_el, point)
        element = AXElement(control=best_el)
        cls.__ax_control_cache__ = element
        return element


class AXOperate:
    """macOS AX 操作工具类"""

    @classmethod
    def get_cursor_pos(cls) -> tuple[int, int]:
        try:
            if sys.platform == "darwin":
                from Quartz import CGEventCreate, CGEventGetLocation

                event = CGEventCreate(None)
                loc = CGEventGetLocation(event)
                return int(round(loc.x)), int(round(loc.y))
        except Exception:
            pass
        pos = pyautogui.position()
        return int(round(pos.x)), int(round(pos.y))

    @classmethod
    def get_process_id(cls, el: Any) -> Optional[int]:
        if hasattr(el, "control"):
            el = el.control
        return ax_common.pid_of(el)

    @classmethod
    def get_app_window(cls, el: Any) -> Any:
        if hasattr(el, "control"):
            el = el.control
        if not el:
            return None
        win = ax_common.window_of(el)
        if win is not None:
            return win
        return el


ax_picker = AXPicker()
