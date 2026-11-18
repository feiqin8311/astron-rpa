import base64
from unittest.mock import MagicMock, patch

from astronverse.vision_picker.core.core import IPickCore


def test_resolve_image_local_file(tmp_path):
    # Test that local files are resolved directly to base64 without network
    test_file = tmp_path / "sample.png"
    fake_content = b"\x89PNG\r\n\x1a\nfakeimagebytes"
    test_file.write_bytes(fake_content)

    resolved = IPickCore.resolve_image(str(test_file), "http://localhost:32742")
    expected_b64 = base64.b64encode(fake_content).decode("utf-8")
    assert resolved == expected_b64


def test_resolve_image_data_uri():
    fake_b64 = "aGVsbG93b3JsZA=="
    data_uri = f"data:image/png;base64,{fake_b64}"
    resolved = IPickCore.resolve_image(data_uri, "http://localhost:32742")
    assert resolved == fake_b64


def test_resolve_image_raw_base64():
    raw_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    resolved = IPickCore.resolve_image(raw_b64, "http://localhost:32742")
    assert resolved == raw_b64


def test_resolve_image_cache_first(tmp_path, monkeypatch):
    # Mock cache dir to tmp_path
    monkeypatch.setattr(IPickCore, "get_asset_cache_dir", staticmethod(lambda: tmp_path))

    fake_content = b"network-image-bytes"
    expected_b64 = base64.b64encode(fake_content).decode("utf-8")

    # First call: cache miss, performs requests.get
    mock_resp = MagicMock()
    mock_resp.content = fake_content
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_resp) as mock_get:
        res1 = IPickCore.resolve_image("/api/resource/file/download?fileId=test1", "http://localhost:32742")
        assert res1 == expected_b64
        assert mock_get.call_count == 1

    # Second call: cache hit, should NOT call requests.get
    with patch("requests.get") as mock_get_second:
        res2 = IPickCore.resolve_image("/api/resource/file/download?fileId=test1", "http://localhost:32742")
        assert res2 == expected_b64
        mock_get_second.assert_not_called()


def test_match_imgs_anchor_url_resolved(monkeypatch):
    # Test that anchor URL is resolved even when target is a URL and gets converted
    calls = []

    def fake_resolve(img_ref, remote_addr):
        calls.append(img_ref)
        # 1x1 png base64
        return "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

    monkeypatch.setattr(IPickCore, "resolve_image", staticmethod(fake_resolve))
    monkeypatch.setattr("cv2.error", Exception)

    data = {
        "img": {
            "self": "/api/resource/file/download?fileId=target123",
            "parent": "/api/resource/file/download?fileId=anchor456",
        },
        "pos": {
            "self_x": 10,
            "self_y": 10,
            "parent_x": 20,
            "parent_y": 20,
        },
        "sr": {
            "screen_w": 1920,
            "screen_h": 1080,
        },
    }

    match_ret = (None, [0, 0, 10, 10])
    with patch("astronverse.vision_picker.core.cv_match.AnchorMatch.process_image", return_value=match_ret):
        with patch.object(IPickCore, "screenshot") as mock_ss:
            from PIL import Image

            mock_ss.return_value = Image.new("RGB", (1920, 1080), "white")
            IPickCore.match_imgs(data, "http://localhost:32742")

    # Both target and anchor must have been resolved!
    assert "/api/resource/file/download?fileId=target123" in calls
    assert "/api/resource/file/download?fileId=anchor456" in calls
