"""Platform independent checks for the macOS picker wiring."""

import subprocess
import sys

from astronverse.picker import APP
from astronverse.picker.core.event_core_mac import process_event
from astronverse.picker.core.picker_core_mac import PickerCore


def test_app_init_macos_names():
    assert APP.init("Google Chrome") is APP.Chrome
    assert APP.init("Microsoft Edge") is APP.Edge
    assert APP.init("Chromium") is APP.Chromium
    assert APP.init("FIREFOX") is APP.Firefox


def test_element_domain():
    core = PickerCore()

    class AXElement:
        pass

    class WEBElement:
        pass

    assert core._get_element_domain(AXElement()) == "ax"
    assert core._get_element_domain(WEBElement()) == "web"


def test_event_gesture_rules():
    swallowed, state = process_event("flagsChanged", 1 << 18)
    assert not swallowed
    assert state["control_down"]
    swallowed, state = process_event("leftMouseDown", state=state)
    assert swallowed
    assert state["focus"]
    swallowed, state = process_event("leftMouseUp", state=state)
    assert swallowed
    assert not state["swallow_mouse_up"]
    _, state = process_event("keyUp", keycode=53, state=state)
    assert state["cancel"]
    _, state = process_event("keyUp", keycode=118, state=state)
    assert state["f4"]


def test_picker_imports_with_darwin_platform():
    code = "import sys; sys.platform = 'darwin'; import astronverse.picker.start, astronverse.picker.server.ws_server"
    subprocess.run([sys.executable, "-c", code], check=True)
