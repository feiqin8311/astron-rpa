import sys
from collections import deque
from typing import Any, Optional, Union

import requests
from astronverse.baseline.logger.logger import logger
from astronverse.locator import (
    BROWSER_UIA_POINT_CLASS,
    BROWSER_UIA_WINDOW_CLASS,
    LIKE_CHROME_BROWSER_TYPES,
    BrowserType,
    ILocator,
    Rect,
)
from astronverse.locator.utils.window import top_browser

if sys.platform == "win32":
    import uiautomation as auto


def _bfs_ax_webarea(win: Any, ax_common: Any, max_depth: int = 12) -> Optional[Rect]:
    queue: deque[tuple[Any, int]] = deque([(win, 0)])
    while queue:
        el, depth = queue.popleft()
        if ax_common.ax_attr(el, "AXRole") == "AXWebArea":
            rect = ax_common.ax_rect(el)
            if rect is not None and rect.width() > 0 and rect.height() > 0:
                return rect
        if depth >= max_depth:
            continue
        for child in ax_common.ax_children(el):
            queue.append((child, depth + 1))
    return None


def _ax_webarea_origin(pid: int) -> Optional[tuple[int, int]]:
    if not pid:
        return None
    from astronverse.locator.core import ax_common

    app_el = ax_common.app_element(pid)
    for win in ax_common.app_windows(app_el):
        if ax_common.ax_attr(win, "AXMinimized"):
            continue
        ax_common.raise_window(win, pid)
        rect = _bfs_ax_webarea(win, ax_common)
        if rect is not None:
            return rect.top, rect.left
    return None


class WEBLocator(ILocator):
    def __init__(self, rect=None, rects=None):
        self.__rect = rect
        self.__rects = rects

    def rect(self) -> Optional[Rect]:
        if self.__rects is not None and len(self.__rects) > 0:
            return self.__rects
        return self.__rect

    def control(self) -> Any:
        return None


class WebFactory:
    """Web工厂"""

    @classmethod
    def find(cls, ele: dict, picker_type: str, **kwargs) -> Union[WEBLocator, None]:
        cur_target_app = kwargs.get("cur_target_app")
        app = ele.get("app", "")
        if cur_target_app:
            app = cur_target_app
        if app not in LIKE_CHROME_BROWSER_TYPES:
            # 直接结束
            return None
        # 获取外部配置
        scroll_into_view = kwargs.get("scroll_into_view", True)
        scroll_into_center = kwargs.get("scroll_into_center", True)

        menu_height, menu_left = cls.__get_web_top__(ele, app=app)

        # 通过插件获取元素位置信息
        rect_res = cls.__get_rect_from_browser_plugin__(
            ele, app=app, scroll_into_view=scroll_into_view, scroll_into_center=scroll_into_center
        )
        if not rect_res:
            return None
        rect = Rect(
            int(rect_res[0]["x"] + menu_left),
            int(rect_res[0]["y"] + menu_height),
            int(rect_res[0]["right"] + menu_left),
            int(rect_res[0]["bottom"] + menu_height),
        )
        rects = []
        if len(rect_res) > 1:
            for s_rect in rect_res:
                rects.append(
                    Rect(
                        int(s_rect["x"] + menu_left),
                        int(s_rect["y"] + menu_height),
                        int(s_rect["right"] + menu_left),
                        int(s_rect["bottom"] + menu_height),
                    )
                )
        return WEBLocator(rect=rect, rects=rects)

    @classmethod
    def __get_rect_from_browser_plugin__(cls, element: dict, app: str, scroll_into_view=True, scroll_into_center=True):
        """通过浏览器插件获取rect"""
        url = "http://127.0.0.1:9082/browser/transition"
        browser_type = app
        path_data = element.get("path", {})
        try:
            # 如果需要滚动到视图中
            if scroll_into_view:
                path_data = {**path_data, "atomConfig": {"scrollIntoCenter": scroll_into_center}}
                requests.post(
                    url, json={"browser_type": browser_type, "data": path_data, "key": "scrollIntoView"}, timeout=10
                )

            # 检查元素
            response = requests.post(
                url, json={"browser_type": browser_type, "data": path_data, "key": "checkElement"}, timeout=10
            )

            if response.status_code != 200:
                raise Exception("浏览器插件通信通道出错，请重启应用")

            logger.info(f"浏览器插件返回结果: {response.text}")
            res_json = response.json()

            if not res_json or res_json.get("code", "") != "0000":  # 通信错误
                raise Exception("浏览器插件通信失败, 请检查插件是否安装并启用")
            elif res_json.get("code", "") == "0000":
                data = res_json.get("data", {})
                if data.get("code", "") != "0000":  # 元素错误
                    raise Exception(data.get("msg", "浏览器插件获取元素失败"))
                web_info = data.get("data", {})
                return web_info["rect"]

        except requests.exceptions.ConnectionError:
            raise Exception("无法连接浏览器插件服务，请确认插件状态")
        except requests.exceptions.Timeout:
            raise Exception("浏览器插件响应超时，请检查插件是否安装并启用")
        except Exception as e:
            raise Exception(f"获取元素失败：{e}")

    @classmethod
    def __get_web_top__(cls, element: dict, app: str) -> tuple[int, int]:
        """浏览器右上角位置"""
        if sys.platform == "darwin":
            ctrl = top_browser(app_name=app)
            if ctrl is None:
                raise Exception(f"未找到{app}浏览器窗口，请确认浏览器是否已启动")

            origin = _ax_webarea_origin(getattr(ctrl, "ProcessId", 0))
            if origin is not None:
                return origin

            logger.warning("未找到浏览器 AXWebArea，回退到窗口顶部 + 工具栏高度估算")

            b_rect = ctrl.BoundingRectangle
            window_top = b_rect.top
            window_left = b_rect.left
            window_height = b_rect.height()

            # The web element rect from the extension is relative to the viewport.
            # On macOS, compute viewport top = window_top + (window_height - viewport_height)
            # when the extension provides window.innerHeight/outerHeight data.
            # If not available, use sensible fixed offset per browser.
            viewport_height = element.get("innerHeight") or element.get("viewport_height")
            outer_height = element.get("outerHeight") or element.get("window_height")
            if viewport_height and outer_height:
                toolbar_height = int(outer_height) - int(viewport_height)
            elif viewport_height and window_height:
                toolbar_height = int(window_height) - int(viewport_height)
            else:
                # TODO: Extension checkElement does not currently return window.innerHeight/outerHeight.
                # When browser extension is updated to supply viewport dimension metadata,
                # toolbar_height can be computed dynamically as (window_height - viewport_height).
                # Default toolbar heights on macOS:
                # Chrome: ~85px (tab bar + address bar)
                # Edge: ~85px
                # Firefox: ~85px
                # Chromium: ~85px
                browser_toolbar_heights = {
                    BrowserType.CHROME.value: 85,
                    BrowserType.EDGE.value: 85,
                    BrowserType.FIREFOX.value: 85,
                    BrowserType.CHROMIUM.value: 85,
                    BrowserType.CHROME_360_SE.value: 85,
                    BrowserType.CHROME_360_X.value: 85,
                }
                toolbar_height = browser_toolbar_heights.get(app, 85)

            viewport_top = window_top + toolbar_height
            viewport_left = window_left
            return viewport_top, viewport_left

        app_name = app
        cfg = BROWSER_UIA_WINDOW_CLASS.get(app_name)
        if not cfg:
            return 0, 0
        point_cfg = BROWSER_UIA_POINT_CLASS.get(app_name)
        if not point_cfg:
            return 0, 0

        class_name, patterns, match_type = cfg
        tag_value, tag = point_cfg

        # 查找窗口
        root_control = auto.GetRootControl()
        base_ctrl = None
        for control, depth in auto.WalkControl(root_control, includeTop=True, maxDepth=1):
            if control.ClassName != class_name:
                continue
            if not patterns:
                base_ctrl = control
                break
            text = control.Name.split("-")[-1].strip() if match_type == "last_in" else control.Name
            if any(p.lower() in text.lower() for p in patterns):
                base_ctrl = control
                break

        if base_ctrl is None:
            raise Exception(f"未找到{app_name}浏览器窗口，请确认浏览器是否已启动")

        # 置顶窗口
        try:
            top_browser(handle=base_ctrl.NativeWindowHandle, ctrl=base_ctrl)
        except Exception as e:
            pass

        # 获取位置
        for control, depth in auto.WalkControl(base_ctrl, includeTop=True, maxDepth=12):
            if tag == "ClassName":
                tag_match = control.ClassName
            elif tag == "AutomationId":
                tag_match = control.AutomationId
            else:
                tag_match = ""
            if tag_match == tag_value:
                bounding_rect = control.BoundingRectangle
                top = bounding_rect.top
                left = bounding_rect.left
                return top, left
        return 0, 0


web_factory = WebFactory()
