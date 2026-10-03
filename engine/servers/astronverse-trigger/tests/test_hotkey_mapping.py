import subprocess
import sys

import pytest
from astronverse.trigger.tasks.hotkey_task import HotKeyTask, to_pynput_hotkey


def test_to_pynput_hotkey_basic():
    assert to_pynput_hotkey(["ctrl", "alt", "a"]) == "<ctrl>+<alt>+a"
    assert to_pynput_hotkey(["Ctrl", "Shift", "F1"]) == "<ctrl>+<shift>+<f1>"
    assert to_pynput_hotkey(["ctrl", "shift", "z"]) == "<ctrl>+<shift>+z"


def test_to_pynput_hotkey_modifiers():
    assert to_pynput_hotkey(["control", "option", "a"]) == "<ctrl>+<alt>+a"
    assert to_pynput_hotkey(["win", "cmd", "command", "super", "meta"]) == "<cmd>+<cmd>+<cmd>+<cmd>+<cmd>"
    assert to_pynput_hotkey(["opt", "windows"]) == "<alt>+<cmd>"


def test_to_pynput_hotkey_function_keys():
    for i in range(1, 13):
        assert to_pynput_hotkey([f"F{i}"]) == f"<f{i}>"
        assert to_pynput_hotkey([f"f{i}"]) == f"<f{i}>"


def test_to_pynput_hotkey_special_keys():
    assert to_pynput_hotkey(["esc"]) == "<esc>"
    assert to_pynput_hotkey(["escape"]) == "<esc>"
    assert to_pynput_hotkey(["enter"]) == "<enter>"
    assert to_pynput_hotkey(["return"]) == "<enter>"
    assert to_pynput_hotkey(["space"]) == "<space>"
    assert to_pynput_hotkey(["spacebar"]) == "<space>"
    assert to_pynput_hotkey(["tab"]) == "<tab>"
    assert to_pynput_hotkey(["backspace"]) == "<backspace>"
    assert to_pynput_hotkey(["delete"]) == "<delete>"
    assert to_pynput_hotkey(["del"]) == "<delete>"
    assert to_pynput_hotkey(["up", "down", "left", "right"]) == "<up>+<down>+<left>+<right>"
    assert to_pynput_hotkey(["home", "end"]) == "<home>+<end>"
    assert to_pynput_hotkey(["page_up", "pagedown"]) == "<page_up>+<page_down>"
    assert to_pynput_hotkey(["pageup", "page_down"]) == "<page_up>+<page_down>"


def test_to_pynput_hotkey_printable_characters():
    assert to_pynput_hotkey(["A"]) == "a"
    assert to_pynput_hotkey(["1"]) == "1"
    assert to_pynput_hotkey(["ctrl", "Z"]) == "<ctrl>+z"


def test_to_pynput_hotkey_combined_strings():
    assert to_pynput_hotkey(["Ctrl + Shift + F5"]) == "<ctrl>+<shift>+<f5>"
    assert to_pynput_hotkey(["ctrl+alt+a"]) == "<ctrl>+<alt>+a"


def test_to_pynput_hotkey_empty():
    assert to_pynput_hotkey([]) == ""
    assert to_pynput_hotkey(None) == ""


@pytest.mark.skipif(sys.platform != "darwin", reason="Only runs on macOS (darwin)")
def test_pynput_parse_validity():
    from pynput.keyboard import HotKey

    shortcuts_list = [
        ["ctrl", "alt", "a"],
        ["Ctrl", "Shift", "F1"],
        ["win", "space"],
        ["esc"],
        ["enter"],
        ["page_up"],
        ["page_down"],
        ["home"],
        ["end"],
        ["up"],
        ["down"],
        ["left"],
        ["right"],
        ["backspace"],
        ["delete"],
        ["tab"],
    ]
    for sc in shortcuts_list:
        pynput_expr = to_pynput_hotkey(sc)
        # Should parse without raising ValueError or AttributeError
        parsed = HotKey.parse(pynput_expr)
        assert len(parsed) > 0


@pytest.mark.skipif(sys.platform != "darwin", reason="Only runs on macOS (darwin)")
def test_hotkey_task_does_not_import_keyboard_on_darwin():
    cmd = [
        sys.executable,
        "-c",
        (
            "import sys\n"
            "import astronverse.trigger.tasks.hotkey_task\n"
            "assert 'keyboard' not in sys.modules, 'keyboard module must not be imported on darwin'\n"
            "print('OK')\n"
        ),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, f"Subprocess failed:\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    assert "OK" in proc.stdout


def test_hotkey_task_initialization_and_cleanup():
    task = HotKeyTask(shortcuts=["ctrl", "alt", "a"])
    assert task.shortcuts == ["ctrl", "alt", "a"]
    assert task._h_handle is None
    # force_end_callback should not raise when _h_handle is None
    if sys.platform == "darwin":
        task.force_end_callback()
