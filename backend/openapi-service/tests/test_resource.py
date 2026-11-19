import io
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.main import app
from app.services.storage import LocalStorageDriver, StoragePort, set_storage


@pytest.fixture
def mock_storage(tmp_path):
    driver = LocalStorageDriver(base_dir=str(tmp_path))
    set_storage(driver)
    return driver


@pytest.mark.asyncio
async def test_upload_and_download_file(mock_storage):
    mock_db = AsyncMock()
    saved_records = {}

    def fake_add(record):
        saved_records[record.file_id] = record

    mock_db.add = MagicMock(side_effect=fake_add)
    mock_db.commit = AsyncMock()

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            file_content = b"hello openapi resource storage test"
            files = {"file": ("test_doc.txt", io.BytesIO(file_content), "text/plain")}
            response = await client.post("/file/upload", files=files)

            assert response.status_code == 200
            data = response.json()
            assert data["code"] == "000000"
            file_id = data["data"]
            assert file_id in saved_records
            # 校验契约：纯数字且在 BIGINT 范围内，路径在 VARCHAR(100) 以内且不包含文件名
            assert file_id.isdigit()
            assert 0 < int(file_id) < 2**63 - 1
            saved_record = saved_records[file_id]
            assert saved_record.path.startswith("rpa/")
            assert saved_record.path.endswith(f"{file_id}.txt")
            assert "test_doc.txt" not in saved_record.path
            assert len(saved_record.path) <= 100
            assert saved_record.file_name == "test_doc.txt"

            mock_result = MagicMock()
            mock_result.scalars.return_value.first.return_value = saved_records[file_id]
            mock_db.execute = AsyncMock(return_value=mock_result)

            dl_response = await client.get(f"/file/download?fileId={file_id}")
            assert dl_response.status_code == 200
            assert dl_response.content == file_content
            assert "attachment" in dl_response.headers.get("content-disposition", "")
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_upload_video_validation(mock_storage):
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            files = {"file": ("malicious.exe", io.BytesIO(b"fake binary"), "application/octet-stream")}
            resp = await client.post("/file/upload-video", files=files)
            assert resp.status_code == 200
            data = resp.json()
            assert data["code"] == "900001"
            assert "视频文件格式不支持" in data["message"]

            valid_files = {"file": ("demo.mp4", io.BytesIO(b"\x00\x00\x00\x18ftypmp42"), "video/mp4")}
            valid_resp = await client.post("/file/upload-video", files=valid_files)
            assert valid_resp.status_code == 200
            valid_data = valid_resp.json()
            assert valid_data["code"] == "000000"
            assert valid_data["data"] is not None
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_share_file_types(mock_storage):
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Word (.docx) -> type 2
            resp = await client.post(
                "/file/share-file-upload",
                files={"file": ("guide.docx", io.BytesIO(b"word"), "application/vnd.openxmlformats")},
            )
            data = resp.json()["data"]
            assert data["type"] == 2
            assert data["fileId"].isdigit()
            assert 0 < int(data["fileId"]) < 2**63 - 1

            # PDF (.pdf) -> type 3
            resp = await client.post(
                "/file/share-file-upload",
                files={"file": ("manual.pdf", io.BytesIO(b"pdf"), "application/pdf")},
            )
            data = resp.json()["data"]
            assert data["type"] == 3
            assert data["fileName"] == "manual.pdf"
            assert data["filename"] == "manual.pdf"

            # Text (.txt) -> type 1
            resp = await client.post(
                "/file/share-file-upload",
                files={"file": ("notes.txt", io.BytesIO(b"txt"), "text/plain")},
            )
            assert resp.json()["data"]["type"] == 1

            # Other (.json) -> type 0
            resp = await client.post(
                "/file/share-file-upload",
                files={"file": ("config.json", io.BytesIO(b"json"), "application/json")},
            )
            assert resp.json()["data"]["type"] == 0
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_upload_file_size_limit(mock_storage, monkeypatch):
    from app.routers import resource

    # Temporarily lower limit to 100 bytes for fast testing
    monkeypatch.setattr(resource, "MAX_NORMAL_FILE_SIZE", 100)

    mock_db = AsyncMock()

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            large_content = b"a" * 150
            resp = await client.post(
                "/file/upload",
                files={"file": ("large.txt", io.BytesIO(large_content), "text/plain")},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["code"] == "900001"
            assert "超过" in data["message"]
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_storage_fallback_migration(tmp_path):
    """Test that LocalStorageDriver falls back to legacy storage and caches locally on first read."""
    mock_legacy_s3 = AsyncMock(spec=StoragePort)
    legacy_file_path = "rpa/2024-05-15/legacy_icon.png"
    legacy_bytes = b"fake legacy minio icon image"
    mock_legacy_s3.read.return_value = legacy_bytes

    driver = LocalStorageDriver(base_dir=str(tmp_path), fallback_driver=mock_legacy_s3)
    set_storage(driver)

    # 1. Local file does not exist initially
    local_file = tmp_path / legacy_file_path
    assert not local_file.exists()

    # 2. Read should invoke fallback
    data = await driver.read(legacy_file_path)
    assert data == legacy_bytes
    mock_legacy_s3.read.assert_awaited_once_with(legacy_file_path)

    # 3. File is now cached locally
    assert local_file.exists()
    assert local_file.read_bytes() == legacy_bytes

    # 4. Subsequent read does NOT call fallback
    mock_legacy_s3.read.reset_mock()
    cached_data = await driver.read(legacy_file_path)
    assert cached_data == legacy_bytes
    mock_legacy_s3.read.assert_not_awaited()


@pytest.mark.asyncio
async def test_download_file_not_found(mock_storage):
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/file/download?fileId=non_existent_id")
            assert resp.status_code == 404
            data = resp.json()
            assert data["code"] == "900003"
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_download_file_aliases_and_disposition(mock_storage):
    mock_db = AsyncMock()
    file_content = b"\x89PNG\r\n\x1a\nfake png data"
    file_path = "rpa/2026-03-31/123456.png"
    await mock_storage.save(file_path, file_content)

    fake_file = MagicMock()
    fake_file.file_id = "123456"
    fake_file.file_name = "test_image.png"
    fake_file.path = file_path
    fake_file.deleted = 0

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = fake_file
    mock_db.execute = AsyncMock(return_value=mock_result)

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Test snake_case alias file_id
            resp = await client.get("/file/download?file_id=123456")
            assert resp.status_code == 200
            assert resp.content == file_content
            assert resp.headers["content-type"].startswith("image/png")
            assert "attachment" in resp.headers["content-disposition"]

            # 2. Test disposition=inline
            resp_inline = await client.get("/file/download?fileId=123456&disposition=inline")
            assert resp_inline.status_code == 200
            assert resp_inline.content == file_content
            assert "inline" in resp_inline.headers["content-disposition"]
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_storage_path_traversal_guard(tmp_path):
    driver = LocalStorageDriver(base_dir=str(tmp_path))

    # Path traversal attempt
    with pytest.raises(ValueError, match="Path traversal"):
        await driver.save("../../../etc/passwd", b"bad data")

    with pytest.raises(ValueError, match="Path traversal"):
        await driver.read("..\\..\\secret.txt")

    assert not await driver.exists("../outside.txt")
