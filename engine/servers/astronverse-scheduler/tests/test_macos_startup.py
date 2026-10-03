import os
import subprocess
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from astronverse.scheduler.core.schduler.init import linux_env_check, mac_env_check
from astronverse.scheduler.core.schduler.venv import VenvManager
from astronverse.scheduler.core.setup.setup import Process
from astronverse.scheduler.utils.clipboard import Clipboard
from astronverse.scheduler.utils.platform_utils import (
    platform_python_path,
    platform_python_run_dir,
    platform_python_venv_path,
    platform_python_venv_run_dir,
    platform_shell,
)
from astronverse.scheduler.utils.window import AutoStart, Registry

# These tests fake POSIX platforms and assert POSIX path strings, which do not
# hold on a Windows runner.
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only startup tests")


def test_platform_utils_paths_on_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")

    assert platform_python_path("/app/dir") == "/app/dir/bin/python3"
    assert platform_python_venv_path("/app/dir") == "/app/dir/venv/bin/python3"
    assert platform_python_run_dir("/app/dir/bin/python3") == "/app/dir"
    assert platform_python_venv_run_dir("/app/dir/venv/bin/python3") == "/app/dir"
    assert platform_shell(win_shell=True, linux_shell=False) is False


def test_platform_utils_paths_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    assert platform_python_path("/app/dir") == os.path.join("/app/dir", "python.exe")
    assert platform_python_venv_path("/app/dir") == os.path.join("/app/dir", "venv", "Scripts", "python.exe")
    assert platform_shell(win_shell=True, linux_shell=False) is True


def test_linux_env_check_handles_missing_gsettings(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    def mock_run(*args, **kwargs):
        raise FileNotFoundError("No such file or directory: 'gsettings'")

    monkeypatch.setattr(subprocess, "run", mock_run)

    # Should catch FileNotFoundError and not raise
    linux_env_check()


def test_linux_env_check_skipped_on_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")

    called = False

    def mock_run(*args, **kwargs):
        nonlocal called
        called = True
        return MagicMock(stdout="true")

    monkeypatch.setattr(subprocess, "run", mock_run)

    linux_env_check()
    assert not called


def test_mac_env_check_alerts_when_permission_missing(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")

    mock_ax = MagicMock(return_value=False)
    mock_preflight = MagicMock(return_value=False)
    mock_request = MagicMock()
    mock_emit = MagicMock()

    with patch.dict(
        "sys.modules",
        {
            "ApplicationServices": MagicMock(
                AXIsProcessTrustedWithOptions=mock_ax,
                kAXTrustedCheckOptionPrompt="prompt",
            ),
            "Quartz": MagicMock(
                CGPreflightScreenCaptureAccess=mock_preflight,
                CGRequestScreenCaptureAccess=mock_request,
            ),
        },
    ):
        with patch("astronverse.scheduler.core.schduler.init.emit_to_front", mock_emit):
            mac_env_check()

    assert mock_request.called
    assert mock_emit.called
    emit_msg = mock_emit.call_args[1]["msg"]
    assert "系统设置 > 隐私与安全性" in emit_msg["msg"]
    assert "辅助功能" in emit_msg["msg"]
    assert "屏幕录制" in emit_msg["msg"]
    assert "输入监控" in emit_msg["msg"]


def test_mac_env_check_silent_when_permissions_granted(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")

    mock_ax = MagicMock(return_value=True)
    mock_preflight = MagicMock(return_value=True)
    mock_emit = MagicMock()

    with patch.dict(
        "sys.modules",
        {
            "ApplicationServices": MagicMock(
                AXIsProcessTrustedWithOptions=mock_ax,
                kAXTrustedCheckOptionPrompt="prompt",
            ),
            "Quartz": MagicMock(
                CGPreflightScreenCaptureAccess=mock_preflight,
            ),
        },
    ):
        with patch("astronverse.scheduler.core.schduler.init.emit_to_front", mock_emit):
            mac_env_check()

    assert not mock_emit.called


def test_mac_env_check_skipped_on_non_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    mock_emit = MagicMock()
    with patch("astronverse.scheduler.core.schduler.init.emit_to_front", mock_emit):
        mac_env_check()

    assert not mock_emit.called


def test_get_python_proc_in_current_dir_filtering(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")

    venv_prefix = "/test/venv/env"
    base_prefix = "/test/python_base"
    monkeypatch.setattr(sys, "prefix", venv_prefix)
    monkeypatch.setattr(sys, "base_prefix", base_prefix)

    def fake_realpath(path):
        return path

    monkeypatch.setattr(os.path, "realpath", fake_realpath)

    # Mock self process hierarchy
    self_proc = MagicMock()
    self_proc.pid = 100
    ancestor_proc = MagicMock()
    ancestor_proc.pid = 90
    ancestor_proc.parent.return_value = None
    self_proc.parent.return_value = ancestor_proc

    # Mock candidate processes
    # 1. self (pid 100) -> excluded
    proc_self = MagicMock()
    proc_self.pid = 100
    proc_self.info = {
        "pid": 100,
        "name": "python",
        "exe": f"{venv_prefix}/bin/python3",
        "cmdline": ["python3", "-m", "astronverse.scheduler.start"],
    }

    # 2. ancestor (pid 90) -> excluded
    proc_ancestor = MagicMock()
    proc_ancestor.pid = 90
    proc_ancestor.info = {
        "pid": 90,
        "name": "python",
        "exe": f"{venv_prefix}/bin/python3",
        "cmdline": ["python3", "-m", "astronverse.scheduler.start"],
    }

    # 3. unrelated python (pid 101) -> excluded
    proc_unrelated = MagicMock()
    proc_unrelated.pid = 101
    proc_unrelated.info = {
        "pid": 101,
        "name": "python",
        "exe": f"{venv_prefix}/bin/python3",
        "cmdline": ["python3", "script.py"],
    }

    # 4. astronverse module with same prefix (pid 102) -> included
    proc_astron_mod = MagicMock()
    proc_astron_mod.pid = 102
    proc_astron_mod.info = {
        "pid": 102,
        "name": "python",
        "exe": f"{venv_prefix}/bin/python3",
        "cmdline": ["python3", "-m", "astronverse.engine.main"],
    }

    # 5. astronverse module but unrelated python install (pid 103) -> excluded
    proc_diff_python = MagicMock()
    proc_diff_python.pid = 103
    proc_diff_python.info = {
        "pid": 103,
        "name": "python",
        "exe": "/usr/local/bin/python3",
        "cmdline": ["python3", "-m", "astronverse.engine.main"],
    }

    # 6. astron-rpa exe with same prefix (pid 104) -> included
    proc_astron_exe = MagicMock()
    proc_astron_exe.pid = 104
    proc_astron_exe.info = {
        "pid": 104,
        "name": "astron-rpa",
        "exe": f"{venv_prefix}/bin/astron-rpa",
        "cmdline": ["astron-rpa"],
    }

    mock_process_class = MagicMock(return_value=self_proc)
    mock_process_iter = MagicMock(
        return_value=[
            proc_self,
            proc_ancestor,
            proc_unrelated,
            proc_astron_mod,
            proc_diff_python,
            proc_astron_exe,
        ]
    )

    with patch("psutil.Process", mock_process_class), patch("psutil.process_iter", mock_process_iter):
        result = Process.get_python_proc_in_current_dir()

    assert result == [proc_astron_mod, proc_astron_exe]


def test_remove_temp_venv_on_non_win32(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")

    with tempfile.TemporaryDirectory() as tmpdir:
        svc = MagicMock()
        svc.config.venv_base_dir = tmpdir

        # Create a dot temp dir (like .temp_venv1)
        dot_dir = os.path.join(tmpdir, ".temp_venv1")
        os.makedirs(dot_dir, exist_ok=True)

        # Create a broken venv dir without 'venv' subdirectory
        broken_dir = os.path.join(tmpdir, "broken_venv")
        os.makedirs(broken_dir, exist_ok=True)

        # Create a valid venv dir with 'venv' subdirectory
        valid_dir = os.path.join(tmpdir, "valid_venv", "venv")
        os.makedirs(valid_dir, exist_ok=True)

        VenvManager.remove_temp_venv(svc)

        assert not os.path.exists(dot_dir)
        assert not os.path.exists(broken_dir)
        assert os.path.exists(os.path.join(tmpdir, "valid_venv"))


def test_window_utils_on_darwin(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))

    assert Registry.exist(r"Software\Test") is False
    assert Registry.get_registry_value(r"Software\Test", "Key") is None
    # No-op calls must not raise
    Registry.create(r"Software\Test")
    Registry.delete(r"Software\Test", "Sub")
    Registry.add_string_value(r"Software\Test", "Key", "Val")

    assert AutoStart.check() is False
    AutoStart.enable("/path/to/astron-rpa")
    assert AutoStart.check() is True
    plist = AutoStart.launch_agent_path()
    assert os.path.isfile(plist)
    with open(plist, encoding="utf-8") as fh:
        body = fh.read()
    assert "/path/to/astron-rpa" in body
    assert "RunAtLoad" in body
    AutoStart.disable()
    assert AutoStart.check() is False


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS clipboard test")
def test_clipboard_roundtrip_darwin():
    test_str = "星辰RPA 剪切板测试内容\n换行与emoji: 🚀 ✨ 123"
    Clipboard.copy_str_clip(test_str)

    pasted = Clipboard.paste_str_clip()
    assert pasted == test_str

    html_pasted = Clipboard.paste_html_clip()
    assert html_pasted == test_str
