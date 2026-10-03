import plistlib
import shutil
import subprocess
import sys
from unittest.mock import MagicMock

import psutil
import pytest
from astronverse.software import core_mac
from astronverse.software.core_mac import SoftwareCore, get_bundle_executable
from astronverse.software.software import Software
from astronverse.software.software import SoftwareCore as InstantiatedCore


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS specific tests")
class TestMacOSSoftware:
    def test_import_software_darwin(self):
        """测试在 macOS (Darwin) 环境下导入 software 模块"""
        assert Software is not None
        assert InstantiatedCore is not None
        assert isinstance(InstantiatedCore, core_mac.ISoftwareCore)

    def test_info_plist_executable_parsing(self, tmp_path):
        """测试从 Info.plist 解析 CFBundleExecutable"""
        app_bundle = tmp_path / "FakeApp.app"
        contents_dir = app_bundle / "Contents"
        contents_dir.mkdir(parents=True)
        plist_path = contents_dir / "Info.plist"

        plist_data = {
            "CFBundleExecutable": "MyFakeBinary",
            "CFBundleName": "FakeAppName",
        }
        with open(plist_path, "wb") as f:
            plistlib.dump(plist_data, f)

        # 传入 .app 目录路径
        exe = get_bundle_executable(str(app_bundle))
        assert exe == "MyFakeBinary"

        # 传入 .app 内部路径
        inner_path = app_bundle / "Contents" / "MacOS" / "something"
        assert get_bundle_executable(str(inner_path)) == "MyFakeBinary"

        # 无 Info.plist 的回退测试
        plain_app = tmp_path / "PlainApp.app"
        plain_app.mkdir(parents=True)
        assert get_bundle_executable(str(plain_app)) == "PlainApp"

        # 空路径测试
        assert get_bundle_executable("") == ""

    def test_get_app_path_with_tmp_fake_app_dirs(self, tmp_path, monkeypatch):
        """测试 get_app_path 在临时假 .app 目录下的搜索（monkeypatch 搜索路径）"""
        fake_apps_dir = tmp_path / "Applications"
        fake_apps_dir.mkdir(parents=True)

        app1 = fake_apps_dir / "Google Chrome.app"
        app1.mkdir()
        app2 = fake_apps_dir / "Visual Studio Code.app"
        app2.mkdir()

        # Monkeypatch 搜索根目录
        monkeypatch.setattr(core_mac, "APP_SEARCH_DIRS", [str(fake_apps_dir)])
        monkeypatch.setattr(SoftwareCore, "APP_SEARCH_DIRS", [str(fake_apps_dir)])

        # 1. 精确名称（不带 .app）
        found = SoftwareCore.get_app_path("Google Chrome")
        assert found == str(app1)

        # 2. 精确名称（带 .app）
        found = SoftwareCore.get_app_path("Google Chrome.app")
        assert found == str(app1)

        # 3. 大小写不敏感匹配
        found = SoftwareCore.get_app_path("google chrome")
        assert found == str(app1)

        found = SoftwareCore.get_app_path("visual studio code.app")
        assert found == str(app2)

        # 4. 不存在的应用程序返回 ""
        found = SoftwareCore.get_app_path("NonExistentApp")
        assert found == ""

    def test_get_app_path_absolute_path(self, tmp_path):
        """测试绝对路径直接返回"""
        custom_bin = tmp_path / "my_custom_tool"
        custom_bin.write_text("binary content")

        found = SoftwareCore.get_app_path(str(custom_bin))
        assert found == str(custom_bin)

        # 空参数返回空
        assert SoftwareCore.get_app_path("") == ""

    def test_get_app_path_bundle_id(self, tmp_path, monkeypatch):
        """测试通过 Bundle ID 查找应用 (mdfind CFBundleIdentifier)"""
        monkeypatch.setattr(core_mac, "APP_SEARCH_DIRS", [str(tmp_path / "Empty")])
        monkeypatch.setattr(SoftwareCore, "APP_SEARCH_DIRS", [str(tmp_path / "Empty")])

        fake_app = tmp_path / "Safari.app"
        fake_app.mkdir()

        def fake_run(cmd, *args, **kwargs):
            query = cmd[1]
            if "CFBundleIdentifier" in query and "com.apple.Safari" in query:
                res = MagicMock()
                res.returncode = 0
                res.stdout = f"{str(fake_app)}\n"
                return res
            res = MagicMock()
            res.returncode = 0
            res.stdout = ""
            return res

        monkeypatch.setattr(subprocess, "run", fake_run)

        found = SoftwareCore.get_app_path("com.apple.Safari")
        assert found == str(fake_app)

    def test_get_app_path_shutil_which(self, tmp_path, monkeypatch):
        """测试回退到 shutil.which 查找 CLI 工具"""
        monkeypatch.setattr(core_mac, "APP_SEARCH_DIRS", [str(tmp_path / "Empty")])
        monkeypatch.setattr(SoftwareCore, "APP_SEARCH_DIRS", [str(tmp_path / "Empty")])
        monkeypatch.setattr(core_mac, "_run_mdfind", lambda q: "")

        monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/git" if cmd == "git" else None)

        found = SoftwareCore.get_app_path("git")
        assert found == "/usr/bin/git"

    def test_pid_matching_on_macos(self):
        """测试 macOS 下进程名不带 .exe / 带 .app 的匹配"""
        current_proc = psutil.Process()
        proc_name = current_proc.name()

        # 原名匹配
        pid1 = Software.pid(proc_name)
        assert pid1 > 0

        # 带 .exe 伪后缀在 macOS 上应该也能匹配到
        pid2 = Software.pid(f"{proc_name}.exe")
        assert pid2 == pid1

        # exists 方法
        assert Software.exists(proc_name)
        assert Software.exists(f"{proc_name}.exe")
        assert not Software.exists("definitely_nonexistent_process_12345")

    def test_open_app_mocked(self, tmp_path, monkeypatch):
        """测试打开 .app 应用程序时调用 open -a，不启动真实应用"""
        fake_app = tmp_path / "TestOpen.app"
        fake_app.mkdir()

        called_cmd = []

        class FakePopen:
            def __init__(self, cmd, *args, **kwargs):
                called_cmd.extend(cmd)
                self.pid = 99999

        monkeypatch.setattr(subprocess, "Popen", FakePopen)

        result = Software.open(app_absolute_path=str(fake_app), app_arguments="--arg1 val1")
        assert result == str(fake_app)
        assert called_cmd == ["open", "-a", str(fake_app), "--args", "--arg1", "val1"]

    def test_close_app_mocked(self, tmp_path, monkeypatch):
        """测试关闭 .app 应用程序时通过 osascript 优雅退出，不关闭真实应用"""
        fake_app = tmp_path / "TestClose.app"
        contents_dir = fake_app / "Contents"
        contents_dir.mkdir(parents=True)
        plist_path = contents_dir / "Info.plist"

        plist_data = {
            "CFBundleExecutable": "TestCloseExec",
            "CFBundleName": "TestCloseName",
        }
        with open(plist_path, "wb") as f:
            plistlib.dump(plist_data, f)

        osascript_calls = []

        def fake_run(cmd, *args, **kwargs):
            if cmd[0] == "osascript":
                osascript_calls.append(cmd)
            return MagicMock(returncode=0)

        monkeypatch.setattr(subprocess, "run", fake_run)
        # 模拟没有残留进程
        monkeypatch.setattr(psutil, "process_iter", lambda *args, **kwargs: [])

        Software.close(app_absolute_path=str(fake_app))
        assert len(osascript_calls) == 1
        assert 'quit app "TestCloseName"' in osascript_calls[0][2]
