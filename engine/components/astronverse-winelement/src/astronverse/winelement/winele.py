import os
import sys

import pyautogui
from astronverse.actionlib import AtomicFormType, AtomicFormTypeMeta, DynamicsItem
from astronverse.actionlib.atomic import atomicMg
from astronverse.actionlib.types import WinPick
from astronverse.actionlib.utils import Credential, FileExistenceType, handle_existence
from astronverse.locator import PickerDomain, Point
from astronverse.winelement import (
    ElementInputType,
    MouseClickButton,
    MouseClickKeyboard,
    MouseClickType,
)
from astronverse.winelement.core import IWinEleCore
from astronverse.winelement.core_win import WinEleCore
from astronverse.winelement.error import *

WinEleCore: IWinEleCore = WinEleCore()

_SUPPORTED_DESKTOP_TYPES = (PickerDomain.UIA.value, PickerDomain.AX.value)


def _pick_type(pick: WinPick):
    return pick.get("elementData", {}).get("type", None)


def _darwin_click_key(key: str) -> str:
    # UI 提供 ctrl/shift/alt/win；darwin 上 win -> command，ctrl 保持 ctrl
    if key == "win":
        return "command"
    return key


def _ax_type_text(text: str) -> None:
    if text.isascii():
        pyautogui.write(text)
        return
    import pyperclip

    old = None
    try:
        old = pyperclip.paste()
    except Exception:
        old = None
    try:
        pyperclip.copy(text)
        pyautogui.hotkey("command", "v")
    finally:
        if old is not None:
            try:
                pyperclip.copy(old)
            except Exception:
                pass


def _input_text_element_ax(locator, input_type, text, credential_text, clear_first):
    control = locator.control()
    used_set_value = False
    if clear_first:
        try:
            used_set_value = bool(control.set_value(""))
        except Exception:
            used_set_value = False
        if not used_set_value:
            pyautogui.hotkey("command", "a")
            pyautogui.press("delete")
    else:
        pyautogui.press("end")

    if input_type == ElementInputType.CLIPBOARD:
        pyautogui.hotkey("command", "v")
        return

    payload = text
    if input_type == ElementInputType.Credential:
        payload = Credential.get_credential(credential_text)
    payload = "" if payload is None else str(payload)

    if used_set_value and control.set_value(payload):
        return
    _ax_type_text(payload)


class WinEle:
    @staticmethod
    @atomicMg.atomic(
        "WinEle",
        inputList=[
            atomicMg.param(
                "pick",
                formType=AtomicFormTypeMeta(type=AtomicFormType.PICK.value, params={"use": "ELEMENT"}),
            ),
        ],
    )
    def click_element(
        pick: WinPick,
        click_button: MouseClickButton = MouseClickButton.LEFT,
        click_type: MouseClickType = MouseClickType.CLICK,
        wait_time: float = 10.0,
        horizontals_offset: int = 0,
        verticals_offset: int = 0,
        keyboard_input: MouseClickKeyboard = MouseClickKeyboard.NONE,
    ):
        locator = WinEleCore.find(pick, wait_time)
        point = locator.point()

        modifier = keyboard_input.value
        if keyboard_input != MouseClickKeyboard.NONE and sys.platform == "darwin":
            modifier = _darwin_click_key(modifier)

        # 按下辅助按键
        if keyboard_input != MouseClickKeyboard.NONE:
            pyautogui.keyDown(modifier)
        try:
            locator.move(Point(point.x + int(horizontals_offset), point.y + int(verticals_offset)))
            pyautogui.click(
                clicks=1 if click_type == MouseClickType.CLICK else 2,
                button=click_button.value,
            )
        except Exception as e:
            raise e
        finally:
            # 记得释放
            if keyboard_input != MouseClickKeyboard.NONE:
                pyautogui.keyUp(modifier)

    @staticmethod
    @atomicMg.atomic(
        "WinEle",
        inputList=[
            atomicMg.param(
                "pick",
                formType=AtomicFormTypeMeta(type=AtomicFormType.PICK.value, params={"use": "ELEMENT"}),
            ),
            atomicMg.param(
                "file_path",
                formType=AtomicFormTypeMeta(
                    type=AtomicFormType.INPUT_VARIABLE_PYTHON_FILE.value,
                    params={"filters": [], "file_type": "folder"},
                ),
            ),
        ],
    )
    def screenshot_element(
        pick: WinPick,
        file_path: str,
        file_name: str = "桌面元素截图",
        exist_type: FileExistenceType = FileExistenceType.RENAME,
    ):
        if not file_name.endswith(".png"):
            file_name += ".png"

        new_file_path = handle_existence(os.path.join(file_path, file_name), exist_type)
        if not new_file_path:
            raise BaseException(PATH_ERROR, "拾取或保存路径有误")

        locator = WinEleCore.find(pick=pick)
        window_rect = locator.rect()
        width = window_rect.width()
        height = window_rect.height()
        rect = (
            window_rect.left,
            window_rect.top,
            width,
            height,
        )
        screenshot = pyautogui.screenshot(region=rect)
        # Retina: pyautogui 截到像素尺寸，缩回点尺寸后再保存
        if sys.platform == "darwin" and width > 0 and height > 0:
            if screenshot.size != (width, height):
                screenshot = screenshot.resize((width, height))
        screenshot.save(new_file_path)

    @staticmethod
    @atomicMg.atomic(
        "WinEle",
        inputList=[
            atomicMg.param(
                "pick",
                formType=AtomicFormTypeMeta(type=AtomicFormType.PICK.value, params={"use": "ELEMENT"}),
            ),
        ],
    )
    def hover_element(pick: WinPick, wait_time: float = 10.0):
        locator = WinEleCore.find(pick, wait_time)
        locator.hover()

    @staticmethod
    @atomicMg.atomic(
        "WinEle",
        inputList=[
            atomicMg.param(
                "pick",
                formType=AtomicFormTypeMeta(type=AtomicFormType.PICK.value, params={"use": "ELEMENT"}),
            ),
            atomicMg.param(
                "text",
                dynamics=[
                    DynamicsItem(
                        key="$this.text.show",
                        expression="return $this.input_type.value == '{}'".format(ElementInputType.KEYBOARD.value),
                    )
                ],
            ),
            atomicMg.param(
                "credential_text",
                formType=AtomicFormTypeMeta(type=AtomicFormType.SELECT.value, params={"filters": ["credential"]}),
                dynamics=[
                    DynamicsItem(
                        key="$this.credential_text.show",
                        expression=f"return $this.input_type.value == '{ElementInputType.Credential.value}'",
                    )
                ],
            ),
        ],
    )
    def input_text_element(
        pick: WinPick,
        input_type: ElementInputType = ElementInputType.KEYBOARD,
        text: str = "",
        credential_text: str = "",
        clear_first: bool = True,
        wait_time: float = 10.0,
    ):
        pick_type = _pick_type(pick)
        if pick_type not in _SUPPORTED_DESKTOP_TYPES:
            raise BaseException(UNPICKABLE, "类型不支持{}".format(pick.get("type", None)))

        locator = WinEleCore.find(pick, wait_time)
        locator.move()
        pyautogui.click()

        if pick_type == PickerDomain.AX.value and sys.platform == "darwin":
            _input_text_element_ax(locator, input_type, text, credential_text, clear_first)
            return

        import uiautomation

        if clear_first:
            window_control = locator.control()
            if window_control.ControlTypeName == uiautomation.EditControl.ControlTypeName:
                window_control.GetValuePattern().SetValue("")
            else:
                pyautogui.press("home")
                pyautogui.hotkey("ctrl", "a")
                pyautogui.press("delete")
        else:
            pyautogui.press("end")

        if input_type == ElementInputType.KEYBOARD:
            uiautomation.SendKeys(text)
        elif input_type == ElementInputType.CLIPBOARD:
            pyautogui.hotkey("ctrl", "v")
        elif input_type == ElementInputType.Credential:
            uiautomation.SendKeys(Credential.get_credential(credential_text))

    @staticmethod
    @atomicMg.atomic(
        "WinEle",
        inputList=[
            atomicMg.param(
                "pick",
                formType=AtomicFormTypeMeta(type=AtomicFormType.PICK.value, params={"use": "ELEMENT"}),
            ),
        ],
        outputList=[atomicMg.param("ele_text", types="Str")],
    )
    def get_element_text(pick: WinPick, wait_time: float = 10.0):
        locator = WinEleCore.find(pick, wait_time)
        control = locator.control()
        name = control.Name
        if sys.platform == "darwin" and not name:
            value = getattr(control, "value", None)
            if value:
                return value
        return name

    @staticmethod
    @atomicMg.atomic(
        "WinEle",
        outputList=[
            atomicMg.param("get_similar_ele", types="List"),
        ],
    )
    def similar(pick: WinPick, wait_time: int = 10) -> list:
        if _pick_type(pick) not in _SUPPORTED_DESKTOP_TYPES:
            raise BaseException(UNPICKABLE, "类型不支持{}".format(pick.get("type", None)))

        locator_list = WinEleCore.find(pick, wait_time)
        res_list = []
        if locator_list:
            if not isinstance(locator_list, list):
                locator_list = [locator_list]
            for locator in locator_list:
                win_pick = WinPick()
                win_pick.locator = locator
                res_list.append(win_pick)
        return res_list
