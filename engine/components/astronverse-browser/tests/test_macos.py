import subprocess
import sys
from types import SimpleNamespace

import pytest
from astronverse.browser.core.launcher import BrowserLauncher


class FakeEl:
    def __init__(
        self,
        role="",
        subrole="",
        identifier="",
        value="",
        children=None,
        minimized=False,
        sheets=None,
        default_button=None,
        rect=None,
    ):
        self.role = role
        self.subrole = subrole
        self.identifier = identifier
        self.value = value
        self.children = children or []
        self.minimized = minimized
        self.sheets = sheets or []
        self.default_button = default_button
        self.rect = rect
        for c in self.children:
            if not hasattr(c, "parent"):
                c.parent = self


def fake_ax_attr(el, name, default=None):
    if not isinstance(el, FakeEl):
        return default
    mapping = {
        "AXRole": el.role,
        "AXSubrole": el.subrole,
        "AXIdentifier": el.identifier,
        "AXValue": el.value,
        "AXChildren": el.children,
        "AXMinimized": el.minimized,
        "AXSheets": el.sheets,
        "AXDefaultButton": el.default_button,
    }
    return mapping.get(name, default)


def fake_ax_children(el):
    return list(el.children) if isinstance(el, FakeEl) else []


def fake_ax_rect(el):
    return el.rect if isinstance(el, FakeEl) else None


def _patch_ax(monkeypatch, windows):
    monkeypatch.setattr("astronverse.locator.core.ax_common.find_apps", lambda *a, **k: [42] if windows else [])
    monkeypatch.setattr("astronverse.locator.core.ax_common.app_element", lambda pid: FakeEl(role="AXApplication"))
    monkeypatch.setattr("astronverse.locator.core.ax_common.app_windows", lambda app: windows)
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_attr", fake_ax_attr)
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_children", fake_ax_children)
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_rect", fake_ax_rect)
    monkeypatch.setattr("astronverse.locator.core.ax_common.pid_of", lambda el: 42)
    monkeypatch.setattr("astronverse.locator.core.ax_common.raise_window", lambda *a, **k: None)
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_set_attr", lambda *a, **k: True)
    monkeypatch.setattr("astronverse.locator.core.ax_common.ax_perform", lambda *a, **k: True)


class TestLauncherArgv:
    def test_darwin_app_bundle(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        cmd = BrowserLauncher.build_cmd("/Applications/Google Chrome.app", "https://example.com", "--new-window")
        assert cmd == [
            "open",
            "-n",
            "-a",
            "/Applications/Google Chrome.app",
            "--args",
            "--new-window",
            "https://example.com",
        ]

    def test_darwin_app_omits_empty_url(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        cmd = BrowserLauncher.build_cmd("/Applications/Google Chrome.app", "", "--new-window")
        assert cmd == ["open", "-n", "-a", "/Applications/Google Chrome.app", "--args", "--new-window"]
        cmd = BrowserLauncher.build_cmd("/Applications/Firefox.app", "", "")
        assert cmd == ["open", "-n", "-a", "/Applications/Firefox.app", "--args"]

    def test_darwin_binary_path(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        cmd = BrowserLauncher.build_cmd("/usr/bin/chromium", "https://a", "--foo bar")
        assert cmd == ["/usr/bin/chromium", "--foo", "bar", "https://a"]

    def test_load_extension_no_single_quotes(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        path = "/Users/me/plugins/chromium-extension"
        cmd = BrowserLauncher.build_cmd(
            "/Applications/Chromium.app",
            "https://x",
            f' --load-extension="{path}" --new-window',
        )
        assert f"--load-extension={path}" in cmd
        assert not any("'" in part for part in cmd)

    def test_open_uses_argv_list(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        captured = {}

        class FakePopen:
            def __init__(self, cmd, *args, **kwargs):
                captured["cmd"] = cmd
                captured["kwargs"] = kwargs
                self.pid = 1

            def poll(self):
                return None

        monkeypatch.setattr(subprocess, "Popen", FakePopen)
        ok = BrowserLauncher.open("/Applications/Google Chrome.app", "https://example.com", "--new-window")
        assert ok is True
        assert isinstance(captured["cmd"], list)
        assert captured["cmd"][0] == "open"
        assert captured["kwargs"].get("close_fds") is True


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS specific tests")
class TestMacOSBrowser:
    def test_imports(self):
        import astronverse.browser.browser_element as be
        import astronverse.browser.browser_software as bs
        from astronverse.browser.core.core_mac import BrowserCore

        assert bs.BrowserCore is BrowserCore
        assert be.BrowserCore is BrowserCore

    def test_get_browser_path(self, monkeypatch):
        from astronverse.browser.core.core_mac import BrowserCore

        monkeypatch.setattr(
            "astronverse.software.software.Software.get_app_path",
            lambda name: f"/Applications/{name}.app" if name else "",
        )
        assert BrowserCore.get_browser_path("chrome") == "/Applications/Google Chrome.app"
        assert BrowserCore.get_browser_path("edge") == "/Applications/Microsoft Edge.app"
        assert BrowserCore.get_browser_path("firefox") == "/Applications/Firefox.app"
        assert BrowserCore.get_browser_path("chromium") == "/Applications/Chromium.app"
        assert BrowserCore.get_browser_path("360se") == ""
        assert BrowserCore.get_browser_path("360ChromeX") == ""

    def test_get_browser_control_skips_minimized(self, monkeypatch):
        from astronverse.browser.core.core_mac import BrowserCore

        mini = FakeEl(role="AXWindow", subrole="AXStandardWindow", minimized=True)
        front = FakeEl(role="AXWindow", subrole="AXStandardWindow", minimized=False)
        _patch_ax(monkeypatch, [mini, front])
        assert BrowserCore.get_browser_control("chrome") is front

    def test_get_browser_control_fallback_minimized(self, monkeypatch):
        from astronverse.browser.core.core_mac import BrowserCore

        mini = FakeEl(role="AXWindow", subrole="AXStandardWindow", minimized=True)
        _patch_ax(monkeypatch, [mini])
        assert BrowserCore.get_browser_control("chrome") is mini

    def test_get_browser_control_none(self, monkeypatch):
        from astronverse.browser.core.core_mac import BrowserCore

        _patch_ax(monkeypatch, [])
        assert BrowserCore.get_browser_control("chrome") is None
        assert BrowserCore.get_browser_control("360se") is None

    def test_get_browser_point(self, monkeypatch):
        from astronverse.browser.core.core_mac import BrowserCore

        empty = FakeEl(role="AXWebArea", rect=SimpleNamespace(left=0, top=0, right=0, bottom=0))
        web = FakeEl(role="AXWebArea", rect=SimpleNamespace(left=12, top=34, right=112, bottom=134))
        group = FakeEl(role="AXGroup", children=[empty, web])
        win = FakeEl(role="AXWindow", subrole="AXStandardWindow", children=[group])
        _patch_ax(monkeypatch, [win])
        assert BrowserCore.get_browser_point("chrome") == (34, 12)

    def test_download_dialog(self, monkeypatch, tmp_path):
        import pyautogui
        import pyperclip
        from astronverse.browser.core import core_mac
        from astronverse.browser.core.core_mac import BrowserCore

        btn = FakeEl(role="AXButton")
        field = FakeEl(role="AXTextField", identifier="saveAsNameTextField", value="page.pdf")
        sheet = FakeEl(role="AXSheet", children=[field], default_button=btn)
        win = FakeEl(role="AXWindow", subrole="AXStandardWindow", sheets=[sheet], children=[sheet])
        _patch_ax(monkeypatch, [win])

        sets = []
        monkeypatch.setattr(
            "astronverse.locator.core.ax_common.ax_set_attr",
            lambda el, name, value: sets.append((el, name, value)) or True,
        )
        performs = []
        monkeypatch.setattr(
            "astronverse.locator.core.ax_common.ax_perform",
            lambda el, action="AXPress": performs.append(el) or True,
        )
        monkeypatch.setattr(core_mac.time, "sleep", lambda s: None)

        hotkeys = []
        monkeypatch.setattr(pyautogui, "hotkey", lambda *a, **k: hotkeys.append(a))
        monkeypatch.setattr(pyautogui, "press", lambda *a, **k: hotkeys.append(("press", a)))
        clip = {"v": "OLDCLIP"}
        copied = []

        def copy(val):
            copied.append(val)
            clip["v"] = val

        monkeypatch.setattr(pyperclip, "paste", lambda: clip["v"])
        monkeypatch.setattr(pyperclip, "copy", copy)

        dest = BrowserCore.download_window_operate(
            browser_type="chrome",
            save_path=str(tmp_path),
            file_name="custom",
            custom_flag=True,
            is_wait=False,
            time_out=0,
        )
        assert dest == str(tmp_path / "custom.pdf")
        assert ("command", "shift", "g") in hotkeys
        assert ("command", "v") in hotkeys
        assert copied[0] == str(tmp_path)
        assert copied[-1] == "OLDCLIP"
        assert any(el is field and name == "AXValue" and value == "custom.pdf" for el, name, value in sets)
        assert btn in performs

    def test_download_timeout(self, monkeypatch):
        from astronverse.browser.core import core_mac
        from astronverse.browser.core.core_mac import BrowserCore
        from astronverse.browser.error import DOWNLOAD_WINDOW_NO_FIND, BaseException

        win = FakeEl(role="AXWindow", subrole="AXStandardWindow")
        _patch_ax(monkeypatch, [win])
        t = [0.0]
        monkeypatch.setattr(core_mac.time, "time", lambda: t[0])
        monkeypatch.setattr(core_mac.time, "sleep", lambda s: t.__setitem__(0, t[0] + s))
        with pytest.raises(BaseException) as ei:
            BrowserCore.download_window_operate(browser_type="chrome", save_path="/tmp", is_wait=False)
        assert ei.value.code == DOWNLOAD_WINDOW_NO_FIND

    def test_upload_dialog(self, monkeypatch):
        import pyautogui
        import pyperclip
        from astronverse.browser.core import core_mac
        from astronverse.browser.core.core_mac import BrowserCore

        btn = FakeEl(role="AXButton")
        sheet = FakeEl(role="AXSheet", default_button=btn)
        win = FakeEl(role="AXWindow", subrole="AXStandardWindow", sheets=[sheet], children=[sheet])
        _patch_ax(monkeypatch, [win])
        monkeypatch.setattr(core_mac.time, "sleep", lambda s: None)
        hotkeys = []
        monkeypatch.setattr(pyautogui, "hotkey", lambda *a, **k: hotkeys.append(a))
        monkeypatch.setattr(pyautogui, "press", lambda *a, **k: None)
        clip = {"v": "OLD"}
        copied = []

        def copy(val):
            copied.append(val)
            clip["v"] = val

        monkeypatch.setattr(pyperclip, "paste", lambda: clip["v"])
        monkeypatch.setattr(pyperclip, "copy", copy)
        performs = []
        monkeypatch.setattr(
            "astronverse.locator.core.ax_common.ax_perform",
            lambda el, action="AXPress": performs.append(el) or True,
        )

        dest = BrowserCore.upload_window_operate(browser_type="chrome", upload_path="/tmp/a.txt|/tmp/b.txt")
        assert dest == "/tmp/a.txt"
        assert ("command", "shift", "g") in hotkeys
        assert copied[0] == "/tmp/a.txt"
        assert copied[-1] == "OLD"
        assert btn in performs
