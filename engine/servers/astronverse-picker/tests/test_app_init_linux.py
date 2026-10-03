from astronverse.picker import APP


def test_app_init_linux_chrome_names():
    assert APP.init("google-chrome-stable") is APP.Chrome
    assert APP.init("google-chrome") is APP.Chrome
    assert APP.init("microsoft-edge-stable") is APP.Edge
    assert APP.init("chromium-browser") is APP.Chromium
    assert APP.init("firefox-esr") is APP.Firefox
