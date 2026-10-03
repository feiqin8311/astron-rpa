"""macOS keyboard and mouse event tap used by the picker."""

import threading
import time
from typing import Any

from astronverse.picker import IEventCore, MKSign
from astronverse.picker.logger import logger


def process_event(
    event_type: Any,
    flags: int = 0,
    keycode: int | None = None,
    state: dict[str, bool] | None = None,
) -> tuple[bool, dict[str, bool]]:
    """Apply one event to a plain state mapping.

    The function is deliberately independent of Quartz so the gesture rules can
    be tested on any platform.
    """
    state = dict(state or {})
    event_type = {
        1: "leftMouseDown",
        2: "leftMouseUp",
        10: "keyDown",
        11: "keyUp",
        12: "flagsChanged",
    }.get(event_type, event_type)
    control = bool(state.get("control_down", False))
    command = bool(state.get("command_down", False))
    swallow_up = bool(state.get("swallow_mouse_up", False))
    swallow = False

    if event_type in ("flagsChanged", "flags_changed"):
        state["control_down"] = bool(flags & (1 << 18))
        state["command_down"] = bool(flags & (1 << 20))
    elif event_type in ("leftMouseDown", "left_mouse_down"):
        if control or command or bool(flags & ((1 << 18) | (1 << 20))):
            state["focus"] = True
            state["swallow_mouse_up"] = True
            swallow = True
    elif event_type in ("leftMouseUp", "left_mouse_up"):
        if swallow_up:
            state["swallow_mouse_up"] = False
            swallow = True
    elif event_type in ("keyUp", "key_up"):
        if keycode == 53:
            state["cancel"] = True
        elif keycode == 118:
            state["f4"] = True

    # Keep the state keys stable for callers and tests.
    state.setdefault("control_down", control)
    state.setdefault("command_down", command)
    state.setdefault("focus", False)
    state.setdefault("cancel", False)
    state.setdefault("f4", False)
    state.setdefault("swallow_mouse_up", False)
    return swallow, state


class EventCore(IEventCore):
    """Global event tap for Control/Command-click picking on macOS."""

    def __init__(self):
        self.__closed = True
        self.__init = False
        self.__tap = None
        self.__run_loop = None
        self.__thread = None
        self.__state: dict[str, bool] = {}
        self.domain = None
        self.error_message = ""

    def _callback(self, proxy, event_type, event, _refcon):
        try:
            import Quartz

            if event_type == getattr(Quartz, "kCGEventTapDisabledByTimeout", object()):
                if self.__tap is not None:
                    Quartz.CGEventTapEnable(self.__tap, True)
                return event

            type_names = {
                Quartz.kCGEventLeftMouseDown: "leftMouseDown",
                Quartz.kCGEventLeftMouseUp: "leftMouseUp",
                Quartz.kCGEventKeyDown: "keyDown",
                Quartz.kCGEventKeyUp: "keyUp",
                Quartz.kCGEventFlagsChanged: "flagsChanged",
            }
            name = type_names.get(event_type, event_type)
            flags = int(Quartz.CGEventGetFlags(event))
            keycode = None
            if event_type in (Quartz.kCGEventKeyDown, Quartz.kCGEventKeyUp):
                keycode = int(Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode))
            swallow, self.__state = process_event(name, flags, keycode, self.__state)
            return None if swallow else event
        except Exception as exc:
            logger.debug(f"macOS event callback failed: {exc}")
            return event

    def _hook(self):
        try:
            import Quartz
        except Exception as exc:
            self.error_message = f"无法加载 macOS 事件监听模块: {exc}"
            logger.error(self.error_message)
            self.__state["cancel"] = True
            self.__init = True
            return

        mask = sum(
            1 << event_type
            for event_type in (
                Quartz.kCGEventLeftMouseDown,
                Quartz.kCGEventLeftMouseUp,
                Quartz.kCGEventKeyDown,
                Quartz.kCGEventKeyUp,
                Quartz.kCGEventFlagsChanged,
            )
        )
        self.__tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,
            mask,
            self._callback,
            None,
        )
        if self.__tap is None:
            self.error_message = "无法创建 macOS 事件监听，请在系统设置中授予辅助功能和输入监控权限"
            logger.error(self.error_message)
            self.__state["cancel"] = True
            self.__init = True
            return

        source = Quartz.CFMachPortCreateRunLoopSource(None, self.__tap, 0)
        self.__run_loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(self.__run_loop, source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self.__tap, True)
        self.__init = True
        Quartz.CFRunLoopRun()

    def _hook_thread(self):
        try:
            self._hook()
        except Exception as exc:
            self.error_message = f"无法启动 macOS 事件监听: {exc}"
            logger.error(self.error_message)
            self.__state["cancel"] = True
            self.__init = True

    def is_cancel(self):
        return bool(self.__state.get("cancel", False))

    def is_focus(self):
        return bool(self.__state.get("focus", False))

    def is_f4_pressed(self):
        return bool(self.__state.get("f4", False))

    def reset_f4_flag(self):
        self.__state["f4"] = False

    def reset_cancel_flag(self):
        self.__state["cancel"] = False

    def start(self, domain=MKSign.PICKER):
        if not self.__closed:
            return False
        self.__state = {
            "control_down": False,
            "command_down": False,
            "focus": False,
            "cancel": False,
            "f4": False,
            "swallow_mouse_up": False,
        }
        self.error_message = ""
        self.__init = False
        self.__closed = False
        self.domain = domain
        self.__thread = threading.Thread(target=self._hook_thread, daemon=True)
        self.__thread.start()
        while not self.__init:
            time.sleep(0.01)
        return True

    def close(self):
        if self.__closed:
            return False
        try:
            import Quartz

            if self.__tap is not None:
                Quartz.CGEventTapEnable(self.__tap, False)
            if self.__run_loop is not None:
                Quartz.CFRunLoopStop(self.__run_loop)
        except Exception as exc:
            logger.debug(f"EventCore close failed: {exc}")
        self.__tap = None
        self.__run_loop = None
        self.__closed = True
        self.domain = None
        return True
