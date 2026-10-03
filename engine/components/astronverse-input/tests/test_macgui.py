import sys

import pytest
from astronverse.actionlib.types import WinPick
from astronverse.input import KeyboardType
from astronverse.input.code.keyboard import Keyboard
from astronverse.input.gui_key import GuiKeyBoard
from astronverse.locator import Rect


class FakeAX:
    def __init__(self, title="", subrole="AXStandardWindow", pid=10, children=None, rect=None, role="AXWindow"):
        self.title = title
        self.subrole = subrole
        self.pid = pid
        self.children = children or []
        self.role = role
        self._rect = rect or Rect(0, 0, 200, 100)


def _pick(name="", cls="", app=""):
    return WinPick(
        {
            "elementData": {
                "type": "ax",
                "app": app,
                "path": [{"tag_name": "AXWindow", "name": name, "cls": cls}],
            }
        }
    )


def _patch(monkeypatch, windows):
    from astronverse.input.code import macgui

    def fake_attr(el, name, default=None):
        if not isinstance(el, FakeAX):
            return default
        if name == "AXTitle":
            return el.title
        if name in ("AXDescription", "AXHelp"):
            return ""
        if name == "AXSubrole":
            return el.subrole
        if name == "AXRole":
            return el.role
        if name == "AXChildren":
            return el.children
        return default

    monkeypatch.setattr(macgui.ax_common, "ax_attr", fake_attr)
    monkeypatch.setattr(macgui.ax_common, "ax_children", lambda el: list(getattr(el, "children", []) or []))
    monkeypatch.setattr(macgui.ax_common, "ax_rect", lambda el: getattr(el, "_rect", None))
    monkeypatch.setattr(macgui.ax_common, "pid_of", lambda el: getattr(el, "pid", None))
    monkeypatch.setattr(macgui.ax_common, "app_element", lambda pid: FakeAX(title=str(pid), pid=pid, role="AXApplication"))
    monkeypatch.setattr(macgui.ax_common, "app_windows", lambda app: [w for w in windows if w.pid == app.pid])
    monkeypatch.setattr(macgui.ax_common, "find_apps", lambda name, bundle=None: list({w.pid for w in windows}))
    monkeypatch.setattr(macgui, "_regular_app_pids", lambda: list({w.pid for w in windows}))
    return macgui


def test_window_find_and_info(monkeypatch):
    content = FakeAX(title="body", role="AXScrollArea", rect=Rect(0, 22, 200, 100), pid=10)
    win = FakeAX(title="Doc", pid=10, children=[content], rect=Rect(0, 0, 200, 100))
    macgui = _patch(monkeypatch, [win])

    handler = macgui.window_find(_pick(name="Doc"))
    assert handler.title == "Doc"
    info = macgui.window_info(handler)
    assert info.position == (0, 0, 200, 100)
    assert info.client_position == (0, 22, 200, 100)


def test_window_find_missing(monkeypatch):
    macgui = _patch(monkeypatch, [FakeAX(title="A")])
    with pytest.raises(Exception, match="未找到"):
        macgui.window_find(_pick(name="Nope"))


def test_window_top(monkeypatch):
    win = FakeAX(title="T")
    macgui = _patch(monkeypatch, [win])
    raised = []
    monkeypatch.setattr(macgui.ax_common, "raise_window", lambda el, pid=None: raised.append((el, pid)))
    handler = macgui.window_find(_pick(name="T"))
    macgui.window_top(handler)
    assert raised == [(win, 10)]


def test_keyboard_maps_win_to_command(monkeypatch):
    seen = []
    monkeypatch.setattr("pyautogui.keyDown", lambda key: seen.append(("down", key)))
    monkeypatch.setattr("pyautogui.keyUp", lambda key: seen.append(("up", key)))
    monkeypatch.setattr("pyautogui.hotkey", lambda *a, **k: seen.append(("hot", a)))
    Keyboard.key_down("win")
    Keyboard.key_up("win")
    Keyboard.hotkey("win", "c")
    if sys.platform == "darwin":
        assert seen == [("down", "command"), ("up", "command"), ("hot", ("command", "c"))]
    else:
        assert seen[0][1] == "win"


def test_driver_mode_errors_on_darwin():
    if sys.platform != "darwin":
        pytest.skip("darwin only")
    with pytest.raises(Exception) as ei:
        GuiKeyBoard.keyboard(keyboard_type=KeyboardType.DRIVER, message="x")
    assert "VK.exe" in getattr(ei.value, "message", "") or "VK.exe" in str(ei.value)
