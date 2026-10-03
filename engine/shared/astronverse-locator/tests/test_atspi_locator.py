from typing import Any, Optional

from astronverse.locator import Rect
from astronverse.locator.core.atspi_locator import ATSPIFactory, ATSPILocator, atspi_factory


class FakeATSPI:
    def __init__(
        self,
        role: str,
        name: str = "",
        cls: str = "",
        value: str = "",
        identifier: str = "",
        rect: Optional[Rect] = None,
        pid: int = 1234,
        children: Optional[list["FakeATSPI"]] = None,
        parent: Optional["FakeATSPI"] = None,
    ):
        self.role = role
        self.name = name
        self.cls = cls
        self.value = value
        self.identifier = identifier
        self._rect = rect or Rect(0, 0, 100, 100)
        self.pid = pid
        self.children = children or []
        self.parent = parent
        for c in self.children:
            c.parent = self


def test_locator_manager_dispatches_atspi(monkeypatch):
    from astronverse.locator.locator import locator

    win = FakeATSPI("frame", name="Settings")
    monkeypatch.setattr("astronverse.locator.core.atspi_common.find_apps", lambda n, b=None: [1234])
    monkeypatch.setattr("astronverse.locator.core.atspi_common.app_element", lambda pid: win)
    monkeypatch.setattr("astronverse.locator.core.atspi_common.app_windows", lambda a: [win])
    monkeypatch.setattr("astronverse.locator.core.atspi_common._role_name", lambda el: getattr(el, "role", ""))
    monkeypatch.setattr("astronverse.locator.core.atspi_common.atspi_name", lambda el: getattr(el, "name", ""))
    monkeypatch.setattr("astronverse.locator.core.atspi_common.atspi_cls", lambda el: getattr(el, "cls", ""))
    monkeypatch.setattr("astronverse.locator.core.atspi_common.raise_window", lambda w, p=None: None)
    monkeypatch.setattr("astronverse.locator.core.atspi_common.atspi_rect", lambda el, **k: getattr(el, "_rect", None))

    ele_dict = {
        "type": "atspi",
        "app": "SettingsApp",
        "picker_type": "WINDOW",
        "path": [{"tag_name": "frame", "name": "Settings", "checked": True, "disable_keys": ["index"]}],
    }
    loc = locator.locator(ele_dict)
    assert loc is not None
    assert isinstance(loc, ATSPILocator)
    assert loc._element == win


def test_atspi_factory_parse_node():
    node = ATSPIFactory._parse_node({"tag_name": "push button", "name": "OK", "index": 1, "checked": True})
    assert node.tag_name == "push button"
    assert node.name == "OK"
    assert node.index == 1
    assert atspi_factory is not None
