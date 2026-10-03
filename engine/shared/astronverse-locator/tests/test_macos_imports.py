import subprocess
import sys
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest
from astronverse.locator import Rect
from astronverse.locator.core.web_locator import WebFactory
from astronverse.locator.utils import window
from astronverse.locator.utils.process import get_java_process


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-specific tests")
@pytest.mark.parametrize(
    "module_name",
    [
        "astronverse.locator",
        "astronverse.locator.locator",
        "astronverse.locator.core.web_locator",
        "astronverse.locator.utils.window",
        "astronverse.locator.utils.move",
        "astronverse.locator.utils.process",
    ],
)
def test_subprocess_imports_succeed_on_darwin(module_name):
    """Subprocess imports of astronverse-locator modules must succeed cleanly on macOS."""
    res = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Importing {module_name} failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-specific tests")
def test_screen_scale_helpers_on_darwin():
    """Verify screen scale rate helpers on macOS."""
    # Effective scale for coordinate math on macOS must be 1.0 (pyautogui / Quartz coordinates are in points)
    runtime_scale = window.get_screen_scale_rate_runtime()
    assert runtime_scale == 1.0

    # Backing scale factor should be >= 1.0 (typically 2.0 on Retina)
    backing_scale = window.get_screen_scale_rate_new()
    assert isinstance(backing_scale, float)
    assert backing_scale >= 1.0


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-specific tests")
def test_darwin_top_browser_window_filtering():
    """Unit test for top_browser Quartz window filtering on macOS."""
    mock_windows = [
        # Window 1: Non-zero layer (e.g. menu bar or system overlay) -> should be skipped
        {
            "kCGWindowLayer": 25,
            "kCGWindowOwnerName": "Google Chrome",
            "kCGWindowName": "Overlay",
            "kCGWindowNumber": 101,
            "kCGWindowOwnerPID": 2001,
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 1920, "Height": 30},
        },
        # Window 2: Layer 0, but wrong owner -> should be skipped
        {
            "kCGWindowLayer": 0,
            "kCGWindowOwnerName": "Finder",
            "kCGWindowName": "Desktop",
            "kCGWindowNumber": 102,
            "kCGWindowOwnerPID": 2002,
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 1920, "Height": 1080},
        },
        # Window 3: Layer 0, zero-sized/tiny helper window -> should be skipped
        {
            "kCGWindowLayer": 0,
            "kCGWindowOwnerName": "Google Chrome",
            "kCGWindowName": "",
            "kCGWindowNumber": 103,
            "kCGWindowOwnerPID": 2003,
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 10, "Height": 10},
        },
        # Window 4: Layer 0, matching browser window (frontmost Chrome) -> MATCH
        {
            "kCGWindowLayer": 0,
            "kCGWindowOwnerName": "Google Chrome",
            "kCGWindowName": "Google - Google Chrome",
            "kCGWindowNumber": 104,
            "kCGWindowOwnerPID": 2004,
            "kCGWindowBounds": {"X": 100, "Y": 50, "Width": 1200, "Height": 800},
        },
        # Window 5: Layer 0, another Chrome window behind Window 4 -> should NOT be picked
        {
            "kCGWindowLayer": 0,
            "kCGWindowOwnerName": "Google Chrome",
            "kCGWindowName": "Secondary - Google Chrome",
            "kCGWindowNumber": 105,
            "kCGWindowOwnerPID": 2004,
            "kCGWindowBounds": {"X": 200, "Y": 150, "Width": 1000, "Height": 700},
        },
    ]

    with (
        patch("astronverse.locator.core.ax_common.find_apps", return_value=[]),
        patch("Quartz.CGWindowListCopyWindowInfo", return_value=mock_windows),
    ):
        ctrl = window.top_browser(app_name="chrome")
        assert ctrl is not None
        assert ctrl.NativeWindowHandle == 104
        assert ctrl.ClassName == "Google Chrome"
        assert ctrl.ProcessId == 2004
        assert ctrl.BoundingRectangle.left == 100
        assert ctrl.BoundingRectangle.top == 50
        assert ctrl.BoundingRectangle.right == 1300
        assert ctrl.BoundingRectangle.bottom == 850
        assert ctrl.BoundingRectangle.width() == 1200
        assert ctrl.BoundingRectangle.height() == 800


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-specific tests")
def test_darwin_top_browser_not_found():
    """Verify top_browser returns None when no matching window is found."""
    mock_windows = [
        {
            "kCGWindowLayer": 0,
            "kCGWindowOwnerName": "Finder",
            "kCGWindowName": "Desktop",
            "kCGWindowNumber": 102,
            "kCGWindowOwnerPID": 2002,
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 1920, "Height": 1080},
        }
    ]

    with (
        patch("astronverse.locator.core.ax_common.find_apps", return_value=[]),
        patch("Quartz.CGWindowListCopyWindowInfo", return_value=mock_windows),
    ):
        ctrl = window.top_browser(app_name="firefox")
        assert ctrl is None


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-specific tests")
def test_web_locator_viewport_calc_on_darwin():
    """Test web locator viewport calculation on macOS."""
    mock_ctrl = window.DarwinWindowControl(
        NativeWindowHandle=123,
        BoundingRectangle=Rect(left=50, top=30, right=1250, bottom=830),
        Name="Browser",
        ClassName="Google Chrome",
        ProcessId=999,
    )

    with (
        patch("astronverse.locator.core.web_locator.top_browser", return_value=mock_ctrl),
        patch("astronverse.locator.core.web_locator._ax_webarea_origin", return_value=None),
    ):
        # 1. Default fallback toolbar height (85px)
        top, left = WebFactory.__get_web_top__({}, "chrome")
        assert top == 30 + 85
        assert left == 50

        # 2. Dynamic toolbar height with outerHeight and innerHeight provided
        ele_with_dims = {"outerHeight": 800, "innerHeight": 710}
        top, left = WebFactory.__get_web_top__(ele_with_dims, "chrome")
        assert top == 30 + (800 - 710)
        assert left == 50


class _FakeAX:
    def __init__(
        self,
        role: str,
        rect: Optional[Rect] = None,
        children: Optional[list] = None,
        minimized: bool = False,
        title: str = "",
    ):
        self.role = role
        self.rect = rect or Rect(0, 0, 0, 0)
        self.children = children or []
        self.minimized = minimized
        self.title = title


def _fake_ax_attr(el: Any, name: str, default: Any = None) -> Any:
    if not isinstance(el, _FakeAX):
        return default
    if name == "AXRole":
        return el.role
    if name == "AXMinimized":
        return el.minimized
    if name == "AXTitle":
        return el.title
    return default


def _fake_ax_children(el: Any) -> list:
    return list(el.children) if isinstance(el, _FakeAX) else []


def _fake_ax_rect(el: Any) -> Optional[Rect]:
    return el.rect if isinstance(el, _FakeAX) else None


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-specific tests")
def test_darwin_top_browser_ax_path():
    """top_browser prefers AX find_apps / first non-minimised window on macOS."""
    win = _FakeAX("AXWindow", rect=Rect(10, 20, 810, 620), title="Tab")
    raise_window = MagicMock()

    with (
        patch("astronverse.locator.core.ax_common.find_apps", return_value=[4321]) as find_apps,
        patch("astronverse.locator.core.ax_common.app_element", return_value=object()),
        patch("astronverse.locator.core.ax_common.app_windows", return_value=[win]),
        patch("astronverse.locator.core.ax_common.ax_attr", side_effect=_fake_ax_attr),
        patch("astronverse.locator.core.ax_common.ax_rect", side_effect=_fake_ax_rect),
        patch("astronverse.locator.core.ax_common.raise_window", raise_window),
    ):
        ctrl = window.top_browser(app_name="chrome")

    find_apps.assert_called_once_with("Google Chrome", "com.google.Chrome")
    raise_window.assert_called_once_with(win, 4321)
    assert ctrl is not None
    assert ctrl.ProcessId == 4321
    assert ctrl.BoundingRectangle.left == 10
    assert ctrl.BoundingRectangle.top == 20
    assert ctrl.Name == "Tab"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-specific tests")
def test_web_locator_ax_webarea_origin_on_darwin():
    """AXWindow > AXGroup > AXWebArea(at 0,120) => origin (0, 120)."""
    web = _FakeAX("AXWebArea", rect=Rect(0, 120, 800, 920))
    group = _FakeAX("AXGroup", rect=Rect(0, 80, 800, 920), children=[web])
    win = _FakeAX("AXWindow", rect=Rect(0, 0, 800, 920), children=[group])
    mock_ctrl = window.DarwinWindowControl(
        NativeWindowHandle=0,
        BoundingRectangle=Rect(0, 0, 800, 920),
        ProcessId=1234,
    )

    with (
        patch("astronverse.locator.core.web_locator.top_browser", return_value=mock_ctrl),
        patch("astronverse.locator.core.ax_common.app_element", return_value=object()),
        patch("astronverse.locator.core.ax_common.app_windows", return_value=[win]),
        patch("astronverse.locator.core.ax_common.ax_attr", side_effect=_fake_ax_attr),
        patch("astronverse.locator.core.ax_common.ax_children", side_effect=_fake_ax_children),
        patch("astronverse.locator.core.ax_common.ax_rect", side_effect=_fake_ax_rect),
        patch("astronverse.locator.core.ax_common.raise_window"),
    ):
        top, left = WebFactory.__get_web_top__({}, "chrome")
    assert top == 120
    assert left == 0


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-specific tests")
def test_web_locator_ax_webarea_fallback_on_darwin():
    """No AXWebArea => window-top + toolbar estimate."""
    group = _FakeAX("AXGroup", rect=Rect(50, 30, 1250, 830), children=[])
    win = _FakeAX("AXWindow", rect=Rect(50, 30, 1250, 830), children=[group])
    mock_ctrl = window.DarwinWindowControl(
        NativeWindowHandle=123,
        BoundingRectangle=Rect(left=50, top=30, right=1250, bottom=830),
        Name="Browser",
        ClassName="Google Chrome",
        ProcessId=999,
    )

    with (
        patch("astronverse.locator.core.web_locator.top_browser", return_value=mock_ctrl),
        patch("astronverse.locator.core.ax_common.app_element", return_value=object()),
        patch("astronverse.locator.core.ax_common.app_windows", return_value=[win]),
        patch("astronverse.locator.core.ax_common.ax_attr", side_effect=_fake_ax_attr),
        patch("astronverse.locator.core.ax_common.ax_children", side_effect=_fake_ax_children),
        patch("astronverse.locator.core.ax_common.ax_rect", side_effect=_fake_ax_rect),
        patch("astronverse.locator.core.ax_common.raise_window"),
    ):
        top, left = WebFactory.__get_web_top__({}, "chrome")
    assert top == 30 + 85
    assert left == 50


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-specific tests")
def test_get_java_process_on_darwin():
    """Verify get_java_process executes cleanly on macOS without crashing."""
    pids, names = get_java_process()
    assert isinstance(pids, list)
    assert isinstance(names, list)
