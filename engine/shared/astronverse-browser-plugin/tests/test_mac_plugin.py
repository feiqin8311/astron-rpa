import json
import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
from astronverse.browser_plugin import BrowserType, PluginData
from astronverse.browser_plugin.browser import ExtensionManager
from astronverse.browser_plugin.mac import BrowserPluginFactory
from astronverse.browser_plugin.mac.chromium import ChromiumPluginManager, find_mac_app
from astronverse.browser_plugin.mac.firefox import FirefoxPluginManager


@pytest.fixture
def mock_env(tmp_path, monkeypatch):
    """Isolate tests from real home directory and system libraries."""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    return fake_home


@pytest.fixture
def dummy_plugin_data(tmp_path):
    crx_path = tmp_path / "chrome-5.2.12-hklbenkcbnefkhgodegcoihmgoodlgod.crx"
    crx_path.write_text("dummy crx")
    unpacked_dir = tmp_path / "chromium-extension"
    unpacked_dir.mkdir()
    (unpacked_dir / "manifest.json").write_text(json.dumps({"name": "Astron Browser Plugin", "version": "5.2.12"}))
    return PluginData(
        plugin_path=str(crx_path),
        plugin_id="hklbenkcbnefkhgodegcoihmgoodlgod",
        plugin_version="5.2.12",
        plugin_name="chrome",
    )


def test_import_and_support_list():
    assert sys.platform == "darwin"
    support = BrowserPluginFactory.get_support_browser()
    assert BrowserType.CHROME in support
    assert BrowserType.MICROSOFT_EDGE in support
    assert BrowserType.FIREFOX in support
    assert BrowserType.BROWSER_360 not in support

    names = [b.value.lower() for b in ExtensionManager.get_support()]
    assert names == ["chrome", "microsoft_edge", "firefox"]


def test_find_mac_app(tmp_path, monkeypatch):
    # 1. System Applications
    with patch("os.path.exists") as mock_exists:
        mock_exists.side_effect = lambda p: p == "/Applications/Google Chrome.app"
        assert find_mac_app("Google Chrome", "com.google.Chrome") == "/Applications/Google Chrome.app"

    # 2. User Applications
    fake_user_app = os.path.expanduser("~/Applications/Google Chrome.app")
    with patch("os.path.exists") as mock_exists:
        mock_exists.side_effect = lambda p: p == fake_user_app
        assert find_mac_app("Google Chrome", "com.google.Chrome") == fake_user_app

    # 3. Fallback mdfind
    with patch("os.path.exists") as mock_exists:
        custom_app = "/Custom/Path/Google Chrome.app"
        mock_exists.side_effect = lambda p: p == custom_app
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=f"{custom_app}\n")
            assert find_mac_app("Google Chrome", "com.google.Chrome") == custom_app

    # 4. Not installed
    with patch("os.path.exists", return_value=False):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            assert find_mac_app("Google Chrome", "com.google.Chrome") is None


def test_chromium_browser_running_and_lifecycle(dummy_plugin_data):
    manager = ChromiumPluginManager(dummy_plugin_data, app_name="Google Chrome")

    # check_browser_running using pgrep
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert manager.check_browser_running() is True
        mock_run.assert_called_with(
            ["pgrep", "-x", "Google Chrome"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    # close_browser using osascript
    with patch("subprocess.run") as mock_run:
        manager.close_browser()
        mock_run.assert_called_with(
            ["osascript", "-e", 'quit app "Google Chrome"'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    # open_browser using open -a
    with patch("subprocess.run") as mock_run:
        manager.open_browser()
        mock_run.assert_called_with(
            ["open", "-a", "Google Chrome"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def test_chromium_check_plugin_profile_scan(mock_env, dummy_plugin_data):
    # Setup simulated Chrome profile with official extension ID directory
    chrome_dir = mock_env / "Library" / "Application Support" / "Google" / "Chrome"
    ext_ver_dir = chrome_dir / "Default" / "Extensions" / dummy_plugin_data.plugin_id / "5.2.12_0"
    ext_ver_dir.mkdir(parents=True)

    manager = ChromiumPluginManager(dummy_plugin_data, user_data_rel_path="Google/Chrome")
    with patch.object(manager, "check_browser", return_value=True):
        status = manager.check_plugin()
        assert status.installed is True
        assert status.latest is True
        assert status.installed_version == "5.2.12"
        assert status.browser_installed is True


def test_chromium_check_plugin_outdated(mock_env, dummy_plugin_data):
    chrome_dir = mock_env / "Library" / "Application Support" / "Google" / "Chrome"
    ext_ver_dir = chrome_dir / "Profile 1" / "Extensions" / dummy_plugin_data.plugin_id / "5.2.10_1"
    ext_ver_dir.mkdir(parents=True)

    manager = ChromiumPluginManager(dummy_plugin_data, user_data_rel_path="Google/Chrome")
    with patch.object(manager, "check_browser", return_value=True):
        status = manager.check_plugin()
        assert status.installed is True
        assert status.latest is False
        assert status.installed_version == "5.2.10"


def test_chromium_check_plugin_preference_file_alone_not_installed(mock_env, dummy_plugin_data):
    """External Extensions preference file alone must NOT report installed (false positive prevention)."""
    ext_ext_dir = mock_env / "Library" / "Application Support" / "Google" / "Chrome" / "External Extensions"
    ext_ext_dir.mkdir(parents=True)
    pref_file = ext_ext_dir / f"{dummy_plugin_data.plugin_id}.json"
    pref_file.write_text(json.dumps({"external_crx": "/tmp/dummy.crx", "external_version": "5.2.12"}))

    manager = ChromiumPluginManager(dummy_plugin_data, user_data_rel_path="Google/Chrome")
    with patch.object(manager, "check_browser", return_value=True):
        status = manager.check_plugin()
        assert status.installed is False
        assert status.latest is False
        assert status.installed_version == ""


def test_chromium_check_plugin_unpacked_secure_preferences_matching_path(mock_env, dummy_plugin_data):
    """Secure Preferences with unpacked extension matching folder path => installed True."""
    chrome_profile = mock_env / "Library" / "Application Support" / "Google" / "Chrome" / "Default"
    chrome_profile.mkdir(parents=True)
    unpacked_path = os.path.join(os.path.dirname(dummy_plugin_data.plugin_path), "chromium-extension")

    secure_pref = chrome_profile / "Secure Preferences"
    secure_pref.write_text(
        json.dumps(
            {
                "extensions": {
                    "settings": {
                        "randomgeneratedidforunpacked001": {
                            "path": unpacked_path,
                            "state": 1,
                            "manifest": {
                                "name": "Some Custom Title",
                                "version": "5.2.12",
                            },
                        }
                    }
                }
            }
        )
    )

    manager = ChromiumPluginManager(dummy_plugin_data, user_data_rel_path="Google/Chrome")
    with patch.object(manager, "check_browser", return_value=True):
        status = manager.check_plugin()
        assert status.installed is True
        assert status.latest is True
        assert status.installed_version == "5.2.12"


def test_chromium_check_plugin_unpacked_matching_name_different_path(mock_env, dummy_plugin_data):
    """Secure Preferences with matching manifest.name but different path => installed True."""
    chrome_profile = mock_env / "Library" / "Application Support" / "Google" / "Chrome" / "Profile 2"
    chrome_profile.mkdir(parents=True)

    secure_pref = chrome_profile / "Secure Preferences"
    secure_pref.write_text(
        json.dumps(
            {
                "extensions": {
                    "settings": {
                        "randomgeneratedidforunpacked002": {
                            "path": "/opt/custom/location/extension",
                            "state": 1,
                            "manifest": {
                                "name": "Astron Browser Plugin",
                                "version": "5.2.12",
                            },
                        }
                    }
                }
            }
        )
    )

    manager = ChromiumPluginManager(dummy_plugin_data, user_data_rel_path="Google/Chrome")
    with patch.object(manager, "check_browser", return_value=True):
        status = manager.check_plugin()
        assert status.installed is True
        assert status.latest is True
        assert status.installed_version == "5.2.12"


def test_chromium_check_plugin_disabled_not_installed(mock_env, dummy_plugin_data):
    """Extension with state == 0 or non-empty disable_reasons must be treated as not installed."""
    chrome_profile = mock_env / "Library" / "Application Support" / "Google" / "Chrome" / "Default"
    chrome_profile.mkdir(parents=True)
    unpacked_path = os.path.join(os.path.dirname(dummy_plugin_data.plugin_path), "chromium-extension")

    secure_pref = chrome_profile / "Secure Preferences"
    secure_pref.write_text(
        json.dumps(
            {
                "extensions": {
                    "settings": {
                        "disabled_unpacked_ext": {
                            "path": unpacked_path,
                            "state": 0,
                            "manifest": {
                                "name": "Astron Browser Plugin",
                                "version": "5.2.12",
                            },
                        },
                        "disabled_with_reason_ext": {
                            "path": "/some/other/path",
                            "state": 1,
                            "disable_reasons": [1],
                            "manifest": {
                                "name": "Astron Browser Plugin",
                                "version": "5.2.12",
                            },
                        },
                    }
                }
            }
        )
    )

    manager = ChromiumPluginManager(dummy_plugin_data, user_data_rel_path="Google/Chrome")
    with patch.object(manager, "check_browser", return_value=True):
        status = manager.check_plugin()
        assert status.installed is False


def test_edge_check_plugin_unpacked(mock_env, dummy_plugin_data):
    """Microsoft Edge uses same unpacked detection under Microsoft Edge profile dir."""
    edge_profile = mock_env / "Library" / "Application Support" / "Microsoft Edge" / "Default"
    edge_profile.mkdir(parents=True)
    unpacked_path = os.path.join(os.path.dirname(dummy_plugin_data.plugin_path), "chromium-extension")

    edge_pref = edge_profile / "Preferences"
    edge_pref.write_text(
        json.dumps(
            {
                "extensions": {
                    "settings": {
                        "edge_unpacked_id": {
                            "path": unpacked_path,
                            "state": 1,
                            "manifest": {
                                "name": "Astron Browser Plugin",
                                "version": "5.2.12",
                            },
                        }
                    }
                }
            }
        )
    )

    manager = ChromiumPluginManager(
        dummy_plugin_data,
        app_name="Microsoft Edge",
        bundle_id="com.microsoft.edgemac",
        user_data_rel_path="Microsoft Edge",
        url_scheme="edge",
    )
    with patch.object(manager, "check_browser", return_value=True):
        status = manager.check_plugin()
        assert status.installed is True
        assert status.latest is True
        assert status.installed_version == "5.2.12"


def test_chromium_check_plugin_not_installed(mock_env, dummy_plugin_data):
    manager = ChromiumPluginManager(dummy_plugin_data, user_data_rel_path="Google/Chrome")
    with patch.object(manager, "check_browser", return_value=False):
        status = manager.check_plugin()
        assert status.installed is False
        assert status.latest is False
        assert status.installed_version == ""
        assert status.browser_installed is False


def test_chromium_install_plugin(mock_env, dummy_plugin_data):
    manager = ChromiumPluginManager(dummy_plugin_data, user_data_rel_path="Google/Chrome")

    with patch("subprocess.run") as mock_run:
        msg = manager.install_plugin()
        pref_file = (
            mock_env
            / "Library"
            / "Application Support"
            / "Google"
            / "Chrome"
            / "External Extensions"
            / f"{dummy_plugin_data.plugin_id}.json"
        )
        assert pref_file.exists()
        pref_content = json.loads(pref_file.read_text())
        assert pref_content["external_version"] == "5.2.12"
        assert pref_content["external_crx"] == dummy_plugin_data.plugin_path

        # Verify Finder was opened with -R and browser opened extensions page
        assert mock_run.call_count == 2
        finder_call = mock_run.call_args_list[0]
        assert finder_call[0][0][0:2] == ["open", "-R"]
        browser_call = mock_run.call_args_list[1]
        assert browser_call[0][0] == ["open", "-a", "Google Chrome", "chrome://extensions"]

        # Verify instruction message returned
        assert "开发者模式" in msg
        assert "加载已解压的扩展程序" in msg


def test_firefox_check_and_install(mock_env, dummy_plugin_data):
    ff_data = PluginData(
        plugin_path=dummy_plugin_data.plugin_path,
        plugin_id="astronrpa@example.com",
        plugin_version="5.2.12",
        plugin_name="firefox",
    )
    ff_base = mock_env / "Library" / "Application Support" / "Firefox"
    profile_dir = ff_base / "Profiles" / "test.default-release"
    profile_dir.mkdir(parents=True)

    # Write profiles.ini
    profiles_ini = ff_base / "profiles.ini"
    profiles_ini.write_text("[Profile0]\nName=default\nIsRelative=1\nPath=Profiles/test.default-release\nDefault=1\n")

    manager = FirefoxPluginManager(ff_data)

    # Initially not installed
    with patch.object(manager, "check_browser", return_value=True):
        status = manager.check_plugin()
        assert status.installed is False

    # Simulate installed via extensions.json
    ext_json = profile_dir / "extensions.json"
    ext_json.write_text(
        json.dumps(
            {
                "addons": [
                    {
                        "id": "astronrpa@example.com",
                        "version": "5.2.12",
                        "sourceURI": None,
                    }
                ]
            }
        )
    )

    with patch.object(manager, "check_browser", return_value=True):
        status = manager.check_plugin()
        assert status.installed is True
        assert status.latest is True
        assert status.installed_version == "5.2.12"

    # Test install
    with patch("subprocess.Popen") as mock_popen:
        manager.install_plugin()
        copied_xpi = profile_dir / "extensions" / "astronrpa@example.com.xpi"
        assert copied_xpi.exists()
        assert mock_popen.called


def test_360_browser_unsupported(dummy_plugin_data):
    manager_360 = BrowserPluginFactory.get_plugin_manager(BrowserType.BROWSER_360, dummy_plugin_data)
    assert manager_360.check_browser() is False
    status = manager_360.check_plugin()
    assert status.installed is False
    assert status.browser_installed is False
    with pytest.raises(NotImplementedError):
        manager_360.install_plugin()
