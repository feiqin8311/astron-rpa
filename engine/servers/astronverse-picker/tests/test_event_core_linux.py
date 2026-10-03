from astronverse.picker.core.event_core_linux import process_event


def test_ctrl_click_sets_focus():
    state = {}
    _, state = process_event("press", "ctrl", state)
    swallow, state = process_event("click", "left", state)
    assert swallow is True
    assert state["focus"] is True


def test_esc_cancels():
    _, state = process_event("press", "esc", {})
    assert state["cancel"] is True


def test_f4_flag():
    _, state = process_event("release", "f4", {})
    assert state["f4"] is True
