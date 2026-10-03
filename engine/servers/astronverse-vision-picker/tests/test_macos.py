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
