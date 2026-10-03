from astronverse.browser_plugin import BrowserType, PluginData, PluginManager, PluginManagerCore, PluginStatus
from astronverse.browser_plugin.mac.chromium import ChromiumPluginManager
from astronverse.browser_plugin.mac.firefox import FirefoxPluginManager


class UnsupportedPluginManager(PluginManagerCore):
    def __init__(self, plugin_data: PluginData, browser_name: str) -> None:
        self.plugin_data = plugin_data
        self.browser_name = browser_name

    def check_browser(self) -> bool:
        return False

    def check_plugin(self) -> PluginStatus:
        return PluginStatus(
            installed=False,
            latest=False,
            installed_version="",
            latest_version=self.plugin_data.plugin_version,
            browser_installed=False,
        )

    def install_plugin(self):
        raise NotImplementedError(f"{self.browser_name} is not supported on macOS")

    def close_browser(self):
        pass

    def open_browser(self):
        pass

    def check_browser_running(self) -> bool:
        return False


class BrowserPluginFactory(PluginManager):
    @staticmethod
    def get_support_browser() -> list[BrowserType]:
        return [
            BrowserType.CHROME,
            BrowserType.MICROSOFT_EDGE,
            BrowserType.FIREFOX,
        ]

    @staticmethod
    def get_plugin_manager(browser_type: BrowserType, plugin_data: PluginData) -> PluginManagerCore:
        if browser_type == BrowserType.CHROME:
            return ChromiumPluginManager(
                plugin_data,
                app_name="Google Chrome",
                bundle_id="com.google.Chrome",
                user_data_rel_path="Google/Chrome",
                url_scheme="chrome",
            )
        elif browser_type == BrowserType.MICROSOFT_EDGE:
            return ChromiumPluginManager(
                plugin_data,
                app_name="Microsoft Edge",
                bundle_id="com.microsoft.edgemac",
                user_data_rel_path="Microsoft Edge",
                url_scheme="edge",
            )
        elif browser_type == BrowserType.FIREFOX:
            return FirefoxPluginManager(plugin_data)
        elif browser_type in (BrowserType.BROWSER_360, BrowserType.BROWSER_360X):
            return UnsupportedPluginManager(plugin_data, browser_name=browser_type.value)
        else:
            raise ValueError(f"Unsupported browser type: {browser_type}")
