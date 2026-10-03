"""macOS 自动拾取策略：浏览器视口 (AXWebArea) + web 扩展，失败则回退 AX。

坐标约定（拾取侧视口原点，locator 回放需镜像）：
- 从光标下的 AXUIElement 沿 AXParent 上走到 AXRole == "AXWebArea"；
  视口原点 = ax_rect(AXWebArea) 的 (left, top)，全局屏幕点，主屏左上为原点。
- 扩展返回的元素 rect 是视口相对的 CSS px。macOS 页面缩放 100% 时 CSS px == 点
  （与 Retina / devicePixelRatio 无关；dPR 只影响物理像素）。
- 若扩展 payload 含 zoom / pageZoom，仅按 zoom 把 CSS 值换算为点；绝不除以 devicePixelRatio。
"""

import dataclasses
from typing import Any, Optional

from astronverse.picker import APP, CHROME_LIKE_BROWSER_TYPES, IElement, PickerDomain
from astronverse.picker.logger import logger
from astronverse.picker.strategy.types import StrategySvc


class _WebViewportControl:
    """轻量控件，形状对齐 UIA start_control，供 web_default_strategy 原样使用。"""

    def __init__(self, left, top, right, bottom, hwnd=0):
        self.BoundingRectangle = _Bound(left, top, right, bottom)
        self.NativeWindowHandle = hwnd or 0


class _Bound:
    def __init__(self, left, top, right, bottom):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


def _role(el: Any) -> Optional[str]:
    if el is None:
        return None
    role = getattr(el, "role", None)
    if role:
        return role
    try:
        from astronverse.locator.core.ax_common import ax_attr

        return ax_attr(el, "AXRole")
    except Exception:
        return None


def _parent(el: Any) -> Any:
    if el is None:
        return None
    parent = getattr(el, "parent", None)
    if parent is not None:
        return parent
    try:
        from astronverse.locator.core.ax_common import ax_parent

        return ax_parent(el)
    except Exception:
        return None


def _rect(el: Any) -> Any:
    if el is None:
        return None
    r = getattr(el, "_rect", None)
    if r is not None and hasattr(r, "left"):
        return r
    br = getattr(el, "BoundingRectangle", None)
    if br is not None and hasattr(br, "left"):
        return br
    try:
        from astronverse.locator.core.ax_common import ax_rect

        return ax_rect(el)
    except Exception:
        return None


def _pid(el: Any) -> int:
    if el is None:
        return 0
    pid = getattr(el, "pid", None)
    if pid:
        return int(pid)
    try:
        from astronverse.locator.core.ax_common import pid_of

        p = pid_of(el)
        return int(p) if p else 0
    except Exception:
        return 0


def find_web_area_down(el: Any, max_depth: int = 40) -> Any:
    """先向上找 AXWebArea，找不到再向下 BFS。"""
    found = _find_web_area(el)
    if found is not None:
        return found
    if el is None:
        return None
    from collections import deque

    queue = deque([(el, 0)])
    seen = {id(el)}
    while queue:
        curr, depth = queue.popleft()
        if _role(curr) == "AXWebArea":
            return curr
        if depth >= max_depth:
            continue
        children = getattr(curr, "children", None)
        if children is None:
            try:
                from astronverse.locator.core.ax_common import ax_children

                children = ax_children(curr)
            except Exception:
                children = []
        for child in children or []:
            if id(child) in seen:
                continue
            seen.add(id(child))
            queue.append((child, depth + 1))
    return None


def viewport_from_web_area(web_area: Any) -> Optional[_WebViewportControl]:
    r = _rect(web_area)
    if r is None:
        return None
    return _WebViewportControl(
        left=r.left,
        top=r.top,
        right=r.right,
        bottom=r.bottom,
        hwnd=_window_hwnd(web_area) or _pid(web_area),
    )


def _find_web_area(el: Any) -> Any:
    """沿 AXParent 上走到 AXWebArea（含自身）。"""
    curr = el
    seen: set[int] = set()
    depth = 0
    while curr is not None and id(curr) not in seen and depth < 50:
        seen.add(id(curr))
        if _role(curr) == "AXWebArea":
            return curr
        curr = _parent(curr)
        depth += 1
    return None


def _window_hwnd(el: Any) -> int:
    """AXWindow 的 pid，找不到则 0。"""
    curr = el
    seen: set[int] = set()
    while curr is not None and id(curr) not in seen:
        seen.add(id(curr))
        if _role(curr) == "AXWindow":
            return _pid(curr)
        curr = _parent(curr)
    return _pid(el)


def _is_chrome_like(app: APP) -> bool:
    if app is None:
        return False
    value = app.value if isinstance(app, APP) else app
    return value in CHROME_LIKE_BROWSER_TYPES


def auto_default_strategy_mac(service_context, strategy, strategy_svc: StrategySvc) -> Optional[IElement]:
    """macOS 自动策略：Chrome-like 浏览器走 web（AXWebArea 视口），否则 / 失败回退 AX。"""
    domain = strategy_svc.domain

    if _is_chrome_like(strategy_svc.app) and domain != PickerDomain.AUTO_DESK:
        web_area = _find_web_area(strategy_svc.start_control)
        if web_area is not None:
            r = _rect(web_area)
            if r is not None:
                viewport = _WebViewportControl(
                    left=r.left,
                    top=r.top,
                    right=r.right,
                    bottom=r.bottom,
                    hwnd=_window_hwnd(web_area),
                )
                web_svc = dataclasses.replace(strategy_svc, start_control=viewport)
                try:
                    from astronverse.picker.strategy.web_strategy import web_default_strategy

                    ele = web_default_strategy(service_context, web_svc)
                    if ele is not None:
                        return ele
                except Exception as e:
                    logger.error(f"auto_default_strategy_mac web error: {e}")

        if domain == PickerDomain.AUTO_WEB:
            return None

    from astronverse.picker.strategy.ax_strategy import ax_default_strategy

    return ax_default_strategy(service_context, strategy, strategy_svc)
