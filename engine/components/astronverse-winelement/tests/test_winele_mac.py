import sys

import pytest
from astronverse.actionlib.types import WinPick
from astronverse.locator import Point, Rect
from astronverse.winelement import ElementInputType, MouseClickKeyboard
from astronverse.winelement import winele as winele_mod
from astronverse.winelement.winele import WinEle


class FakeControl:
    def __init__(self, name="", value=None, settable=True):
        self.Name = name
        self.value = value
        self._settable = settable
        self.values = []

    def set_value(self, text):
        if not self._settable:
            return False
        self.values.append(text)
        self.value = text
        return True


class FakeLocator:
    def __init__(self, control=None, rect=None, point=None):
        self._control = control or FakeControl()
        self._rect = rect or Rect(0, 0, 50, 20)
        self._point = point or Point(25, 10)
        self.moved = False
        self.hovered = False

    def control(self):
        return self._control

    def rect(self):
        return self._rect

    def point(self):
        return self._point

    def move(self, point=None, duration=0.4):
        self.moved = True

    def hover(self, point=None):
        self.hovered = True


def _ax_pick():
    return WinPick({"elementData": {"type": "ax", "path": [{"name": "x"}]}})


def test_click_maps_win_not_ctrl(monkeypatch):
    loc = FakeLocator()
    monkeypatch.setattr(winele_mod.WinEleCore, "find", staticmethod(lambda pick, wait_time=10: loc))
    keys = []
    monkeypatch.setattr(winele_mod.pyautogui, "keyDown", lambda k: keys.append(("down", k)))
    monkeypatch.setattr(winele_mod.pyautogui, "keyUp", lambda k: keys.append(("up", k)))
    monkeypatch.setattr(winele_mod.pyautogui, "click", lambda **k: keys.append(("click", k)))
    WinEle.click_element(pick=_ax_pick(), keyboard_input=MouseClickKeyboard.WIN)
    if sys.platform == "darwin":
        assert ("down", "command") in keys
        assert ("up", "command") in keys
        assert ("down", "win") not in keys
    WinEle.click_element(pick=_ax_pick(), keyboard_input=MouseClickKeyboard.CTRL)
    if sys.platform == "darwin":
        assert ("down", "ctrl") in keys
        assert ("down", "command") in keys  # from previous call only for win


def test_screenshot_resizes_on_darwin(monkeypatch, tmp_path):
    loc = FakeLocator(rect=Rect(0, 0, 10, 5))
    monkeypatch.setattr(winele_mod.WinEleCore, "find", staticmethod(lambda pick, wait_time=10, **k: loc))
    monkeypatch.setattr(winele_mod, "handle_existence", lambda p, t: str(tmp_path / "out.png"))

    class Img:
        def __init__(self, size):
            self.size = size
            self.saved = None
            self.resized_to = None

        def resize(self, size):
            self.resized_to = size
            self.size = size
            return self

        def save(self, path):
            self.saved = path

    img = Img((20, 10))
    monkeypatch.setattr(winele_mod.pyautogui, "screenshot", lambda region=None: img)
    WinEle.screenshot_element(pick=_ax_pick(), file_path=str(tmp_path), file_name="shot")
    if sys.platform == "darwin":
        assert img.resized_to == (10, 5)
    assert img.saved.endswith("out.png")


def test_input_ax_set_value(monkeypatch):
    if sys.platform != "darwin":
        pytest.skip("ax input path is darwin-only")
    ctrl = FakeControl(settable=True)
    loc = FakeLocator(control=ctrl)
    monkeypatch.setattr(winele_mod.WinEleCore, "find", staticmethod(lambda pick, wait_time=10: loc))
    monkeypatch.setattr(winele_mod.pyautogui, "click", lambda **k: None)
    WinEle.input_text_element(pick=_ax_pick(), input_type=ElementInputType.KEYBOARD, text="hello", clear_first=True)
    assert ctrl.values == ["", "hello"]


def test_input_ax_fallback_write(monkeypatch):
    if sys.platform != "darwin":
        pytest.skip("ax input path is darwin-only")
    ctrl = FakeControl(settable=False)
    loc = FakeLocator(control=ctrl)
    monkeypatch.setattr(winele_mod.WinEleCore, "find", staticmethod(lambda pick, wait_time=10: loc))
    written = []
    monkeypatch.setattr(winele_mod.pyautogui, "click", lambda **k: None)
    monkeypatch.setattr(winele_mod.pyautogui, "hotkey", lambda *a: written.append(("hot", a)))
    monkeypatch.setattr(winele_mod.pyautogui, "press", lambda k: written.append(("press", k)))
    monkeypatch.setattr(winele_mod.pyautogui, "write", lambda t: written.append(("write", t)))
    WinEle.input_text_element(pick=_ax_pick(), input_type=ElementInputType.KEYBOARD, text="abc", clear_first=True)
    assert ("hot", ("command", "a")) in written
    assert ("write", "abc") in written


def test_get_element_text_prefers_value(monkeypatch):
    loc = FakeLocator(control=FakeControl(name="", value="typed"))
    monkeypatch.setattr(winele_mod.WinEleCore, "find", staticmethod(lambda pick, wait_time=10: loc))
    text = WinEle.get_element_text(pick=_ax_pick())
    if sys.platform == "darwin":
        assert text == "typed"
    else:
        assert text == ""


def test_similar_allows_ax(monkeypatch):
    loc = FakeLocator()
    monkeypatch.setattr(winele_mod.WinEleCore, "find", staticmethod(lambda pick, wait_time=10: loc))
    res = WinEle.similar(pick=_ax_pick())
    assert len(res) == 1
    assert res[0].locator is loc
