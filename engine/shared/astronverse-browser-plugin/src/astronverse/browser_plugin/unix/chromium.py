import json
import os
import shutil
import subprocess

from astronverse.browser_plugin import PluginData, PluginManagerCore, PluginStatus

# Runtime only checks. Writes to /etc/opt/chrome and /opt/google/chrome/extensions
# happen in the .deb postinst (frontend/packages/electron-app/build/linux/after-install.sh).


class ChromiumPluginManager(PluginManagerCore):
    root_path = "/opt/google/chrome"
    browser_name = "google-chrome-stable"
    process_name = "chrome"
    extension_path = os.path.join(root_path, "extensions")
    policy_dir = "/etc/opt/chrome/policies/managed"

    def __init__(
        self,
        plugin_data: PluginData,
        root_path: str,
        browser_name: str,
        process_name: str,
        policy_dir: str = "",
    ) -> None:
        self.plugin_data = plugin_data
        self.root_path = root_path
        self.browser_name = browser_name
        self.process_name = process_name
        self.extension_path = os.path.join(root_path, "extensions")
        self.policy_dir = policy_dir or (
            "/etc/opt/edge/policies/managed" if "edge" in browser_name else "/etc/opt/chrome/policies/managed"
        )

    def _browser_names(self) -> list[str]:
        names = [self.browser_name]
        if self.browser_name == "google-chrome-stable":
            names.extend(["google-chrome", "chromium", "chromium-browser"])
        elif self.browser_name == "microsoft-edge":
            names.append("microsoft-edge-stable")
        return names

    def check_browser(self):
        return any(shutil.which(name) for name in self._browser_names())

    def check_plugin(self):
        plugin_config_path = os.path.join(self.extension_path, f"{self.plugin_data.plugin_id}.json")
        if os.path.exists(plugin_config_path):
            with open(plugin_config_path, encoding="utf-8") as file:
                plugin_config_data = json.load(file)
                installed_version = plugin_config_data.get("external_version")
                latest_version = self.plugin_data.plugin_version
                latest = installed_version == latest_version
                return PluginStatus(
                    installed=True,
                    installed_version=installed_version,
                    latest_version=latest_version,
                    latest=latest,
                    browser_installed=self.check_browser(),
                )
        return PluginStatus(
            installed=False,
            latest_version=self.plugin_data.plugin_version,
            latest=False,
            browser_installed=self.check_browser(),
        )

    def close_browser(self):
        try:
            subprocess.run(
                ["killall", self.process_name],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    def open_browser(self):
        pass

    def check_browser_running(self) -> bool:
        try:
            result = subprocess.run(
                ["pgrep", "-x", self.process_name],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return result.returncode == 0
        except Exception:
            return False

    def install_plugin(self):
        status = self.check_plugin()
        if status.installed and status.latest:
            return
        raise Exception(
            "Chrome 扩展需由 .deb 安装脚本写入 /etc/opt/chrome/policies/managed 与 "
            "/opt/google/chrome/extensions。请使用官方安装包，或重新安装客户端。"
        )
