from astronverse.locator import Rect
from astronverse.locator.core.atspi_common import (
    compensate_gtk4_rect,
    gtk4_point_to_window,
    is_gtk4_toolkit,
    origin_frame_for_pid,
    parse_gtk_frame_extents,
    parse_xdotool_location,
    parse_xprop_pid,
    parse_xwininfo_origin,
)


def test_parse_xdotool_location():
    text = "X=100\nY=200\nSCREEN=0\nWINDOW=12345\n"
    assert parse_xdotool_location(text) == (100, 200, 12345)


def test_parse_xprop_pid():
    assert parse_xprop_pid("_NET_WM_PID(CARDINAL) = 4321") == 4321
    assert parse_xprop_pid('WM_CLASS(STRING) = "x"') == 0


def test_parse_gtk_frame_extents():
    assert parse_gtk_frame_extents("_GTK_FRAME_EXTENTS(CARDINAL) = 10, 10, 30, 10") == (10, 30)
    assert parse_gtk_frame_extents("") == (0, 0)


def test_parse_xwininfo_origin():
    text = "Absolute upper-left X:  48\nAbsolute upper-left Y:  72\n"
    assert parse_xwininfo_origin(text) == (48, 72)


def test_compensate_gtk4_rect():
    rect = compensate_gtk4_rect(10, 40, 200, 100, origin_x=100, origin_y=50, frame_left=10, frame_top=30)
    assert rect == Rect(100, 60, 300, 160)


def test_gtk4_point_to_window():
    assert gtk4_point_to_window(150, 90, 100, 50, 10, 30) == (60, 70)


def test_is_gtk4_toolkit():
    assert is_gtk4_toolkit("GTK", "4.14.0") is True
    assert is_gtk4_toolkit("gtk4", "1") is True
    assert is_gtk4_toolkit("GTK", "3.24") is False
    assert is_gtk4_toolkit("Qt", "6") is False


def test_origin_frame_for_pid_uses_cache():
    from astronverse.locator.core import atspi_common

    atspi_common._window_meta[99] = (4321, (48, 72), (10, 30))
    try:
        assert origin_frame_for_pid(4321) == ((48, 72), (10, 30))
        assert origin_frame_for_pid(0) == ((0, 0), (0, 0))
    finally:
        atspi_common._window_meta.pop(99, None)
