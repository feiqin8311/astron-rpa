import json
import socket
import subprocess
import sys
import time
from unittest.mock import MagicMock

import pytest
from astronverse.scheduler.core.picker.mac.highlighter import (
    BLINK_CYCLES,
    BLINK_VALIDATE_MS,
    HINT_TEXT_CV,
    Box,
    HLState,
    ScreenFrame,
    apply_message,
    box_to_flipped_local,
    hint_text_for,
    parse_datagram,
    tick_blink,
    top_left_to_cocoa_point,
)

PRIMARY = ScreenFrame(0, 0, 1440, 900)


def test_parse_datagram_accepts_bytes_and_str():
    payload = {"Operation": "start", "Type": "normal"}
    raw = json.dumps(payload)
    assert parse_datagram(raw) == payload
    assert parse_datagram(raw.encode("utf-8")) == payload


def test_parse_datagram_rejects_garbage():
    assert parse_datagram(b"\xff\xfe not json") is None
    assert parse_datagram("{") is None
    assert parse_datagram("[1, 2]") is None


def test_apply_start_sets_mode_and_cv_hint():
    state = HLState()
    apply_message(state, {"Operation": "start", "Type": "normal"})
    assert state.mode == "normal"
    assert state.hint_visible is False

    apply_message(state, {"Operation": "start", "Type": "CV"})
    assert state.mode == "CV"
    assert state.hint_visible is True
    assert state.hint_mode == "CV"
    assert hint_text_for("CV") == HINT_TEXT_CV

    apply_message(state, {"Operation": "start", "Type": "hide"})
    assert state.hint_visible is False


def test_apply_picking_one_box_draws_msg_without_blink():
    state = HLState()
    apply_message(
        state,
        {
            "Operation": "picking",
            "Type": "normal",
            "Boxes": [{"Left": 10, "Top": 20, "Right": 110, "Bottom": 80, "Msg": "OK"}],
        },
    )
    assert state.visible is True
    assert state.blink is None
    assert len(state.boxes) == 1
    assert state.boxes[0].msg == "OK"
    assert state.boxes[0].left == 10
    assert state.boxes[0].bottom == 80


def test_apply_picking_several_boxes_blinks_three_times():
    state = HLState()
    apply_message(
        state,
        {
            "Operation": "picking",
            "Type": "normal",
            "Boxes": [
                {"Left": 0, "Top": 0, "Right": 10, "Bottom": 10, "Msg": "A"},
                {"Left": 20, "Top": 20, "Right": 40, "Bottom": 50, "Msg": "B"},
            ],
        },
    )
    assert state.visible is True
    assert state.blink is not None
    assert state.blink.cycles_left == BLINK_CYCLES
    assert state.blink.clear_after is False
    for _ in range(BLINK_CYCLES * 2):
        tick_blink(state)
    assert state.blink is None
    assert state.visible is True
    assert len(state.boxes) == 2


def test_apply_validate_blinks_then_clears():
    state = HLState()
    apply_message(
        state,
        {
            "Operation": "validate",
            "Boxes": [{"Left": 1, "Top": 2, "Right": 3, "Bottom": 4, "Msg": ""}],
        },
    )
    assert state.mode == "validate"
    assert state.blink is not None
    assert state.blink.interval_ms == BLINK_VALIDATE_MS
    assert state.blink.clear_after is True
    for _ in range(BLINK_CYCLES * 2):
        tick_blink(state)
    assert state.blink is None
    assert state.visible is False
    assert state.boxes == []


def test_initialize_esc_shift_exit():
    state = HLState()
    apply_message(state, {"Operation": "start", "Type": "CV"})
    apply_message(
        state,
        {"Operation": "picking", "Boxes": [{"Left": 0, "Top": 0, "Right": 5, "Bottom": 5, "Msg": ""}]},
    )
    apply_message(state, {"Operation": "initialize", "Type": "ESC"})
    assert state.visible is False
    assert state.boxes == []
    assert state.hint_visible is False
    assert state.should_exit is False

    apply_message(state, {"Operation": "start", "Type": "CV"})
    apply_message(state, {"Operation": "initialize", "Type": "SHIFT"})
    assert state.visible is False
    assert state.hint_visible is True

    apply_message(state, {"Operation": "initialize", "Type": "Exit"})
    assert state.should_exit is True
    assert state.hint_visible is False


def test_top_left_to_cocoa_on_primary():
    # 主屏顶左 (0,0) -> Cocoa (0, height)
    assert top_left_to_cocoa_point(0, 0, PRIMARY) == (0, 900)
    assert top_left_to_cocoa_point(100, 50, PRIMARY) == (100, 850)


def test_box_to_flipped_local_primary():
    box = Box(100, 50, 200, 150, "x")
    rect = box_to_flipped_local(box, PRIMARY, PRIMARY)
    assert rect == (100, 50, 100, 100)


def test_box_to_flipped_local_secondary_and_no_overlap():
    # 右侧副屏，顶对齐：Cocoa y = 900-1080 = -180
    secondary = ScreenFrame(1440, -180, 1920, 1080)
    box = Box(1500, 100, 1600, 180, "")
    rect = box_to_flipped_local(box, secondary, PRIMARY)
    assert rect == (60, 100, 100, 80)

    on_primary = Box(10, 10, 20, 20, "")
    assert box_to_flipped_local(on_primary, secondary, PRIMARY) is None


def test_box_to_flipped_local_clips_at_edge():
    box = Box(1400, 0, 1500, 40, "")
    rect = box_to_flipped_local(box, PRIMARY, PRIMARY)
    assert rect == (1400, 0, 40, 40)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX path separators")
def test_picker_init_darwin_uses_mac_highlighter_and_real_picker(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    from astronverse.scheduler.core.picker.picker import Picker

    svc = MagicMock()
    svc.config.python_core = "/opt/python/bin/python"
    svc.rpa_hl_port = 11001
    svc.rpa_route_port = 8080
    svc.get_validate_port.return_value = 1234

    picker = Picker(svc)
    picker.init()

    assert picker.highlighter.cmd[0] == "/opt/python/bin/python"
    assert picker.highlighter.cmd[1].endswith("mac/highlighter.py")
    assert picker.highlighter.cmd[2] == "11001"
    assert picker.vision_picker.cmd == ["/opt/python/bin/python", "-m", "astronverse.vision_picker"]
    assert picker.app_picker.cmd == ["/opt/python/bin/python", "-m", "astronverse.picker"]
    assert picker.app_picker.params["highlight_socket_port"] == 11001
    assert picker.app_picker.params["port"] == 1234
    assert picker.app_picker.params["route_port"] == 8080


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX path separators")
def test_picker_init_linux_branch_unchanged(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    from astronverse.scheduler.core.picker.picker import Picker

    svc = MagicMock()
    svc.config.python_core = "/usr/bin/python3"
    svc.rpa_hl_port = 11001
    svc.rpa_route_port = 8080
    svc.get_validate_port.return_value = 1

    picker = Picker(svc)
    picker.init()
    assert picker.highlighter.cmd[1].endswith("linux/RPAHighlighter/cv_match_application_4.0.py")
    assert picker.app_picker.cmd[-1] == "astronverse.picker"


def _free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS highlighter subprocess")
def test_highlighter_exits_on_initialize_exit():
    from astronverse.scheduler.core.picker.mac import highlighter as hl_mod

    port = _free_udp_port()
    proc = subprocess.Popen(
        [sys.executable, hl_mod.__file__, str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        time.sleep(0.4)
        if proc.poll() is not None:
            err = proc.stderr.read() if proc.stderr else ""
            pytest.fail("highlighter exited before Exit was sent: rc={} stderr={}".format(proc.returncode, err))
        deadline = time.time() + 5
        exited = False
        while time.time() < deadline:
            sock.sendto(b'{"Operation":"initialize","Type":"Exit"}', ("127.0.0.1", port))
            try:
                proc.wait(timeout=0.4)
                exited = True
                break
            except subprocess.TimeoutExpired:
                continue
        if not exited:
            proc.kill()
            proc.wait(timeout=2)
            err = proc.stderr.read() if proc.stderr else ""
            pytest.fail("highlighter did not exit within 5s after initialize Exit; stderr={}".format(err))
        err = proc.stderr.read() if proc.stderr else ""
        assert proc.returncode == 0, err
        assert "Traceback" not in (err or "")
    finally:
        sock.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)
