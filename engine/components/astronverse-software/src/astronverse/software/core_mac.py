import os
import plistlib
import shutil
import subprocess

from astronverse.software.core import ISoftwareCore

APP_SEARCH_DIRS: list[str] = [
    "/Applications",
    "/System/Applications",
    os.path.expanduser("~/Applications"),
]


def get_bundle_executable(app_path: str) -> str:
    """从macOS .app的Info.plist中获取可执行文件名(CFBundleExecutable)，获取失败则返回basename"""
    if not app_path:
        return ""
    bundle_path = app_path
    if not bundle_path.endswith(".app") and ".app/" in bundle_path:
        bundle_path = bundle_path.split(".app/")[0] + ".app"

    plist_path = os.path.join(bundle_path, "Contents", "Info.plist")
    if os.path.exists(plist_path):
        try:
            with open(plist_path, "rb") as fp:
                plist_data = plistlib.load(fp)
            exe = plist_data.get("CFBundleExecutable")
            if exe:
                return str(exe)
        except Exception:
            pass

    base = os.path.basename(app_path.rstrip("/"))
    if base.endswith(".app"):
        return base[:-4]
    return base


def _is_bundle_id(name: str) -> bool:
    """判断是否可能是Bundle Identifier (例如 com.google.Chrome)"""
    return (
        "." in name
        and " " not in name
        and "/" not in name
        and not name.lower().endswith((".app", ".exe"))
        and not name.startswith(".")
    )


def _run_mdfind(query: str) -> str:
    """执行mdfind查询并返回第一个存在的路径"""
    try:
        res = subprocess.run(
            ["mdfind", query],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if res.returncode == 0 and res.stdout:
            for line in res.stdout.splitlines():
                path = line.strip()
                if path and os.path.exists(path):
                    return path
    except (subprocess.SubprocessError, OSError):
        pass
    return ""


class SoftwareCore(ISoftwareCore):
    APP_SEARCH_DIRS = APP_SEARCH_DIRS

    @staticmethod
    def get_bundle_executable(app_path: str) -> str:
        return get_bundle_executable(app_path)

    @staticmethod
    def get_app_path(app_name: str = "") -> str:
        """
        在macOS上获取软件路径：
        支持 "Google Chrome", "Google Chrome.app", "chrome", bundle id 如 "com.google.Chrome", 或可执行文件名。
        解析顺序：
        1. 存在的绝对路径 -> 直接返回
        2. /Applications/<name>.app, /System/Applications/<name>.app, ~/Applications/<name>.app (不区分大小写匹配)
        3. Bundle ID -> mdfind "kMDItemCFBundleIdentifier == '<id>'"
        4. DisplayName / FSName -> mdfind
        5. shutil.which(app_name)
        找不到返回 ""
        """
        if not app_name:
            return ""

        # 1. 存在的绝对路径 (含用户主目录 ~ 展开)
        expanded = os.path.expanduser(app_name)
        if os.path.isabs(expanded) and os.path.exists(expanded):
            return expanded

        # 2. 遍历标准应用程序目录（支持不区分大小写匹配）
        name_with_app = app_name if app_name.lower().endswith(".app") else f"{app_name}.app"
        search_dirs = SoftwareCore.APP_SEARCH_DIRS if SoftwareCore.APP_SEARCH_DIRS is not None else APP_SEARCH_DIRS
        for search_dir in search_dirs:
            if not os.path.isdir(search_dir):
                continue
            try:
                for entry in os.listdir(search_dir):
                    if entry.lower() == name_with_app.lower():
                        full_path = os.path.join(search_dir, entry)
                        if os.path.exists(full_path):
                            return full_path
            except OSError:
                continue

        # 3. 如果是Bundle Identifier格式，通过mdfind根据CFBundleIdentifier查找
        if _is_bundle_id(app_name):
            escaped_id = app_name.replace('"', '\\"')
            found = _run_mdfind(f'kMDItemCFBundleIdentifier == "{escaped_id}"')
            if found:
                return found

        # 4. 通过mdfind查找DisplayName或FSName
        clean_name = app_name[:-4] if app_name.lower().endswith(".app") else app_name
        escaped_clean = clean_name.replace("'", "\\'")
        escaped_app = name_with_app.replace("'", "\\'")

        # 尝试通过kMDItemDisplayName查找（兼顾kMDItemContentType与kMDItemKind多语言环境）
        found = _run_mdfind(
            f"(kMDItemContentType == 'com.apple.application-bundle' || kMDItemKind == 'Application') "
            f"&& kMDItemDisplayName == '{escaped_clean}'c"
        )
        if found:
            return found

        # 尝试通过kMDItemFSName查找
        found = _run_mdfind(
            f"kMDItemContentType == 'com.apple.application-bundle' && kMDItemFSName == '{escaped_app}'c"
        )
        if found:
            return found

        # 5. 可执行文件 (CLI工具，如 which)
        which_path = shutil.which(app_name)
        if which_path:
            return which_path

        return ""
