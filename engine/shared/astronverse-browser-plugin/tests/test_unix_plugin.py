import pytest
from astronverse.browser_plugin import PluginData
from astronverse.browser_plugin.unix.chromium import ChromiumPluginManager


def test_install_plugin_is_runtime_check_only(tmp_path):
    data = PluginData(plugin_id="hklbenkcbnefkhgodegcoihmgoodlgod", plugin_version="5.2.12")
    mgr = ChromiumPluginManager(
        data,
        root_path=str(tmp_path / "chrome"),
        browser_name="google-chrome-stable",
        process_name="chrome",
    )
    with pytest.raises(Exception, match=".deb"):
        mgr.install_plugin()


def test_check_plugin_missing(tmp_path):
    data = PluginData(plugin_id="hklbenkcbnefkhgodegcoihmgoodlgod", plugin_version="5.2.12")
    mgr = ChromiumPluginManager(
        data,
        root_path=str(tmp_path / "chrome"),
        browser_name="google-chrome-stable",
        process_name="chrome",
    )
    status = mgr.check_plugin()
    assert status.installed is False
