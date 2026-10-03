"""Tests for macOS auto web-pick strategy (AXWebArea viewport + fallback)."""

from types import SimpleNamespace

from astronverse.picker import APP, PickerDomain, Point
from astronverse.picker.strategy.auto_strategy_mac import auto_default_strategy_mac
from astronverse.picker.strategy.types import StrategySvc


class FakeAX:
    """Minimal AX tree node: role / parent / _rect / pid (duck-typed)."""

    def __init__(self, role, parent=None, rect=None, pid=0, children=None):
        self.role = role
        self.parent = parent
        self._rect = rect
        self.pid = pid
        self.children = children or []
        for c in self.children:
            c.parent = self


class Bound:
    def __init__(self, left, top, right, bottom):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


def make_tree():
    """AXWindow > AXGroup > AXWebArea > AXButton."""
    win = FakeAX("AXWindow", rect=Bound(0, 0, 800, 600), pid=4242)
    group = FakeAX("AXGroup", parent=win, rect=Bound(0, 80, 800, 600), pid=4242)
    web = FakeAX("AXWebArea", parent=group, rect=Bound(0, 80, 800, 600), pid=4242)
    btn = FakeAX("AXButton", parent=web, rect=Bound(10, 100, 80, 130), pid=4242)
    win.children = [group]
    group.children = [web]
    web.children = [btn]
    return win, group, web, btn


def _svc(app, start, domain=PickerDomain.AUTO):
    return StrategySvc(
        app=app,
        process_id=4242,
        last_point=Point(20, 110),
        start_control=start,
        data={},
        domain=domain,
    )


def test_finds_web_area_and_passes_bounding_rect(monkeypatch):
    _win, _group, web, btn = make_tree()
    captured = {}

    def fake_web(service, strategy_svc, cache=None):
        captured["svc"] = strategy_svc
        captured["bound"] = strategy_svc.start_control.BoundingRectangle
        captured["hwnd"] = strategy_svc.start_control.NativeWindowHandle
        return SimpleNamespace(tag="web-ele")

    monkeypatch.setattr("astronverse.picker.strategy.web_strategy.web_default_strategy", fake_web)

    result = auto_default_strategy_mac(None, None, _svc(APP.Chrome, btn))
    assert result is not None
    assert result.tag == "web-ele"
    assert captured["bound"].left == web._rect.left
    assert captured["bound"].top == web._rect.top
    assert captured["bound"].right == web._rect.right
    assert captured["bound"].bottom == web._rect.bottom
    assert captured["hwnd"] == 4242


def test_non_browser_falls_back_to_ax(monkeypatch):
    _win, _group, _web, btn = make_tree()
    called = {"web": False, "ax": False}

    def fake_web(*_a, **_k):
        called["web"] = True
        return SimpleNamespace(tag="web")

    def fake_ax(*_a, **_k):
        called["ax"] = True
        return SimpleNamespace(tag="ax")

    monkeypatch.setattr("astronverse.picker.strategy.web_strategy.web_default_strategy", fake_web)
    monkeypatch.setattr("astronverse.picker.strategy.ax_strategy.ax_default_strategy", fake_ax)

    result = auto_default_strategy_mac(None, None, _svc(APP.Unknown, btn))
    assert result.tag == "ax"
    assert called["ax"] is True
    assert called["web"] is False


def test_auto_web_does_not_fall_back(monkeypatch):
    _win, _group, _web, btn = make_tree()
    called = {"ax": False}

    def fake_web(*_a, **_k):
        return None

    def fake_ax(*_a, **_k):
        called["ax"] = True
        return SimpleNamespace(tag="ax")

    monkeypatch.setattr("astronverse.picker.strategy.web_strategy.web_default_strategy", fake_web)
    monkeypatch.setattr("astronverse.picker.strategy.ax_strategy.ax_default_strategy", fake_ax)

    result = auto_default_strategy_mac(None, None, _svc(APP.Chrome, btn, domain=PickerDomain.AUTO_WEB))
    assert result is None
    assert called["ax"] is False


def test_auto_desk_skips_web(monkeypatch):
    _win, _group, _web, btn = make_tree()
    called = {"web": False, "ax": False}

    def fake_web(*_a, **_k):
        called["web"] = True
        return SimpleNamespace(tag="web")

    def fake_ax(*_a, **_k):
        called["ax"] = True
        return SimpleNamespace(tag="ax")

    monkeypatch.setattr("astronverse.picker.strategy.web_strategy.web_default_strategy", fake_web)
    monkeypatch.setattr("astronverse.picker.strategy.ax_strategy.ax_default_strategy", fake_ax)

    result = auto_default_strategy_mac(None, None, _svc(APP.Chrome, btn, domain=PickerDomain.AUTO_DESK))
    assert result.tag == "ax"
    assert called["ax"] is True
    assert called["web"] is False
