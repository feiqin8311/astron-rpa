import os
import sys

from astronverse.scheduler.logger import logger

if sys.platform == "win32":
    import winreg as reg
else:
    reg = None


class Registry:
    """注册表操作"""

    @staticmethod
    def exist(key_path):
        """
        检测注册表是否存在
        """
        if sys.platform != "win32" or reg is None:
            return False
        try:
            key = reg.OpenKey(reg.HKEY_CURRENT_USER, key_path, 0, reg.KEY_READ)
            reg.CloseKey(key)
            return True
        except Exception:
            return False

    @staticmethod
    def create(key_path):
        """
        创建项
        """
        if sys.platform != "win32" or reg is None:
            return
        keys = key_path.split("\\")
        head_key = reg.OpenKey(reg.HKEY_CURRENT_USER, keys[0], 0, reg.KEY_ALL_ACCESS)
        opened_keys = list()
        opened_keys.append(head_key)
        for key in keys[1:]:
            head_key = reg.CreateKey(head_key, key)
            opened_keys.append(head_key)
        opened_keys.reverse()
        for opened_key in opened_keys:
            reg.CloseKey(opened_key)

    @staticmethod
    def delete(key_path, sub_key):
        """
        删除项
        """
        if sys.platform != "win32" or reg is None:
            return
        key = reg.OpenKey(reg.HKEY_CURRENT_USER, key_path, 0, reg.KEY_SET_VALUE)
        # 删除子项
        reg.DeleteKey(key, sub_key)
        reg.CloseKey(key)

    @staticmethod
    def add_string_value(key_path, value_name, value):
        """
        添加字符串kv对
        """
        if sys.platform != "win32" or reg is None:
            return
        key = reg.OpenKey(reg.HKEY_CURRENT_USER, key_path, 0, reg.KEY_SET_VALUE)
        reg.SetValueEx(key, value_name, 0, reg.REG_SZ, value)
        reg.CloseKey(key)

    @staticmethod
    def get_registry_value(key_path, value_name):
        if sys.platform != "win32" or reg is None:
            return None
        try:
            # 打开注册表键
            key = reg.OpenKey(reg.HKEY_CURRENT_USER, key_path)
            # 获取值
            value, regtype = reg.QueryValueEx(key, value_name)
            # 关闭注册表键
            reg.CloseKey(key)
            return value
        except Exception:
            return None


class AutoStart:
    AUTO_START_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

    @staticmethod
    def launch_agent_path(name="astron-rpa"):
        label = name.replace(" ", "-")
        return os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents", f"com.{label}.plist")

    @staticmethod
    def desktop_path(name="astron-rpa"):
        label = name.replace(" ", "-")
        return os.path.join(os.path.expanduser("~"), ".config", "autostart", f"{label}.desktop")

    @staticmethod
    def check(name="astron-rpa"):
        if sys.platform == "darwin":
            return os.path.isfile(AutoStart.launch_agent_path(name))
        if sys.platform.startswith("linux"):
            return os.path.isfile(AutoStart.desktop_path(name))
        if sys.platform != "win32":
            return False
        exe_path = Registry.get_registry_value(AutoStart.AUTO_START_KEY_PATH, name)
        if not exe_path or exe_path != exe_path:
            return False
        return True

    @staticmethod
    def enable(exe_path: str, name="astron-rpa"):
        if sys.platform == "darwin":
            if AutoStart.check(name):
                return
            plist_path = AutoStart.launch_agent_path(name)
            os.makedirs(os.path.dirname(plist_path), exist_ok=True)
            label = name.replace(" ", "-")
            escaped = exe_path.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
            body = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                '<plist version="1.0">\n'
                "<dict>\n"
                "  <key>Label</key>\n"
                f"  <string>com.{label}</string>\n"
                "  <key>ProgramArguments</key>\n"
                "  <array>\n"
                f"    <string>{escaped}</string>\n"
                "  </array>\n"
                "  <key>RunAtLoad</key>\n"
                "  <true/>\n"
                "</dict>\n"
                "</plist>\n"
            )
            with open(plist_path, "w", encoding="utf-8") as fh:
                fh.write(body)
            return
        if sys.platform.startswith("linux"):
            if AutoStart.check(name):
                return
            desktop_path = AutoStart.desktop_path(name)
            os.makedirs(os.path.dirname(desktop_path), exist_ok=True)
            escaped = exe_path.replace("\\", "\\\\").replace('"', '\\"')
            body = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                f"Name={name}\n"
                f'Exec="{escaped}"\n'
                "X-GNOME-Autostart-enabled=true\n"
                "Hidden=false\n"
            )
            with open(desktop_path, "w", encoding="utf-8") as fh:
                fh.write(body)
            return
        if sys.platform != "win32":
            logger.info("AutoStart.enable is not supported on %s, skipping", sys.platform)
            return
        if AutoStart.check(name):
            return
        Registry.create(AutoStart.AUTO_START_KEY_PATH)
        Registry.add_string_value(AutoStart.AUTO_START_KEY_PATH, name, exe_path)

    @staticmethod
    def disable(name="astron-rpa"):
        if sys.platform == "darwin":
            plist_path = AutoStart.launch_agent_path(name)
            try:
                os.remove(plist_path)
            except FileNotFoundError:
                pass
            return
        if sys.platform.startswith("linux"):
            try:
                os.remove(AutoStart.desktop_path(name))
            except FileNotFoundError:
                pass
            return
        if sys.platform != "win32":
            logger.info("AutoStart.disable is not supported on %s, skipping", sys.platform)
            return
        if not AutoStart.check(name):
            return
        Registry.add_string_value(AutoStart.AUTO_START_KEY_PATH, name, "")
