"""Linux keyboard and mouse listener used by the picker (pynput / X11)."""

import threading
import time
from typing import Any

from astronverse.picker import IEventCore, MKSign
from astronverse.picker.logger import logger


def process_event(
    event_type: Any,
    key: str | None = None,
    state: dict[str, bool] | None = None,
) -> tuple[bool, dict[str, bool]]:
    """Apply one event to a plain state mapping.

    Independent of pynput so the gesture rules can be tested anywhere.
    event_type: press / release / click / click_up
    key: ctrl, esc, f4, left
    """
    state = dict(state or {})
    control = bool(state.get("control_down", False))
    swallow_up = bool(state.get("swallow_mouse_up", False))
    swallow = False
    key_name = (key or "").lower()

    if event_type in ("press", "key_down"):
        if key_name in ("ctrl", "ctrl_l", "ctrl_r", "control"):
            state["control_down"] = True
        elif key_name in ("esc", "escape"):
            state["cancel"] = True
        elif key_name == "f4":
            state["f4"] = True
    elif event_type in ("release", "key_up"):
        if key_name in ("ctrl", "ctrl_l", "ctrl_r", "control"):
            state["control_down"] = False
        elif key_name in ("esc", "escape"):
            state["cancel"] = True
        elif key_name == "f4":
            state["f4"] = True
    elif event_type in ("click", "left_mouse_down"):
        if control or key_name == "ctrl":
            state["focus"] = True
            state["swallow_mouse_up"] = True
            swallow = True
    elif event_type in ("click_up", "left_mouse_up"):
        if swallow_up:
            state["swallow_mouse_up"] = False
            swallow = True

    state.setdefault("control_down", control)
    state.setdefault("focus", False)
    state.setdefault("cancel", False)
    state.setdefault("f4", False)
    state.setdefault("swallow_mouse_up", False)
    return swallow, state


def _key_name(key: Any) -> str:
    name = getattr(key, "name", None)
    if name:
        return str(name).lower()
    char = getattr(key, "char", None)
    if char:
        return str(char).lower()
    text = str(key)
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.strip("<>").lower()


class EventCore(IEventCore):
    """pynput listener: Ctrl+click to pick, ESC to cancel, F4 for similar."""

    def __init__(self):
        self.__closed = True
        self.__init = False
        self.__kb = None
        self.__mouse = None
        self.__state: dict[str, bool] = {}
        self.domain = None
        self.error_message = ""

    def _on_press(self, key):
        _, self.__state = process_event("press", _key_name(key), self.__state)

    def _on_release(self, key):
        _, self.__state = process_event("release", _key_name(key), self.__state)

    def _on_click(self, x, y, button, pressed):
        name = getattr(button, "name", str(button)).lower()
        if name not in ("left", "button1"):
            return True
        kind = "click" if pressed else "click_up"
        swallow, self.__state = process_event(kind, "left", self.__state)
        # ponytail: pynput cannot swallow a single click on X11 without grabbing all mouse events
        return True

    def _hook_thread(self):
        try:
            from pynput import keyboard, mouse
        except Exception as exc:
            self.error_message = f"无法加载 Linux 事件监听模块: {exc}"
            logger.error(self.error_message)
            self.__state["cancel"] = True
            self.__init = True
            return

        try:
            self.__kb = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
            self.__mouse = mouse.Listener(on_click=self._on_click)
            self.__kb.start()
            self.__mouse.start()
            self.__init = True
            while not self.__closed:
                time.sleep(0.05)
        except Exception as exc:
            self.error_message = f"无法启动 Linux 事件监听: {exc}"
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
            "focus": False,
            "cancel": False,
            "f4": False,
            "swallow_mouse_up": False,
        }
        self.error_message = ""
        self.__init = False
        self.__closed = False
        self.domain = domain
        threading.Thread(target=self._hook_thread, daemon=True).start()
        while not self.__init:
            time.sleep(0.01)
        return True

    def close(self):
        if self.__closed:
            return False
        self.__closed = True
        for listener in (self.__kb, self.__mouse):
            if listener is None:
                continue
            try:
                listener.stop()
            except Exception as exc:
                logger.debug("EventCore close failed: %s", exc)
        self.__kb = None
        self.__mouse = None
        self.domain = None
        return True
