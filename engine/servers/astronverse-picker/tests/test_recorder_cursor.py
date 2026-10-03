import sys
from types import SimpleNamespace

import pyautogui
from astronverse.picker.core.recorder_core_win import cursor_pos


def test_cursor_pos_uses_pyautogui_off_win32(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(pyautogui, "position", lambda: SimpleNamespace(x=12.4, y=33.6))
    x, y = cursor_pos()
    assert (x, y) == (12, 34)
