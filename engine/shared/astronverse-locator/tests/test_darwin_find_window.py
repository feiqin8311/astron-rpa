from astronverse.locator.utils.window import (
    darwin_cls_is_ax,
    darwin_window_cls_matches,
    darwin_window_name_matches,
)


def test_darwin_cls_is_ax():
    assert darwin_cls_is_ax("AXWindow") is True
    assert darwin_cls_is_ax("AXStandardWindow") is True
    assert darwin_cls_is_ax("Chrome_WidgetWin_1") is False
    assert darwin_cls_is_ax("") is False


def test_darwin_window_name_matches():
    assert darwin_window_name_matches("Inbox - Gmail", "Inbox - Gmail") is True
    assert darwin_window_name_matches("Inbox - Gmail", "Other") is False
    assert darwin_window_name_matches("Inbox", "") is True


def test_darwin_window_cls_matches_ignores_win32_class():
    assert darwin_window_cls_matches("AXWindow", "AXWindow") is True
    assert darwin_window_cls_matches("AXStandardWindow", "AXWindow") is False
    assert darwin_window_cls_matches("AXWindow", "Chrome_WidgetWin_1") is True
    assert darwin_window_cls_matches("Google Chrome", "") is True
