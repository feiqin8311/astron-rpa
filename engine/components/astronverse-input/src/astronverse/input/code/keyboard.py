import os
import subprocess
import sys

import pyautogui
from astronverse.baseline.logger.logger import logger
from pynput.keyboard import Controller

language_map = {0x0409: "xkb:us::eng", 0x0804: "zh_CN"}  # 英文  # 中文


class Keyboard:
    def __init__(self):
        pyautogui.FAILSAFE = False

    @staticmethod
    def change_language(language: int):
        if sys.platform == "darwin":
            return
        if sys.platform == "win32":
            import win32api
            import win32gui
            from win32con import WM_INPUTLANGCHANGEREQUEST

            hwnd = win32gui.GetForegroundWindow()
            im_list = win32api.GetKeyboardLayoutList()
            im_list = list(map(hex, im_list))
            win32api.SendMessage(hwnd, WM_INPUTLANGCHANGEREQUEST, 0, language)
        else:
            try:
                # 先查询当前输入法状态
                result = subprocess.run(
                    ["fcitx-remote"],
                    timeout=5,
                    capture_output=True,
                    text=True,
                    check=False,
                    encoding="utf-8",
                    errors="replace",
                )
                if result.returncode != 0:
                    logger.info("无法查询fcitx状态，可能fcitx未运行")
                    return

                current_status = int(result.stdout.strip())
                logger.info(f"当前输入法状态: {current_status}")

                # 根据language参数确定期望状态
                if language == 0x0409:  # 英文 - 期望状态为1（未激活）
                    expected_status = 1
                elif language == 0x0804:  # 中文 - 期望状态为2（激活）
                    expected_status = 2
                else:
                    logger.info(f"不支持的语言代码: {hex(language)}")
                    return

                # 判断是否需要切换
                if current_status != expected_status:
                    logger.info(f"需要切换输入法：从状态{current_status}切换到状态{expected_status}")
                    # 执行切换命令
                    subprocess.run(
                        ["fcitx-remote", "-t"],
                        timeout=5,
                        check=False,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            except Exception as e:
                (logger.info(f"切换输入法时发生错误: {e}"))

    @staticmethod
    def write_char(char: str):
        """
        键盘写字符
        keyboard.type()在输入法英文状态下可同时输入中英文字符
        """
        keyboard = Controller()
        return keyboard.type(char)

    @staticmethod
    def write_unicode(text: str, delay: float = 0):
        """
        使用 Windows API 输入 Unicode 文本
        支持中英文、emoji等所有Unicode字符，不依赖输入法状态

        Args:
            text: 要输入的文本
            delay: 每个字符之间的延迟（秒），默认0.01秒

        Example:
            Keyboard.write_unicode("Hello世界！😀")
        """
        if sys.platform == "win32":
            from astronverse.input.code.windows_input import type_text

            return type_text(text, delay=delay)
        else:
            # Linux/Mac 回退到 pynput
            keyboard = Controller()
            return keyboard.type(text)

    @staticmethod
    def _map_key(key):
        if sys.platform == "darwin" and isinstance(key, str) and key.lower() in ("win", "winleft", "winright"):
            return "command"
        return key

    @staticmethod
    def press(keys, presses: int = 1, interval: float = 0.0):
        """
        敲键
        eg1: pyautogui.press(['left', 'left', 'left'])
        eg2: pyautogui.press('left')
        :param keys: 可以是数组 https://pyautogui.readthedocs.io/en/latest/keyboard.html#keyboard-keys
        """
        if isinstance(keys, (list, tuple)):
            keys = [Keyboard._map_key(k) for k in keys]
        else:
            keys = Keyboard._map_key(keys)
        return pyautogui.press(keys=keys, presses=presses, interval=interval)

    @staticmethod
    def hotkey(*args, **kwargs):
        """
        热键
        eg: pyautogui.hotkey('ctrl', 'shift', 'esc')
        """
        args = tuple(Keyboard._map_key(k) for k in args)
        return pyautogui.hotkey(*args, **kwargs)

    @staticmethod
    def key_down(key):
        """
        按键
        """
        return pyautogui.keyDown(key=Keyboard._map_key(key))

    @staticmethod
    def key_up(key):
        """
        松键
        :param key: 键 https://pyautogui.readthedocs.io/en/latest/keyboard.html#keyboard-keys
        :return:
        """
        return pyautogui.keyUp(key=Keyboard._map_key(key))

    @staticmethod
    def get_drive_path():
        script_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(script_dir)
        relative_dir = os.path.join("VK", "bin", "Debug", "VK.exe")
        drive_path = os.path.join(parent_dir, relative_dir)
        return drive_path
