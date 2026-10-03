from astronverse.executor.debug.recording import parse_avfoundation_screen_index, resolve_darwin_ffmpeg

AVFOUNDATION_LIST_SAMPLE = """\
[AVFoundation indev @ 0x7f8] AVFoundation video devices:
[AVFoundation indev @ 0x7f8] [0] FaceTime HD Camera
[AVFoundation indev @ 0x7f8] [1] Capture screen 0
[AVFoundation indev @ 0x7f8] [2] Capture screen 1
[AVFoundation indev @ 0x7f8] AVFoundation audio devices:
[AVFoundation indev @ 0x7f8] [0] MacBook Pro Microphone
"""


def test_parse_avfoundation_first_capture_screen():
    assert parse_avfoundation_screen_index(AVFOUNDATION_LIST_SAMPLE) == "1"


def test_parse_avfoundation_no_screen_returns_none():
    assert parse_avfoundation_screen_index("[0] FaceTime HD Camera") is None


def test_resolve_ffmpeg_prefers_bundled_executable(tmp_path, monkeypatch):
    bundled = tmp_path / "ffmpeg"
    bundled.write_text("")
    bundled.chmod(0o755)
    monkeypatch.setattr(
        "astronverse.executor.debug.recording.shutil.which",
        lambda _name: "/usr/bin/ffmpeg",
    )
    assert resolve_darwin_ffmpeg(str(tmp_path)) == str(bundled)


def test_resolve_ffmpeg_falls_back_to_which(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "astronverse.executor.debug.recording.shutil.which",
        lambda _name: "/opt/homebrew/bin/ffmpeg",
    )
    assert resolve_darwin_ffmpeg(str(tmp_path)) == "/opt/homebrew/bin/ffmpeg"


def test_resolve_ffmpeg_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("astronverse.executor.debug.recording.shutil.which", lambda _name: None)
    assert resolve_darwin_ffmpeg(str(tmp_path)) is None
