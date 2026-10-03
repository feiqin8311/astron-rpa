import sys
from typing import Optional

import pytest
from astronverse.actionlib.types import WinPick
from astronverse.locator import Rect
from astronverse.window import WindowSizeType
from astronverse.window.core_mac import MacWindow, UITreeCore, WindowsCore
from astronverse.window.error import BaseException


class FakeAX:
    def __init__(
        self,
        role="AXWindow",
        title="",
        subrole="AXStandardWindow",
        pid=100,
        children=None,
        attrs=None,
        rect=None,
    ):
        self.role = role
        self.title = title
        self.subrole = subrole
        self.pid = pid
        self.children = children or []
        self.attrs = attrs or {}
        self._rect = rect or Rect(10, 20, 210, 220)


def _pick(name="", cls="", app="", bundle_id=""):
    return WinPick(
        {
            "elementData": {
                "type": "ax",
                "app": app,
                "bundle_id": bundle_id,
                "path": [{"tag_name": "AXWindow", "name": name, "cls": cls}],
            }
        }
    )


def _patch_ax(monkeypatch, windows_by_pid: dict[int, list[FakeAX]], apps: Optional[dict] = None):
    from astronverse.window import core_mac

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
        if name == "AXWindows":
            return windows_by_pid.get(el.pid, [el])
        return el.attrs.get(name, default)

    def fake_children(el):
        if isinstance(el, FakeAX):
            return list(el.children)
        return []

    def fake_rect(el):
        if isinstance(el, FakeAX):
            return el._rect
        return None

    def fake_pid(el):
        if isinstance(el, FakeAX):
            return el.pid
        return None

    def fake_app_element(pid):
        return FakeAX(role="AXApplication", title=str(pid), pid=pid, children=windows_by_pid.get(pid, []))

    def fake_app_windows(app_el):
        return windows_by_pid.get(app_el.pid, [])

    def fake_find_apps(app_name, bundle_id=None):
        if apps is None:
            return list(windows_by_pid.keys())
        keys = []
        for pid, meta in apps.items():
            if bundle_id and meta.get("bundle_id", "").lower() == bundle_id.lower():
                keys.append(pid)
            elif app_name and meta.get("name", "").lower() == app_name.lower():
                keys.append(pid)
        return keys

    monkeypatch.setattr(core_mac.ax_common, "ax_attr", fake_attr)
    monkeypatch.setattr(core_mac.ax_common, "ax_children", fake_children)
    monkeypatch.setattr(core_mac.ax_common, "ax_rect", fake_rect)
    monkeypatch.setattr(core_mac.ax_common, "pid_of", fake_pid)
    monkeypatch.setattr(core_mac.ax_common, "app_element", fake_app_element)
    monkeypatch.setattr(core_mac.ax_common, "app_windows", fake_app_windows)
    monkeypatch.setattr(core_mac.ax_common, "find_apps", fake_find_apps)
    monkeypatch.setattr(core_mac, "_regular_app_pids", lambda: list(windows_by_pid.keys()))
    return core_mac


def test_find_exact_then_contains(monkeypatch):
    w1 = FakeAX(title="Downloads")
    w2 = FakeAX(title="Downloads — Finder", pid=101)
    core_mac = _patch_ax(monkeypatch, {100: [w1], 101: [w2]}, apps={100: {"name": "Finder"}, 101: {"name": "Finder"}})

    found = WindowsCore.find(_pick(name="Downloads", app="Finder"))
    assert found.title == "Downloads"
    assert found.ax_window is w1

    found2 = WindowsCore.find(_pick(name="Finder", app="Finder"))
    assert found2.title == "Downloads — Finder"


def test_find_windows_style_no_app(monkeypatch):
    w = FakeAX(title="Notes")
    _patch_ax(monkeypatch, {200: [w]})
    found = WindowsCore.find(_pick(name="Notes"))
    assert found.pid == 200


def test_find_missing_raises(monkeypatch):
    _patch_ax(monkeypatch, {100: [FakeAX(title="A")]})
    with pytest.raises(BaseException, match="未找到"):
        WindowsCore.find(_pick(name="Nope", app="Finder"))


def test_top_close_info_size(monkeypatch):
    w = FakeAX(title="Win", attrs={"AXCloseButton": "btn", "AXZoomButton": "zoom"})
    core_mac = _patch_ax(monkeypatch, {1: [w]})
    raised = []
    performed = []
    set_attrs = []

    monkeypatch.setattr(core_mac.ax_common, "raise_window", lambda el, pid=None: raised.append((el, pid)))
    monkeypatch.setattr(core_mac.ax_common, "ax_perform", lambda el, action="AXPress": performed.append((el, action)) or True)
    monkeypatch.setattr(
        core_mac.ax_common, "ax_set_attr", lambda el, name, value: set_attrs.append((name, value)) or True
    )
    monkeypatch.setattr(core_mac, "_ax_size", lambda w, h: ("size", w, h))
    monkeypatch.setattr(core_mac, "_ax_point", lambda x, y: ("point", x, y))
    monkeypatch.setattr(core_mac, "_visible_frame_ax", lambda: (0, 0, 800, 600))

    handler = MacWindow(pid=1, ax_window=w, title="Win")
    WindowsCore.top(handler)
    assert raised == [(w, 1)]

    info = WindowsCore.info(handler)
    assert info.name == "Win"
    assert info.classname == "AXStandardWindow"
    assert info.position == (10, 20, 210, 220)

    WindowsCore.close(handler)
    assert performed[0][0] == "btn"

    WindowsCore.size(handler, WindowSizeType.MIN)
    assert ("AXMinimized", True) in set_attrs

    WindowsCore.size(handler, WindowSizeType.CUSTOM, 100, 50)
    assert ("AXSize", ("size", 100, 50)) in set_attrs

    WindowsCore.size(handler, WindowSizeType.MAX)
    assert any(p[0] == "zoom" for p in performed)


def test_tocontrol_and_walk(monkeypatch):
    child = FakeAX(role="AXButton", title="OK", pid=1, rect=Rect(1, 1, 11, 11))
    win = FakeAX(title="W", pid=1, children=[child])
    core_mac = _patch_ax(monkeypatch, {1: [win]})
    monkeypatch.setattr(core_mac.ax_common, "window_of", lambda el: win)

    handler = MacWindow(pid=1, ax_window=win, title="W")
    ctrl = WindowsCore.toControl(handler)
    assert ctrl.Name == "W"

    items = list(UITreeCore.WalkControl(win, includeTop=True, maxDepth=2))
    names = [i.name for i in items]
    assert "W" in names
    assert "OK" in names

    h = UITreeCore.toHandler(child)
    assert h.ax_window is win


@pytest.mark.skipif(sys.platform != "darwin", reason="live AX only on macOS")
def test_live_find_skipped_without_trust():
    from astronverse.locator.core.ax_common import is_trusted

    if not is_trusted():
        pytest.skip("Accessibility not trusted")
    # smoke: at least Finder usually has a window or we just don't crash
    try:
        WindowsCore.find(_pick(name="Finder", app="Finder"))
    except BaseException:
        pass
