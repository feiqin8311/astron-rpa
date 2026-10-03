import sys

import pytest
from PIL import Image


def test_picker_imports_on_darwin():
    if sys.platform != "darwin":
        pytest.skip("darwin only")
    from astronverse.vision_picker.core import picker

    assert picker.PickCore is not None
    assert picker.RectHandler is not None


def test_screenshot_resizes_retina_to_points(monkeypatch):
    from astronverse.vision_picker.core.core import IPickCore

    fake = Image.new("RGB", (2880, 1800), "white")
    monkeypatch.setattr(
        "astronverse.vision_picker.core.core.pyautogui.screenshot",
        lambda region=None: fake,
    )
    monkeypatch.setattr(
        "astronverse.vision_picker.core.core.pyautogui.size",
        lambda: (1440, 900),
    )
    img = IPickCore.screenshot()
    assert img.size == (1440, 900)


def test_screenshot_region_resizes_to_region_points(monkeypatch):
    from astronverse.vision_picker.core.core import IPickCore

    fake = Image.new("RGB", (400, 200), "white")
    monkeypatch.setattr(
        "astronverse.vision_picker.core.core.pyautogui.screenshot",
        lambda region=None: fake,
    )
    img = IPickCore.screenshot(region=(10, 20, 200, 100))
    assert img.size == (200, 100)


def test_foreground_rect_is_ltrb(monkeypatch):
    from astronverse.vision_picker.core.core_mac import RectHandler

    monkeypatch.setattr(
        RectHandler,
        "_frontmost_window",
        staticmethod(lambda: (42, "Safari", (100, 50, 800, 600))),
    )
    hwnd, title, rect = RectHandler.get_foreground_window_rect()
    assert hwnd == 42
    assert title == "Safari"
    assert rect == (100, 50, 900, 650)


def test_foreground_rect_falls_back_to_screen(monkeypatch):
    from astronverse.vision_picker.core import core_mac
    from astronverse.vision_picker.core.core_mac import RectHandler

    monkeypatch.setattr(
        RectHandler,
        "_frontmost_window",
        staticmethod(lambda: (None, None, None)),
    )
    monkeypatch.setattr(core_mac.pyautogui, "size", lambda: (1440, 900))
    hwnd, title, rect = RectHandler.get_foreground_window_rect()
    assert hwnd is None
    assert title == ""
    assert rect == (0, 0, 1440, 900)
