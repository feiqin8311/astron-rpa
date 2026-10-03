import configparser
import json
import os
import shutil
import subprocess

from astronverse.baseline.logger.logger import logger
from astronverse.browser_plugin import PluginData, PluginManagerCore, PluginStatus
from astronverse.browser_plugin.config import Config
from astronverse.browser_plugin.mac.chromium import find_mac_app
from astronverse.browser_plugin.utils import FirefoxUtils, is_browser_running


class FirefoxPluginManager(PluginManagerCore):
    def __init__(self, plugin_data: PluginData) -> None:
        self.plugin_data = plugin_data
        self.app_name = "Firefox"
        self.bundle_id = "org.mozilla.firefox"
        self.profile_base_path = os.path.expanduser("~/Library/Application Support/Firefox")

    def check_browser(self) -> bool:
        return find_mac_app(self.app_name, self.bundle_id) is not None

    def get_browser_bin_path(self) -> str | None:
        app_path = find_mac_app(self.app_name, self.bundle_id)
        if app_path:
            bin_path = os.path.join(app_path, "Contents", "MacOS", "firefox")
            if os.path.exists(bin_path):
                return bin_path
        return None

    def check_browser_running(self) -> bool:
        try:
            res = subprocess.run(
                ["pgrep", "-i", "-x", "firefox"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if res.returncode == 0:
                return True
        except Exception:
            pass
        return is_browser_running("firefox")

    def close_browser(self):
        try:
            subprocess.run(
                ["osascript", "-e", 'quit app "Firefox"'],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            pass

    def open_browser(self):
        try:
            subprocess.run(
                ["open", "-a", "Firefox"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            pass

    def _get_firefox_profile_dirs(self) -> list[str]:
        profile_dirs = []
        if not os.path.exists(self.profile_base_path):
            return profile_dirs

        # Try to find profiles from profiles.ini / installs.ini
        profiles_ini = os.path.join(self.profile_base_path, "profiles.ini")
        if os.path.exists(profiles_ini):
            config = configparser.ConfigParser()
            try:
                config.read(profiles_ini)
                for section in config.sections():
                    if config.has_option(section, "Path"):
                        p = config.get(section, "Path")
                        is_rel = config.get(section, "IsRelative", fallback="1")
                        full_p = os.path.join(self.profile_base_path, p) if is_rel == "1" else p
                        if os.path.isdir(full_p) and full_p not in profile_dirs:
                            profile_dirs.append(full_p)
            except Exception:
                pass

        # Scan Profiles directory directly
        profiles_folder = os.path.join(self.profile_base_path, "Profiles")
        if os.path.isdir(profiles_folder):
            for item in os.listdir(profiles_folder):
                item_path = os.path.join(profiles_folder, item)
                if os.path.isdir(item_path) and item_path not in profile_dirs:
                    profile_dirs.append(item_path)

        return profile_dirs

    def check_plugin(self) -> PluginStatus:
        latest_version = self.plugin_data.plugin_version
        browser_installed = self.check_browser()

        # Check default profile via FirefoxUtils
        installed, installed_version = FirefoxUtils.check()
        if installed:
            latest = installed_version == latest_version
            return PluginStatus(
                installed=True,
                installed_version=installed_version,
                latest_version=latest_version,
                latest=latest,
                browser_installed=browser_installed,
            )

        # Scan all profile dirs
        for p_dir in self._get_firefox_profile_dirs():
            ext_json = os.path.join(p_dir, "extensions.json")
            if os.path.exists(ext_json):
                try:
                    with open(ext_json, encoding="utf-8") as f:
                        data = json.load(f)
                        for addon in data.get("addons", []):
                            if addon.get("id") == Config.FIREFOX_PLUGIN_ID:
                                ver = addon.get("version", "")
                                return PluginStatus(
                                    installed=True,
                                    installed_version=ver,
                                    latest_version=latest_version,
                                    latest=(ver == latest_version),
                                    browser_installed=browser_installed,
                                )
                            for file_id in Config.FIREFOX_PLUGIN_FILE_IDS:
                                src_uri = addon.get("sourceURI") or ""
                                if file_id in src_uri:
                                    ver = addon.get("version", "")
                                    return PluginStatus(
                                        installed=True,
                                        installed_version=ver,
                                        latest_version=latest_version,
                                        latest=(ver == latest_version),
                                        browser_installed=browser_installed,
                                    )
                except Exception:
                    pass

            # Check if .xpi exists in profile extensions folder
            xpi_in_profile = os.path.join(p_dir, "extensions", f"{Config.FIREFOX_PLUGIN_ID}.xpi")
            if os.path.exists(xpi_in_profile):
                return PluginStatus(
                    installed=True,
                    installed_version=latest_version,
                    latest_version=latest_version,
                    latest=True,
                    browser_installed=browser_installed,
                )

        return PluginStatus(
            installed=False,
            installed_version="",
            latest_version=latest_version,
            latest=False,
            browser_installed=browser_installed,
        )

    def install_plugin(self):
        # 1. Attempt to place extension .xpi in default profile's extensions dir
        try:
            default_profile = FirefoxUtils.get_default_profile_path()
            ext_dir = os.path.join(default_profile, "extensions")
            os.makedirs(ext_dir, exist_ok=True)
            target_xpi = os.path.join(ext_dir, f"{Config.FIREFOX_PLUGIN_ID}.xpi")
            shutil.copy2(self.plugin_data.plugin_path, target_xpi)
            logger.info(f"Copied Firefox xpi to {target_xpi}")
        except Exception as e:
            logger.warning(f"Could not copy xpi into Firefox profile extensions dir: {e}")

        # 2. Launch Firefox with the .xpi path (Windows/Linux approach)
        bin_path = self.get_browser_bin_path()
        if bin_path:
            subprocess.Popen(
                [bin_path, self.plugin_data.plugin_path],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        else:
            subprocess.Popen(
                ["open", "-a", "Firefox", self.plugin_data.plugin_path],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
