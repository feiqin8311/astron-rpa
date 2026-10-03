"""Linux 自动拾取策略：Chrome-like 浏览器视口 (document web) + web 扩展，失败则回退 AT-SPI。

坐标约定：视口原点 = atspi_rect(web document) 的 (left, top)，全局屏幕点。
GTK4 窗口相对 SCREEN extents 已在 atspi_rect 中补偿。
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
        from astronverse.locator.core.atspi_common import atspi_rect

        return atspi_rect(el)
    except Exception:
        return None


def _pid(el: Any) -> int:
    if el is None:
        return 0
    pid = getattr(el, "pid", None)
    if pid:
        return int(pid)
    try:
        from astronverse.locator.core.atspi_common import pid_of

        p = pid_of(el)
        return int(p) if p else 0
    except Exception:
        return 0


def viewport_from_web_document(web_el: Any) -> Optional[_WebViewportControl]:
    r = _rect(web_el)
    if r is None:
        return None
    return _WebViewportControl(
        left=r.left,
        top=r.top,
        right=r.right,
        bottom=r.bottom,
        hwnd=_pid(web_el),
    )


def _is_chrome_like(app: APP) -> bool:
    if app is None:
        return False
    value = app.value if isinstance(app, APP) else app
    return value in CHROME_LIKE_BROWSER_TYPES


def auto_default_strategy_linux(service_context, strategy, strategy_svc: StrategySvc) -> Optional[IElement]:
    """Linux 自动策略：Chrome-like 浏览器走 web，否则 / 失败回退 AT-SPI。"""
    domain = strategy_svc.domain

    if _is_chrome_like(strategy_svc.app) and domain != PickerDomain.AUTO_DESK:
        from astronverse.locator.core.atspi_common import find_web_document

        web_el = find_web_document(strategy_svc.start_control)
        if web_el is not None:
            r = _rect(web_el)
            if r is not None:
                viewport = _WebViewportControl(
                    left=r.left,
                    top=r.top,
                    right=r.right,
                    bottom=r.bottom,
                    hwnd=_pid(web_el),
                )
                web_svc = dataclasses.replace(strategy_svc, start_control=viewport)
                try:
                    from astronverse.picker.strategy.web_strategy import web_default_strategy

                    ele = web_default_strategy(service_context, web_svc)
                    if ele is not None:
                        return ele
                except Exception as e:
                    logger.error(f"auto_default_strategy_linux web error: {e}")

        if domain == PickerDomain.AUTO_WEB:
            return None

    from astronverse.picker.strategy.atspi_strategy import atspi_default_strategy

    return atspi_default_strategy(service_context, strategy, strategy_svc)
