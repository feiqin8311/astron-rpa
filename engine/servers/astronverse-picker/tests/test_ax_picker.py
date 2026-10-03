"""Tests for macOS AX picker, AX strategy, and darwin manager dispatch."""

import importlib
import sys
import types
from types import SimpleNamespace
from typing import Any, Optional

import pytest
from astronverse.picker import PickerDomain, PickerType, Point, Rect
from astronverse.picker.engines.ax_picker import (
    TAG_MAP,
    AXElement,
    AXOperate,
    AXPicker,
    ax_picker,
)
from astronverse.picker.strategy.ax_strategy import ax_default_strategy
from astronverse.picker.strategy.manager import Strategy
from astronverse.picker.strategy.types import StrategySvc


class FakeAX:
    """Minimal AX tree node used by monkeypatched ax_common accessors."""

    def __init__(
        self,
        role: str,
        name: str = "",
        subrole: str = "",
        value: Any = None,
        identifier: str = "",
        rect: Optional[Rect] = None,
        pid: int = 1234,
        children: Optional[list["FakeAX"]] = None,
        parent: Optional["FakeAX"] = None,
    ):
        self.role = role
        self.name = name
        self.subrole = subrole
        self.value = value
        self.identifier = identifier
        self._rect = rect or Rect(0, 0, 100, 100)
        self.pid = pid
        self.children = children or []
        self.parent = parent
        for c in self.children:
            c.parent = self


class FakeNSApp:
    def __init__(self, name="Finder", bid="com.apple.finder"):
        self._name = name
        self._bid = bid

    def localizedName(self):  # noqa: N802
        return self._name

    def bundleIdentifier(self):  # noqa: N802
        return self._bid


def fake_ax_attr(el: Any, name: str, default: Any = None) -> Any:
    if not isinstance(el, FakeAX):
        return default
    if name == "AXRole":
        return el.role
    if name == "AXTitle":
        return el.name
    if name in ("AXDescription", "AXHelp"):
        return ""
    if name == "AXSubrole":
        return el.subrole
    if name == "AXValue":
        return el.value
    if name == "AXIdentifier":
        return el.identifier
    if name == "AXChildren":
        return el.children
    if name == "AXParent":
        return el.parent
    if name == "AXWindows":
        return getattr(el, "_windows", [])
    return default


def fake_ax_children(el: Any) -> list:
    return list(el.children) if isinstance(el, FakeAX) else []


def fake_ax_parent(el: Any) -> Any:
    return el.parent if isinstance(el, FakeAX) else None


def fake_ax_rect(el: Any) -> Optional[Rect]:
    return el._rect if isinstance(el, FakeAX) else None


def fake_pid_of(el: Any) -> Optional[int]:
    return el.pid if isinstance(el, FakeAX) else None


def fake_window_of(el: Any) -> Any:
    curr = el
    seen = set()
    while curr is not None and id(curr) not in seen:
        seen.add(id(curr))
        if getattr(curr, "role", None) == "AXWindow":
            return curr
        curr = getattr(curr, "parent", None)
    return None


def fake_app_element(pid: int) -> Any:
    app = FakeAX("AXApplication", name="Finder", pid=pid or 1234)
    return app


def _patch_ax_common(monkeypatch, *, windows=None):
    ax = importlib.import_module("astronverse.locator.core.ax_common")
    monkeypatch.setattr(ax, "ax_attr", fake_ax_attr)
    monkeypatch.setattr(ax, "ax_children", fake_ax_children)
    monkeypatch.setattr(ax, "ax_parent", fake_ax_parent)
    monkeypatch.setattr(ax, "ax_rect", fake_ax_rect)
    monkeypatch.setattr(ax, "pid_of", fake_pid_of)
    monkeypatch.setattr(ax, "window_of", fake_window_of)
    monkeypatch.setattr(ax, "app_element", fake_app_element)
    monkeypatch.setattr(ax, "running_app", lambda pid: FakeNSApp())
    monkeypatch.setattr(ax, "app_windows", lambda app_el: list(windows or []))
    monkeypatch.setattr(ax, "_ensure_darwin", lambda: None)


def _make_hit_tree():
    """Window > pane (large) > button (small) + zero-size ghost; point inside button."""
    win = FakeAX("AXWindow", name="Downloads", subrole="AXStandardWindow", rect=Rect(0, 0, 400, 400))
    pane = FakeAX("AXGroup", name="Content", parent=win, rect=Rect(0, 0, 400, 400))
    btn = FakeAX("AXButton", name="Back", parent=pane, rect=Rect(10, 10, 50, 40))
    ghost = FakeAX("AXGroup", name="ghost", parent=pane, rect=Rect(20, 20, 20, 20))  # zero size
    other = FakeAX("AXStaticText", name="label", parent=pane, rect=Rect(200, 200, 280, 220))
    win.children = [pane]
    pane.children = [btn, ghost, other]
    return win, pane, btn


def _ax_domain():
    return getattr(PickerDomain, "AX", None)


def test_tag_mapping(monkeypatch):
    _patch_ax_common(monkeypatch)
    for role, label in TAG_MAP.items():
        assert AXElement(FakeAX(role)).tag() == label
    assert AXElement(FakeAX("AXUnknownRole")).tag() == "UnknownRole"
    assert AXElement(FakeAX("CustomRole")).tag() == "CustomRole"


def test_min_area_hit_refinement(monkeypatch):
    win, pane, btn = _make_hit_tree()
    _patch_ax_common(monkeypatch, windows=[win])
    ax = importlib.import_module("astronverse.locator.core.ax_common")
    monkeypatch.setattr(ax, "element_at_point", lambda x, y, max_depth=50: win)

    point = Point(20, 20)
    ele = AXPicker.get_element(start_el=win, point=point)
    assert ele is not None
    assert ele.control is btn
    assert ele.tag() == "按钮"
    r = ele.rect()
    assert r.left == 10
    assert r.top == 10
    assert r.right == 50
    assert r.bottom == 40


def test_min_area_prefers_deeper_on_tie(monkeypatch):
    win = FakeAX("AXWindow", name="W", rect=Rect(0, 0, 100, 100))
    outer = FakeAX("AXGroup", name="outer", parent=win, rect=Rect(10, 10, 40, 40))
    inner = FakeAX("AXButton", name="inner", parent=outer, rect=Rect(10, 10, 40, 40))
    win.children = [outer]
    outer.children = [inner]
    _patch_ax_common(monkeypatch, windows=[win])
    ax = importlib.import_module("astronverse.locator.core.ax_common")
    monkeypatch.setattr(ax, "element_at_point", lambda x, y, max_depth=50: win)

    ele = AXPicker.get_element(start_el=win, point=Point(20, 20))
    assert ele.control is inner


def test_path_output_shape(monkeypatch):
    win, pane, btn = _make_hit_tree()
    _patch_ax_common(monkeypatch, windows=[win])
    monkeypatch.setattr("astronverse.picker.engines.ax_picker.screenshot", lambda rect: "fake-png")

    res = AXElement(btn).path()
    assert res["type"] == "ax"
    assert res["version"] == "1"
    assert res["app"] == "Finder"
    assert res["bundle_id"] == "com.apple.finder"
    assert res["img"]["self"] == "fake-png"
    assert res["picker_type"] == PickerType.ELEMENT.value
    assert res["path"]
    assert res["path"][0]["tag_name"] == "AXWindow"
    assert res["path"][0]["name"] == "Downloads"
    assert "disable_keys" in res["path"][0]
    assert res["path"][-1]["tag_name"] == "AXButton"
    assert res["path"][-1]["name"] == "Back"
    assert "disable_keys" in res["path"][-1]


def test_window_pick_truncates_path(monkeypatch):
    win, pane, btn = _make_hit_tree()
    _patch_ax_common(monkeypatch, windows=[win])
    monkeypatch.setattr("astronverse.picker.engines.ax_picker.screenshot", lambda rect: "")

    svc = StrategySvc(data={"pick_type": PickerType.WINDOW})
    res = AXElement(btn).path(strategy_svc=svc)
    assert res["picker_type"] == PickerType.WINDOW.value
    assert len(res["path"]) == 1
    assert res["path"][0]["tag_name"] == "AXWindow"


def test_similar_path_marking():
    old_path = [
        {"tag_name": "AXWindow", "cls": "AXStandardWindow", "name": "Downloads", "index": 0, "disable_keys": ["index"]},
        {"tag_name": "AXGroup", "name": "Toolbar", "index": 0, "disable_keys": ["cls"]},
        {"tag_name": "AXButton", "name": "Back", "index": 2, "disable_keys": []},
    ]
    new_path = [
        {"tag_name": "AXWindow", "cls": "AXStandardWindow", "name": "Downloads", "index": 0, "disable_keys": ["index"]},
        {"tag_name": "AXGroup", "name": "Toolbar", "index": 0, "disable_keys": ["cls"]},
        {"tag_name": "AXButton", "name": "Forward", "index": 3, "disable_keys": []},
    ]
    svc = StrategySvc(data={"data": {"app": "Finder", "type": "ax", "path": old_path}})
    curr = {"app": "Finder", "type": "ax", "path": new_path}
    similar = AXPicker.get_similar_path(svc, curr)
    assert similar is not None
    assert similar[0].get("similar_parent") is True
    assert similar[1].get("similar_parent") is True
    assert similar[2].get("similar_parent") is None
    assert similar[2]["disable_keys"] == ["cls", "name", "value", "index"]


def test_similar_path_rejects_different_app():
    svc = StrategySvc(data={"data": {"app": "Finder", "type": "ax", "path": [{"tag_name": "AXWindow"}]}})
    curr = {"app": "Safari", "type": "ax", "path": [{"tag_name": "AXWindow"}]}
    assert AXPicker.get_similar_path(svc, curr) is None


def test_ax_operate(monkeypatch):
    win, pane, btn = _make_hit_tree()
    _patch_ax_common(monkeypatch, windows=[win])
    assert AXOperate.get_process_id(btn) == 1234
    assert AXOperate.get_process_id(AXElement(btn)) == 1234
    assert AXOperate.get_app_window(btn) is win
    assert AXOperate.get_app_window(AXElement(btn)) is win


def test_ax_default_strategy(monkeypatch):
    win, pane, btn = _make_hit_tree()
    _patch_ax_common(monkeypatch, windows=[win])
    ax = importlib.import_module("astronverse.locator.core.ax_common")
    monkeypatch.setattr(ax, "element_at_point", lambda x, y, max_depth=50: win)

    svc = StrategySvc(start_control=win, last_point=Point(20, 20), data={})
    ele = ax_default_strategy(None, None, svc)
    assert isinstance(ele, AXElement)
    assert ele.control is btn


def _patch_auto_mac(monkeypatch, func):
    name = "astronverse.picker.strategy.auto_strategy_mac"
    try:
        mod = importlib.import_module(name)
        monkeypatch.setattr(mod, "auto_default_strategy_mac", func)
    except ImportError:
        mod = types.ModuleType(name)
        mod.auto_default_strategy_mac = func
        monkeypatch.setitem(sys.modules, name, mod)


def test_manager_darwin_ax_dispatch(monkeypatch):
    domain_ax = _ax_domain()
    if domain_ax is None:
        pytest.skip("PickerDomain.AX not defined")
    sentinel = SimpleNamespace(tag="ax-ele")
    monkeypatch.setattr(
        "astronverse.picker.strategy.ax_strategy.ax_default_strategy",
        lambda sc, st, svc: sentinel,
    )
    monkeypatch.setattr(sys, "platform", "darwin")
    result = Strategy(None).run(StrategySvc(domain=domain_ax, last_point=Point(1, 1), data={}, start_control=object()))
    assert result is sentinel


@pytest.mark.parametrize("domain", [PickerDomain.AUTO, PickerDomain.AUTO_DESK, PickerDomain.AUTO_WEB])
def test_manager_darwin_auto_dispatch(monkeypatch, domain):
    sentinel = SimpleNamespace(tag="auto-mac", domain=domain)
    _patch_auto_mac(monkeypatch, lambda sc, st, svc: sentinel)
    monkeypatch.setattr(sys, "platform", "darwin")
    result = Strategy(None).run(StrategySvc(domain=domain, last_point=Point(1, 1), data={}, start_control=object()))
    assert result is sentinel


def test_manager_win32_uia_passes_only_strategy_svc(monkeypatch):
    captured = {}

    def fake_uia(strategy_svc):
        captured["svc"] = strategy_svc
        captured["argc"] = 1
        return SimpleNamespace(tag="uia")

    fake_mod = types.ModuleType("astronverse.picker.strategy.uia_strategy")
    fake_mod.uia_default_strategy = fake_uia
    monkeypatch.setitem(sys.modules, "astronverse.picker.strategy.uia_strategy", fake_mod)
    monkeypatch.setattr(sys, "platform", "win32")
    svc = StrategySvc(domain=PickerDomain.UIA, last_point=Point(1, 1), data={}, start_control=object())
    result = Strategy(None).run(svc)
    assert result.tag == "uia"
    assert captured["argc"] == 1
    assert captured["svc"] is svc


def test_ax_picker_singleton():
    assert ax_picker is not None
    assert isinstance(ax_picker, AXPicker)
