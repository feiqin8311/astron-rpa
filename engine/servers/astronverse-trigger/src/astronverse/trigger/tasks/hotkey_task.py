import asyncio
import re
import sys

from astronverse.trigger.core.logger import logger

KEY_MAP = {
    # Modifiers
    "ctrl": "<ctrl>",
    "control": "<ctrl>",
    "alt": "<alt>",
    "option": "<alt>",
    "opt": "<alt>",
    "shift": "<shift>",
    "win": "<cmd>",
    "windows": "<cmd>",
    "cmd": "<cmd>",
    "command": "<cmd>",
    "super": "<cmd>",
    "meta": "<cmd>",
    # Special keys
    "esc": "<esc>",
    "escape": "<esc>",
    "enter": "<enter>",
    "return": "<enter>",
    "space": "<space>",
    "spacebar": "<space>",
    "tab": "<tab>",
    "backspace": "<backspace>",
    "delete": "<delete>",
    "del": "<delete>",
    "up": "<up>",
    "down": "<down>",
    "left": "<left>",
    "right": "<right>",
    "home": "<home>",
    "end": "<end>",
    "page_up": "<page_up>",
    "pageup": "<page_up>",
    "page up": "<page_up>",
    "pgup": "<page_up>",
    "page_down": "<page_down>",
    "pagedown": "<page_down>",
    "page down": "<page_down>",
    "pgdn": "<page_down>",
    "caps_lock": "<caps_lock>",
    "capslock": "<caps_lock>",
    "caps": "<caps_lock>",
}


def _map_key(key: str) -> str:
    k = key.strip()
    if not k:
        return ""
    if k.startswith("<") and k.endswith(">") and len(k) > 2:
        k = k[1:-1].strip()
    k_lower = k.lower()
    if k_lower in KEY_MAP:
        return KEY_MAP[k_lower]
    if re.match(r"^f([1-9]|1[0-9]|2[0-4])$", k_lower):
        return f"<{k_lower}>"
    if len(k) == 1:
        return k.lower()
    return f"<{k_lower}>"


def to_pynput_hotkey(shortcuts: list[str]) -> str:
    """
    将快捷键列表转换为 pynput GlobalHotKeys 格式字符串，例如：
    ['ctrl', 'alt', 'a'] -> '<ctrl>+<alt>+a'
    ['Ctrl', 'Shift', 'F1'] -> '<ctrl>+<shift>+<f1>'
    """
    if not shortcuts:
        return ""
    if isinstance(shortcuts, str):
        shortcuts = [shortcuts]

    parts = []
    for item in shortcuts:
        if not item:
            continue
        if "+" in item and item.strip() != "+":
            sub_items = [p.strip() for p in item.split("+") if p.strip()]
        else:
            sub_items = [item.strip()]
        for key in sub_items:
            mapped = _map_key(key)
            if mapped:
                parts.append(mapped)
    return "+".join(parts)


class HotKeyTask:
    def __init__(self, shortcuts: list | None = None, **kwargs):
        """
        构建热键监听的类

        shortcuts: `List`, 快捷键组合

        Kwargs: 该参数用于构建任务的详细参数状态
        """
        self.shortcuts = shortcuts
        self._h_handle = None  # 用于控制监听事件的对象

    async def callback(self, q: asyncio.Queue, run_event: asyncio.Event):
        async def handle_hotkey():
            logger.debug("handle_hotkey: enqueue True to asyncio.Queue")
            await q.put(True)
            try:
                logger.debug(f"handle_hotkey: queue size after put -> {q.qsize()}")
            except Exception:
                pass

        def on_hotkey_press(target_loop=None):
            """loop主要作用于当前事件循环，在同一时间循环下进行任务执行"""
            active_loop = target_loop if target_loop is not None else loop
            try:
                is_set = run_event.is_set()
            except Exception as e:
                logger.exception(f"on_hotkey_press: failed to read run_event.is_set(): {e}")
                is_set = False
            logger.debug(f"on_hotkey_press: hotkey '{hotkey_expression}' pressed, run_event.is_set={is_set}")
            if is_set:
                logger.info("on_hotkey_press: run_event is set; ignore hotkey")
                return
            active_loop.call_soon_threadsafe(asyncio.create_task, handle_hotkey())
            logger.debug("on_hotkey_press: scheduled handle_hotkey on event loop")

        loop = asyncio.get_running_loop()

        if sys.platform in ("darwin",) or sys.platform.startswith("linux"):
            from pynput.keyboard import GlobalHotKeys

            hotkey_expression = to_pynput_hotkey(self.shortcuts)
            logger.info(f"Registering hotkey '{hotkey_expression}' via pynput.keyboard.GlobalHotKeys")
            self._h_handle = GlobalHotKeys({hotkey_expression: on_hotkey_press})
            self._h_handle.start()
        else:
            from keyboard import add_hotkey

            hotkey_expression = "+".join(self.shortcuts)
            logger.info(f"Registering hotkey '{hotkey_expression}' via keyboard.add_hotkey")
            self._h_handle = add_hotkey(hotkey_expression, on_hotkey_press, args=(loop,))

    def force_end_callback(self):
        """该方法进行热键任务回收"""
        logger.info("force_end_callback: removing hotkey listener")
        if sys.platform in ("darwin",) or sys.platform.startswith("linux"):
            if self._h_handle:
                self._h_handle.stop()
                self._h_handle = None
        else:
            from keyboard import remove_hotkey

            remove_hotkey(self._h_handle)
