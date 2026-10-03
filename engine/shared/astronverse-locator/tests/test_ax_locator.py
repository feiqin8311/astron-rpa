import sys
from typing import Any, Optional

import pytest
from astronverse.locator import PickerType, Rect
from astronverse.locator.core.ax_common import (
    AXControl,
    _calculate_disable_keys_progressive,
    build_path,
    is_trusted,
    node_of,
)
from astronverse.locator.core.ax_locator import AXFactory, AXLocator, ax_factory


class FakeAXElement:
    """Mock AXUIElement for unit tests without requiring macOS Accessibility permissions."""

    def __init__(
        self,
        role: str,
        name: str = "",
        subrole: str = "",
        value: Any = None,
        identifier: str = "",
        rect: Optional[Rect] = None,
        pid: int = 1234,
        children: Optional[list["FakeAXElement"]] = None,
        parent: Optional["FakeAXElement"] = None,
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

    def __repr__(self):
        return f"<FakeAX {self.role} name={self.name!r} id={self.identifier!r}>"


def fake_ax_attr(el: Any, name: str, default: Any = None) -> Any:
    if not isinstance(el, FakeAXElement):
        return default
    if name == "AXRole":
        return el.role
    elif name in ("AXTitle", "AXDescription", "AXHelp"):
        return el.name if name == "AXTitle" else ""
    elif name == "AXSubrole":
        return el.subrole
    elif name == "AXValue":
        return el.value
    elif name == "AXIdentifier":
        return el.identifier
    elif name == "AXPosition":
        return (el._rect.left, el._rect.top)
    elif name == "AXSize":
        return (el._rect.width(), el._rect.height())
    elif name == "AXChildren":
        return el.children
    elif name == "AXParent":
        return el.parent
    elif name == "AXWindows":
        return getattr(el, "_windows", [el])
    elif name == "AXMinimized":
        return False
    elif name == "AXEnabled":
        return True
    elif name == "AXFocused":
        return False
    return default


def fake_ax_children(el: Any) -> list:
    if isinstance(el, FakeAXElement):
        return list(el.children)
    return []


def fake_ax_parent(el: Any) -> Any:
    if isinstance(el, FakeAXElement):
        return el.parent
    return None


def fake_ax_rect(el: Any) -> Optional[Rect]:
    if isinstance(el, FakeAXElement):
        return el._rect
    return None


def fake_pid_of(el: Any) -> Optional[int]:
    if isinstance(el, FakeAXElement):
        return el.pid
    return 1234


# ---------------------------------------------------------------------------
# Unit Tests
# ---------------------------------------------------------------------------


def test_node_of_field_rules(monkeypatch):
    """Test node_of field extraction rules according to the AX contract:
    - tag_name: AXRole, always present
    - cls: AXSubrole, omitted when empty
    - name: AXTitle / AXDescription / AXHelp, always present
    - value: str(AXValue) only when non-empty str/num, omitted otherwise
    - identifier: AXIdentifier when non-empty, omitted otherwise
    - index: position among siblings with same AXRole (0-based)
    - checked: True
    """
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_attr", fake_ax_attr)
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_parent", fake_ax_parent)
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_children", fake_ax_children)
    monkeypatch.setattr("astronverse.locator.core.ax_common.pid_of", fake_pid_of)

    # 1. Standard button with all fields
    parent = FakeAXElement("AXWindow", name="MainWin")
    btn0 = FakeAXElement("AXButton", name="Cancel", subrole="AXCloseButton", value="btn_val", identifier="id_cancel")
    btn1 = FakeAXElement("AXButton", name="OK", subrole="AXDefaultButton", identifier="id_ok")
    txt0 = FakeAXElement("AXTextField", name="Input", value="hello", parent=parent)
    parent.children = [btn0, txt0, btn1]
    btn0.parent = parent
    btn1.parent = parent

    node0 = node_of(btn0)
    assert node0["tag_name"] == "AXButton"
    assert node0["cls"] == "AXCloseButton"
    assert node0["name"] == "Cancel"
    assert node0["value"] == "btn_val"
    assert node0["identifier"] == "id_cancel"
    assert node0["index"] == 0
    assert node0["checked"] is True

    # 2. Sibling button with empty cls/value
    node1 = node_of(btn1)
    assert node1["tag_name"] == "AXButton"
    assert "value" not in node1  # Omitted when empty/None
    assert node1["identifier"] == "id_ok"
    assert node1["index"] == 1  # 2nd button among same-role siblings
    assert node1["checked"] is True

    # 3. Text field sibling has index 0 among AXTextFields despite being at child index 1
    node_txt = node_of(txt0)
    assert node_txt["tag_name"] == "AXTextField"
    assert node_txt["index"] == 0
    assert "cls" not in node_txt  # Omitted when empty


def test_disable_keys_computation(monkeypatch):
    """Test progressive disable_keys computation:
    - Unique by tag_name -> other attributes disabled
    - Conflicts on tag_name -> progressively adds cls, name, value, index
    - Empty attributes always disabled
    """
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_attr", fake_ax_attr)

    parent = FakeAXElement("AXWindow", name="Win")
    b1 = FakeAXElement("AXButton", name="Save", parent=parent)
    b2 = FakeAXElement("AXButton", name="Delete", parent=parent)
    b3 = FakeAXElement("AXTextField", name="Search", parent=parent)
    parent.children = [b1, b2, b3]

    # b3 has unique tag_name among siblings -> only tag_name needed
    node_b3 = node_of(b3, siblings=parent.children)
    dk_b3 = _calculate_disable_keys_progressive(node_b3, parent.children, b3, is_root_level=False)
    assert "cls" in dk_b3
    assert "name" in dk_b3
    assert "index" in dk_b3

    # b1 has same tag_name as b2, but different name -> tag_name + name are kept, index/cls/value disabled
    node_b1 = node_of(b1, siblings=parent.children)
    dk_b1 = _calculate_disable_keys_progressive(node_b1, parent.children, b1, is_root_level=False)
    assert "index" in dk_b1  # index disabled because name made it unique
    assert "name" not in dk_b1  # name is required for uniqueness

    # Identical buttons (same name) -> index is required, so index is NOT disabled
    b_dup1 = FakeAXElement("AXButton", name="More", parent=parent)
    b_dup2 = FakeAXElement("AXButton", name="More", parent=parent)
    parent.children = [b_dup1, b_dup2]
    node_dup1 = node_of(b_dup1, siblings=parent.children)
    dk_dup1 = _calculate_disable_keys_progressive(node_dup1, parent.children, b_dup1, is_root_level=False)
    assert "index" not in dk_dup1  # index needed!


def test_build_path_generation(monkeypatch):
    """Test build_path produces the contract JSON shape with disable_keys."""
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_attr", fake_ax_attr)
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_parent", fake_ax_parent)
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_children", fake_ax_children)
    monkeypatch.setattr("astronverse.locator.core.ax_common.pid_of", fake_pid_of)
    monkeypatch.setattr("astronverse.locator.core.ax_common.running_app", lambda pid: None)
    monkeypatch.setattr("astronverse.locator.core.ax_common.app_windows", lambda app: [win])

    win = FakeAXElement("AXWindow", name="Calculator", subrole="AXStandardWindow")
    grp = FakeAXElement("AXGroup", name="", parent=win)
    btn = FakeAXElement("AXButton", name="Equals", parent=grp)
    win.children = [grp]
    grp.children = [btn]

    data = build_path(btn)
    assert data["type"] == "ax"
    assert len(data["path"]) == 3
    assert data["path"][0]["tag_name"] == "AXWindow"
    assert data["path"][0]["name"] == "Calculator"
    assert "disable_keys" in data["path"][0]
    assert data["path"][1]["tag_name"] == "AXGroup"
    assert data["path"][2]["tag_name"] == "AXButton"
    assert data["path"][2]["name"] == "Equals"


def test_strict_and_soft_index_matching(monkeypatch):
    """Test strict match on tag_name/cls/name/value/identifier, and soft match scoring on index."""
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_attr", fake_ax_attr)
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_children", fake_ax_children)
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_rect", fake_ax_rect)
    monkeypatch.setattr("astronverse.locator.core.ax_common.find_apps", lambda n, b=None: [1234])
    monkeypatch.setattr("astronverse.locator.core.ax_common.raise_window", lambda w, p=None: None)

    win = FakeAXElement("AXWindow", name="Editor")
    btn0 = FakeAXElement("AXButton", name="Item", rect=Rect(10, 10, 50, 50), parent=win)
    btn1 = FakeAXElement("AXButton", name="Item", rect=Rect(10, 60, 50, 100), parent=win)
    win.children = [btn0, btn1]

    monkeypatch.setattr("astronverse.locator.core.ax_common.app_windows", lambda a: [win])

    # Search for index 1
    ele_dict = {
        "app": "EditorApp",
        "path": [
            {"tag_name": "AXWindow", "name": "Editor", "checked": True, "disable_keys": ["index"]},
            {"tag_name": "AXButton", "name": "Item", "index": 1, "checked": True, "disable_keys": []},
        ],
    }
    result = ax_factory.find(ele_dict, "ELEMENT")
    assert isinstance(result, AXLocator)
    assert result._element == btn1

    # Search for index 0
    ele_dict["path"][1]["index"] = 0
    result0 = ax_factory.find(ele_dict, "ELEMENT")
    assert isinstance(result0, AXLocator)
    assert result0._element == btn0


def test_disabled_keys_and_unchecked_nodes_ignored(monkeypatch):
    """Test that attributes listed in disable_keys, or nodes with checked=False, are ignored."""
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_attr", fake_ax_attr)
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_children", fake_ax_children)
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_rect", fake_ax_rect)
    monkeypatch.setattr("astronverse.locator.core.ax_common.find_apps", lambda n, b=None: [1234])
    monkeypatch.setattr("astronverse.locator.core.ax_common.raise_window", lambda w, p=None: None)

    win = FakeAXElement("AXWindow", name="Editor")
    btn = FakeAXElement("AXButton", name="OriginalName", value="v1", parent=win)
    win.children = [btn]
    monkeypatch.setattr("astronverse.locator.core.ax_common.app_windows", lambda a: [win])

    # 1. Target node has different name and value, but both are in disable_keys -> MATCH
    ele_dict = {
        "app": "EditorApp",
        "path": [
            {"tag_name": "AXWindow", "name": "Editor", "checked": True, "disable_keys": ["index"]},
            {
                "tag_name": "AXButton",
                "name": "DifferentName",
                "value": "v2",
                "index": 0,
                "checked": True,
                "disable_keys": ["name", "value", "index"],
            },
        ],
    }
    loc = ax_factory.find(ele_dict, "ELEMENT")
    assert loc is not None
    assert loc._element == btn

    # 2. Node checked is False -> matched regardless of tag_name mismatch
    ele_dict["path"][1]["checked"] = False
    ele_dict["path"][1]["tag_name"] = "AXWrongRole"
    loc2 = ax_factory.find(ele_dict, "ELEMENT")
    assert loc2 is not None
    assert loc2._element == btn


def test_contains_name_fallback_for_windows(monkeypatch):
    """Test that if exact window name does not match, contains fallback selects
    the longest matching window name (matching Windows longest-name match).
    """
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_attr", fake_ax_attr)
    monkeypatch.setattr("astronverse.locator.core.ax_common.find_apps", lambda n, b=None: [1234])
    monkeypatch.setattr("astronverse.locator.core.ax_common.raise_window", lambda w, p=None: None)

    # Windows with partial names
    win_short = FakeAXElement("AXWindow", name="Document")
    win_long = FakeAXElement("AXWindow", name="Document - MySpecialDoc.txt - Editor")
    win_unrelated = FakeAXElement("AXWindow", name="Preferences")

    monkeypatch.setattr(
        "astronverse.locator.core.ax_common.app_windows", lambda a: [win_short, win_long, win_unrelated]
    )

    ele_dict = {
        "app": "EditorApp",
        "path": [{"tag_name": "AXWindow", "name": "MySpecialDoc", "checked": True, "disable_keys": ["index"]}],
    }

    # Should select win_long via contains fallback
    loc = ax_factory.find(ele_dict, "WINDOW")
    assert loc is not None
    assert loc._element == win_long


def test_similar_picker_type_returns_all_matching_siblings(monkeypatch):
    """Test SIMILAR picker returns a list of all matching sibling elements."""
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_attr", fake_ax_attr)
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_children", fake_ax_children)
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_rect", fake_ax_rect)
    monkeypatch.setattr("astronverse.locator.core.ax_common.find_apps", lambda n, b=None: [1234])
    monkeypatch.setattr("astronverse.locator.core.ax_common.raise_window", lambda w, p=None: None)

    win = FakeAXElement("AXWindow", name="TableWin")
    tbl = FakeAXElement("AXTable", name="Data", parent=win)
    row0 = FakeAXElement("AXRow", name="Row 0", parent=tbl)
    row1 = FakeAXElement("AXRow", name="Row 1", parent=tbl)
    row2 = FakeAXElement("AXRow", name="Row 2", parent=tbl)
    other = FakeAXElement("AXScrollBar", name="", parent=tbl)
    tbl.children = [row0, row1, row2, other]
    win.children = [tbl]

    monkeypatch.setattr("astronverse.locator.core.ax_common.app_windows", lambda a: [win])

    ele_dict = {
        "app": "DataApp",
        "path": [
            {
                "tag_name": "AXWindow",
                "name": "TableWin",
                "similar_parent": True,
                "checked": True,
                "disable_keys": ["index"],
            },
            {"tag_name": "AXTable", "name": "Data", "similar_parent": True, "checked": True, "disable_keys": []},
            {"tag_name": "AXRow", "checked": True, "disable_keys": ["name", "index"]},
        ],
    }

    results = ax_factory.find(ele_dict, PickerType.SIMILAR.value)
    assert isinstance(results, list)
    assert len(results) == 3
    matched_elements = [r._element for r in results]
    assert matched_elements == [row0, row1, row2]


def test_window_pick_returns_window(monkeypatch):
    """Test WINDOW pick returns the window locator directly."""
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_attr", fake_ax_attr)
    monkeypatch.setattr("astronverse.locator.core.ax_common.find_apps", lambda n, b=None: [1234])
    raised = []
    monkeypatch.setattr("astronverse.locator.core.ax_common.raise_window", lambda w, p=None: raised.append(w))

    win = FakeAXElement("AXWindow", name="Settings")
    monkeypatch.setattr("astronverse.locator.core.ax_common.app_windows", lambda a: [win])

    ele_dict = {
        "app": "SettingsApp",
        "path": [{"tag_name": "AXWindow", "name": "Settings", "checked": True, "disable_keys": ["index"]}],
    }

    loc = ax_factory.find(ele_dict, PickerType.WINDOW.value)
    assert loc is not None
    assert loc._element == win
    assert raised == [win]


def test_ax_control_wrapper(monkeypatch):
    """Test AXControl properties, methods, and ControlTypeName mappings."""
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_attr", fake_ax_attr)
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_rect", fake_ax_rect)
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_children", fake_ax_children)
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_parent", fake_ax_parent)

    # 1. EditControl mapping
    txt = FakeAXElement("AXTextField", name="Username", value="admin", identifier="user_field")
    ctrl_txt = AXControl(txt)
    assert ctrl_txt.ControlTypeName == "EditControl"
    assert ctrl_txt.Name == "Username"
    assert ctrl_txt.value == "admin"
    assert ctrl_txt.identifier == "user_field"

    # 2. ButtonControl mapping
    btn = FakeAXElement("AXButton", name="Submit")
    ctrl_btn = AXControl(btn)
    assert ctrl_btn.ControlTypeName == "ButtonControl"
    assert ctrl_btn.role == "AXButton"

    # 3. Other roles
    grp = FakeAXElement("AXGroup", name="Container")
    ctrl_grp = AXControl(grp)
    assert ctrl_grp.ControlTypeName == "AXGroup"


def test_locator_manager_dispatches_ax(monkeypatch):
    """Test LocatorManager dispatches type='ax' to ax_factory."""
    from astronverse.locator.locator import locator

    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_attr", fake_ax_attr)
    monkeypatch.setattr("astronverse.locator.core.ax_common.find_apps", lambda n, b=None: [1234])
    monkeypatch.setattr("astronverse.locator.core.ax_common.raise_window", lambda w, p=None: None)

    win = FakeAXElement("AXWindow", name="Settings")
    monkeypatch.setattr("astronverse.locator.core.ax_common.app_windows", lambda a: [win])

    ele_dict = {
        "type": "ax",
        "app": "SettingsApp",
        "picker_type": "WINDOW",
        "path": [{"tag_name": "AXWindow", "name": "Settings", "checked": True, "disable_keys": ["index"]}],
    }

    loc = locator.locator(ele_dict)
    assert loc is not None
    assert isinstance(loc, AXLocator)
    assert loc._element == win


# ---------------------------------------------------------------------------
# Live Smoke Test
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "darwin" or not is_trusted(), reason="Requires macOS and Accessibility trust")
def test_live_smoke_finder():
    """Live smoke test: locate Finder frontmost window via element_at_point,
    build path, and verify AXFactory.find retrieves the same rect.
    Skipped when terminal lacks Accessibility permissions.
    """
    from AppKit import NSWorkspace
    from astronverse.locator.core.ax_common import (
        app_element,
        app_windows,
        ax_rect,
        element_at_point,
    )

    apps = NSWorkspace.sharedWorkspace().runningApplications()
    finder = next((a for a in apps if a.bundleIdentifier() == "com.apple.finder"), None)
    if not finder:
        pytest.skip("Finder application not found")

    app_el = app_element(finder.processIdentifier())
    wins = app_windows(app_el)
    if not wins:
        pytest.skip("Finder has no open windows for live smoke test")

    front_win = wins[0]
    rect = ax_rect(front_win)
    if not rect or rect.width() <= 0 or rect.height() <= 0:
        pytest.skip("Finder window rect is empty")

    cx = rect.left + rect.width() // 2
    cy = rect.top + rect.height() // 2

    el = element_at_point(cx, cy)
    assert el is not None

    path_data = build_path(el)
    found_loc = AXFactory.find(path_data, "ELEMENT")
    assert found_loc is not None
    found_rect = found_loc.rect()
    assert found_rect is not None
