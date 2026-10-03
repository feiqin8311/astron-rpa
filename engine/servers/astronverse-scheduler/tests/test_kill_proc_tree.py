import sys
from unittest.mock import MagicMock

import psutil
import pytest
from astronverse.scheduler.utils.utils import kill_proc_tree

RESOLVED_UV_PYTHON = "/Users/me/.local/share/uv/python/cpython-3.13.0-macos-aarch64-none/bin/python3.13"
VENV_PYTHON = "/Users/me/Projects/astron-rpa/engine/.venv/bin/python"
HIGHLIGHTER = (
    "/Users/me/Projects/astron-rpa/engine/servers/astronverse-scheduler"
    "/src/astronverse/scheduler/core/picker/mac/highlighter.py"
)


def _fake_proc(exe="", cmdline=None, pid=4242):
    proc = MagicMock()
    proc.pid = pid
    proc.exe.return_value = exe
    proc.cmdline.return_value = list(cmdline or [])
    proc.children.return_value = []
    return proc


def test_darwin_kills_symlink_resolved_exe_with_astronverse_module(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    proc = _fake_proc(exe=RESOLVED_UV_PYTHON, cmdline=[VENV_PYTHON, "-m", "astronverse.picker"])
    kill_proc_tree(proc)
    proc.kill.assert_called_once()


def test_darwin_does_not_kill_unrelated_process(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    proc = _fake_proc(exe="/usr/bin/python3", cmdline=["/usr/bin/python3", "-m", "http.server"])
    kill_proc_tree(proc)
    proc.kill.assert_not_called()


def test_win32_does_not_kill_when_exe_lacks_astron_rpa_even_if_cmdline_matches(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    proc = _fake_proc(
        exe=r"C:\Python313\python.exe",
        cmdline=[r"C:\Python313\python.exe", "-m", "astronverse.picker"],
    )
    kill_proc_tree(proc)
    proc.kill.assert_not_called()


def test_win32_kills_when_exe_contains_astron_rpa(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    proc = _fake_proc(
        exe=r"C:\Users\me\astron-rpa\python_core\python.exe",
        cmdline=[r"C:\Users\me\astron-rpa\python_core\python.exe", "-m", "astronverse.picker"],
    )
    kill_proc_tree(proc)
    proc.kill.assert_called_once()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX path matching for highlighter.py")
def test_darwin_kills_highlighter_script(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    proc = _fake_proc(exe=RESOLVED_UV_PYTHON, cmdline=[VENV_PYTHON, HIGHLIGHTER, "9082"])
    kill_proc_tree(proc)
    proc.kill.assert_called_once()


def test_darwin_cmdline_fallback_when_exe_access_denied(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    proc = _fake_proc(cmdline=[VENV_PYTHON, "-m", "astronverse.picker"])
    proc.exe.side_effect = psutil.AccessDenied(pid=4242)
    kill_proc_tree(proc)
    proc.kill.assert_called_once()
