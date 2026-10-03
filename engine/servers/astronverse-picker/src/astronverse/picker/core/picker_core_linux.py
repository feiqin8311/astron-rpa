"""Accessibility based picker implementation for Linux (AT-SPI)."""

import os
import threading
import time
from typing import Optional

import pyautogui
from astronverse.locator.core import atspi_common
from astronverse.picker import (
    DrawResult,
    IElement,
    IPickerCore,
    PickerDomain,
    PickerSign,
    PickerType,
    Point,
    Rect,
    SmartComponentAction,
)
from astronverse.picker.logger import logger


class PickerCore(IPickerCore):
    _POINT_TYPES = {PickerType.POINT, PickerType.POINT.value}
    _WINDOW_TYPES = {PickerType.WINDOW, PickerType.WINDOW.value}
    _ELEMENT_TYPES = {
        PickerType.ELEMENT,
        PickerType.ELEMENT.value,
        PickerType.SIMILAR,
        PickerType.SIMILAR.value,
        PickerType.BATCH,
        PickerType.BATCH.value,
    }

    def __init__(self):
        self.last_point = Point(0, 0)
        self.last_element: Optional[IElement] = None
        self.last_strategy_svc = None
        self.lock = threading.Lock()
        self.last_valid_rect: Optional[Rect] = None
        self.last_valid_tag = ""
        self.last_valid_domain: Optional[str] = None

    def _get_element_domain(self, element: IElement) -> str:
        name = type(element).__name__
        if name == "ATSPIElement":
            return PickerDomain.ATSPI.value
        if name == "WEBElement":
            return PickerDomain.WEB.value
        return PickerDomain.ATSPI.value

    @staticmethod
    def _app_name(pid: int | None) -> str:
        if not pid:
            return ""
        try:
            import psutil

            return psutil.Process(pid).name()
        except Exception:
            return ""

    def _is_own_window(self, pid: int | None) -> bool:
        if pid == os.getpid():
            return True
        name = self._app_name(pid).lower()
        return "astron" in name or "星辰" in name

    def draw(self, svc, highlight_client, data: dict) -> DrawResult:
        try:
            pos = pyautogui.position()
            self.last_point = Point(int(round(pos.x)), int(round(pos.y)))
            pick_type = data.get("pick_type")
            if pick_type in self._POINT_TYPES:
                return DrawResult(success=True)
            if pick_type in self._WINDOW_TYPES:
                return self._draw_window(svc, highlight_client, data)
            if pick_type in self._ELEMENT_TYPES:
                return self._draw_element(svc, highlight_client, data)
            return DrawResult(success=False, error_message=f"不支持的拾取类型: {pick_type}")
        except Exception as exc:
            logger.error(f"Linux拾取绘制失败: {exc}")
            return DrawResult(success=False, error_message=str(exc))

    def _draw_window(self, svc, highlight_client, data: dict) -> DrawResult:
        control = atspi_common.element_at_point(self.last_point.x, self.last_point.y)
        win = atspi_common.window_of(control) if control is not None else None
        if win is None:
            return DrawResult(success=False, error_message="未找到窗口")
        pid = atspi_common.pid_of(control)
        if self._is_own_window(pid):
            return self._cached_result()
        from astronverse.picker.engines.atspi_picker import ATSPIElement

        with self.lock:
            self.last_element = ATSPIElement(win)
        self.last_strategy_svc = svc.strategy.gen_svc(pid, self.last_point, data, control, PickerDomain.ATSPI)
        rect = self.last_element.rect()
        tag = self.last_element.tag()
        self._cache(rect, tag, PickerDomain.ATSPI.value)
        highlight_client.draw_wnd(rect, msgs=tag)
        return DrawResult(True, rect, self.last_strategy_svc.app.value, domain=PickerDomain.ATSPI.value)

    def _draw_element(self, svc, highlight_client, data: dict) -> DrawResult:
        control = atspi_common.element_at_point(self.last_point.x, self.last_point.y)
        if control is None:
            return DrawResult(False, error_message="未找到起始控件")
        pid = atspi_common.pid_of(control)
        if self._is_own_window(pid):
            return self._cached_result()
        if not svc.strategy:
            for _ in range(100):
                if svc.strategy:
                    break
                time.sleep(0.1)
            if not svc.strategy:
                return DrawResult(False, error_message="策略加载超时（10s）")
        pick_mode = data.get("pick_mode")
        if pick_mode == "WebPick":
            domain = PickerDomain.AUTO_WEB
        elif pick_mode:
            domain = PickerDomain.AUTO_DESK
        else:
            domain = PickerDomain.AUTO
        self.last_strategy_svc = svc.strategy.gen_svc(pid, self.last_point, data, control, domain)
        result = svc.strategy.run(self.last_strategy_svc)
        if not result:
            return DrawResult(False)
        with self.lock:
            self.last_element = result
        rect, tag = result.rect(), result.tag()
        actual = self._get_element_domain(result)
        self._cache(rect, tag, actual)
        highlight_client.draw_wnd(rect, msgs=tag)
        return DrawResult(True, rect, self.last_strategy_svc.app.value, domain=actual)

    def _cache(self, rect, tag, domain):
        self.last_valid_rect, self.last_valid_tag, self.last_valid_domain = rect, tag, domain

    def _cached_result(self):
        if self.last_valid_rect:
            return DrawResult(True, self.last_valid_rect, domain=self.last_valid_domain)
        return DrawResult(False, error_message="未找到可拾取元素")

    def call_pluguin(self, svc, high_light, data: dict):
        """通过浏览器插件做智能组件拾取（document web 视口 + WEB 策略）。"""
        import json

        from astronverse.locator.core import atspi_common
        from astronverse.picker.strategy.auto_strategy_linux import viewport_from_web_document

        pick_type = data.get("pick_type", "")
        pick_sign = data.get("pick_sign", "")
        smart_component_action = data.get("smart_component_action", "")
        pos = pyautogui.position()
        cur_point = Point(int(round(pos.x)), int(round(pos.y)))
        data_str = data.get("data", "{}")
        data_dict = json.loads(data_str) if isinstance(data_str, str) else data_str
        data["data"] = data_dict
        app = data_dict.get("app")
        title = data_dict.get("path", {}).get("tabTitle", "") or data_dict.get("title", "")

        start_control = None
        process_id = 0
        pids = atspi_common.find_apps(str(app)) if app else []
        if not pids:
            el = atspi_common.element_at_point(cur_point.x, cur_point.y)
            pid = atspi_common.pid_of(el)
            if pid:
                pids = [pid]
        for pid in pids:
            app_el = atspi_common.app_element(pid)
            for win in atspi_common.app_windows(app_el):
                win_title = str(atspi_common.atspi_name(win) or "")
                if title and title not in win_title and win_title not in title:
                    continue
                web = atspi_common.find_web_document(win)
                viewport = viewport_from_web_document(web) if web is not None else None
                if viewport is None:
                    continue
                start_control = viewport
                process_id = int(pid)
                break
            if start_control is not None:
                break
        if start_control is None:
            el = atspi_common.element_at_point(cur_point.x, cur_point.y)
            web = atspi_common.find_web_document(el)
            start_control = viewport_from_web_document(web) if web is not None else None
            process_id = int(atspi_common.pid_of(el) or 0)
        if not start_control:
            logger.info("拾取预处理 start_control 为空")
            return "未找到浏览器，请重试"

        if pick_type not in (PickerType.ELEMENT, PickerType.ELEMENT.value):
            return "拾取类型不支持智能组件"
        if pick_sign not in (PickerSign.SMART_COMPONENT, PickerSign.SMART_COMPONENT.value):
            return "拾取接口参数传递异常"

        if not svc.strategy:
            timeout = 10
            wait_time = 0
            while not svc.strategy and wait_time < timeout:
                time.sleep(0.1)
                wait_time += 0.1
            if not svc.strategy:
                return "策略加载超时（10s）"
            logger.info("strategy 加载完成")

        cur_strategy_svc = svc.strategy.gen_svc(
            process_id=process_id,
            last_point=cur_point,
            data=data,
            start_control=start_control,
            domain=PickerDomain.WEB,
        )
        try:
            res = svc.strategy.run(cur_strategy_svc)
            if res:
                cur_rect = res.rect()
                cur_tag = res.tag()
                if smart_component_action in [SmartComponentAction.PREVIOUS, SmartComponentAction.NEXT]:
                    high_light.draw_wnd(cur_rect, msgs=cur_tag)
                return res.path(svc, cur_strategy_svc)
        except Exception as e:
            logger.info(f"智能组件出现异常 {e}")
            res = str(e)
        return res

    def element(self, svc, data: dict) -> dict:
        pick_type = data.get("pick_type")
        if pick_type in self._POINT_TYPES:
            return {"point": {"x": self.last_point.x, "y": self.last_point.y}, "version": "1"}
        if pick_type in self._WINDOW_TYPES | self._ELEMENT_TYPES:
            with self.lock:
                if self.last_element:
                    return self.last_element.path(svc, self.last_strategy_svc)
            return {}
        raise NotImplementedError()
