import json
import os
import subprocess

from astronverse.baseline.logger.logger import logger
from astronverse.browser_plugin import PluginData, PluginManagerCore, PluginStatus
from astronverse.browser_plugin.utils import get_profile_list, is_browser_running


def find_mac_app(app_name: str, bundle_id: str) -> str | None:
    """Find application bundle path on macOS."""
    system_app = f"/Applications/{app_name}.app"
    if os.path.exists(system_app):
        return system_app
    user_app = os.path.expanduser(f"~/Applications/{app_name}.app")
    if os.path.exists(user_app):
        return user_app
    try:
        result = subprocess.run(
            ["mdfind", f"kMDItemCFBundleIdentifier == '{bundle_id}'"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.splitlines():
                path = line.strip()
                if path.endswith(".app") and os.path.exists(path):
                    return path
    except Exception:
        pass
    return None


class ChromiumPluginManager(PluginManagerCore):
    def __init__(
        self,
        plugin_data: PluginData,
        app_name: str = "Google Chrome",
        bundle_id: str = "com.google.Chrome",
        user_data_rel_path: str = "Google/Chrome",
        url_scheme: str = "chrome",
    ) -> None:
        self.plugin_data = plugin_data
        self.app_name = app_name
        self.bundle_id = bundle_id
        self.user_data_rel_path = user_data_rel_path
        self.url_scheme = url_scheme
        self.user_data_path = os.path.expanduser(f"~/Library/Application Support/{user_data_rel_path}")
        self.preferences_path_list = get_profile_list(self.user_data_path)
        self.user_external_extensions_dir = os.path.expanduser(
            f"~/Library/Application Support/{user_data_rel_path}/External Extensions"
        )
        self.system_external_extensions_dir = f"/Library/Application Support/{user_data_rel_path}/External Extensions"

    def check_browser(self) -> bool:
        return find_mac_app(self.app_name, self.bundle_id) is not None

    def check_browser_running(self) -> bool:
        try:
            res = subprocess.run(
                ["pgrep", "-x", self.app_name],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if res.returncode == 0:
                return True
        except Exception:
            pass
        return is_browser_running(self.app_name)

    def close_browser(self):
        try:
            subprocess.run(
                ["osascript", "-e", f'quit app "{self.app_name}"'],
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
                ["open", "-a", self.app_name],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            pass

    def _get_unpacked_dir_and_manifest(self) -> tuple[str, str, str]:
        """Return (unpacked_dir_realpath, expected_name, expected_version)."""
        unpacked_dir = ""
        if self.plugin_data.plugin_path:
            candidate = os.path.join(os.path.dirname(self.plugin_data.plugin_path), "chromium-extension")
            if os.path.exists(candidate):
                unpacked_dir = candidate
        if not unpacked_dir:
            pkg_plugins = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins", "chromium-extension"
            )
            if os.path.exists(pkg_plugins):
                unpacked_dir = pkg_plugins

        expected_name = "Astron Browser Plugin"
        expected_version = self.plugin_data.plugin_version
        unpacked_realpath = os.path.realpath(unpacked_dir) if unpacked_dir else ""

        if unpacked_dir:
            manifest_file = os.path.join(unpacked_dir, "manifest.json")
            if os.path.exists(manifest_file):
                try:
                    with open(manifest_file, encoding="utf-8") as f:
                        data = json.load(f)
                        expected_name = data.get("name", expected_name)
                        expected_version = data.get("version", expected_version)
                except Exception:
                    pass

        return unpacked_realpath, expected_name, expected_version

    def _get_installed_versions(self) -> list[str]:
        versions = []
        unpacked_realpath, expected_name, expected_version = self._get_unpacked_dir_and_manifest()

        if not os.path.exists(self.user_data_path):
            return versions

        for item in os.listdir(self.user_data_path):
            if item != "Default" and not item.startswith("Profile"):
                continue
            profile_dir = os.path.join(self.user_data_path, item)
            if not os.path.isdir(profile_dir):
                continue

            # 1. Check profile Extensions directories:
            #    ~/Library/Application Support/.../<Default|Profile *>/Extensions/<id>/<version>_0
            ext_dir = os.path.join(profile_dir, "Extensions", self.plugin_data.plugin_id)
            if os.path.isdir(ext_dir):
                for v_dir in os.listdir(ext_dir):
                    v_dir_path = os.path.join(ext_dir, v_dir)
                    if os.path.isdir(v_dir_path):
                        clean_v = v_dir.split("_")[0]
                        versions.append(clean_v)

            # 2. Check Preferences AND Secure Preferences JSON files in each profile
            for pref_name in ("Preferences", "Secure Preferences"):
                pref_file = os.path.join(profile_dir, pref_name)
                if not os.path.exists(pref_file):
                    continue
                try:
                    with open(pref_file, encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    continue

                settings = data.get("extensions", {}).get("settings")
                if not isinstance(settings, dict):
                    continue

                for ext_id, ext_info in settings.items():
                    if not isinstance(ext_info, dict):
                        continue

                    # Treat state == 0 / disable_reasons non-empty as not installed
                    if ext_info.get("state") == 0:
                        continue
                    disable_reasons = ext_info.get("disable_reasons")
                    if disable_reasons:
                        continue

                    manifest = ext_info.get("manifest") or {}
                    ext_ver = manifest.get("version") or expected_version

                    # Match 1: Official extension ID
                    if ext_id == self.plugin_data.plugin_id:
                        versions.append(str(ext_ver).split("_")[0])
                        continue

                    # Match 2: Unpacked extension matching path
                    ext_path = ext_info.get("path")
                    if ext_path and unpacked_realpath:
                        if os.path.realpath(ext_path) == unpacked_realpath:
                            versions.append(str(ext_ver).split("_")[0])
                            continue

                    # Match 3: Unpacked extension matching manifest.name
                    name = manifest.get("name")
                    if name and name == expected_name:
                        versions.append(str(ext_ver).split("_")[0])
                        continue

        return versions

    def check_plugin(self) -> PluginStatus:
        versions = self._get_installed_versions()
        latest_version = self.plugin_data.plugin_version
        browser_installed = self.check_browser()

        if versions:

            def sort_key(v: str):
                return [int(x) for x in v.split(".") if x.isdigit()]

            installed_version = max(versions, key=sort_key)
            latest = installed_version == latest_version
            return PluginStatus(
                installed=True,
                installed_version=installed_version,
                latest_version=latest_version,
                latest=latest,
                browser_installed=browser_installed,
            )
        else:
            return PluginStatus(
                installed=False,
                installed_version="",
                latest_version=latest_version,
                latest=False,
                browser_installed=browser_installed,
            )

    def install_plugin(self):
        # 1. Write the preference file (works if device is enterprise/MDM managed)
        try:
            os.makedirs(self.user_external_extensions_dir, exist_ok=True)
            pref_file = os.path.join(self.user_external_extensions_dir, f"{self.plugin_data.plugin_id}.json")
            pref_data = {
                "external_crx": self.plugin_data.plugin_path,
                "external_version": self.plugin_data.plugin_version,
            }
            with open(pref_file, "w", encoding="utf-8") as f:
                json.dump(pref_data, f, indent=4)
            logger.info(f"Wrote external extension preference file to {pref_file}")
        except Exception as e:
            logger.warning(f"Could not write external extension preference file: {e}")

        # 2. Reveal unpacked extension in Finder (open -R)
        plugins_dir = os.path.dirname(self.plugin_data.plugin_path)
        unpacked_dir = os.path.join(plugins_dir, "chromium-extension")
        if os.path.exists(unpacked_dir):
            try:
                subprocess.run(["open", "-R", unpacked_dir], check=False)
            except Exception:
                pass

        # 3. Open extensions page in browser
        ext_url = f"{self.url_scheme}://extensions"
        try:
            subprocess.run(["open", "-a", self.app_name, ext_url], check=False)
        except Exception:
            pass

        # 4. Return clear instruction message
        msg = (
            f"已配置扩展偏好设置文件并打开 Finder 目录。\n"
            f"macOS 上的 {self.app_name} 若未加入组织管理（MDM/企业托管），系统会忽略本地离线 .crx 扩展。\n"
            f"请按以下步骤手动加载扩展程序：\n"
            f"1. 在已打开的浏览器扩展页面（{ext_url}）开启右上角“开发者模式”；\n"
            f"2. 点击“加载已解压的扩展程序”；\n"
            f"3. 选择访达中已定位的目录：{unpacked_dir}"
        )
        return msg
