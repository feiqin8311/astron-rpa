import io
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.main import app
from app.services.storage import LocalStorageDriver, set_storage


@pytest.fixture
def mock_storage(tmp_path):
    driver = LocalStorageDriver(base_dir=str(tmp_path))
    set_storage(driver)
    return driver


@pytest.mark.asyncio
async def test_upload_and_download_file(mock_storage):
    # Mock database session
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
            # 1. Test Upload
            file_content = b"hello openapi resource storage test"
            files = {"file": ("test_doc.txt", io.BytesIO(file_content), "text/plain")}
            response = await client.post("/file/upload", files=files)

            assert response.status_code == 200
            data = response.json()
            assert data["code"] == "000000"
            file_id = data["data"]
            assert file_id in saved_records

            # 2. Test Download
            # Setup db execute scalar return
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
            # Reject invalid video extension (.exe)
            files = {"file": ("malicious.exe", io.BytesIO(b"fake binary"), "application/octet-stream")}
            resp = await client.post("/file/upload-video", files=files)
            assert resp.status_code == 200
            data = resp.json()
            assert data["code"] == "900001"
            assert "不支持的视频格式" in data["message"]

            # Accept valid video extension (.mp4)
            valid_files = {"file": ("demo.mp4", io.BytesIO(b"\x00\x00\x00\x18ftypmp42"), "video/mp4")}
            valid_resp = await client.post("/file/upload-video", files=valid_files)
            assert valid_resp.status_code == 200
            valid_data = valid_resp.json()
            assert valid_data["code"] == "000000"
            assert valid_data["data"] is not None
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_share_file_upload(mock_storage):
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            files = {"file": ("shared_workflow.json", io.BytesIO(b'{"flow": 1}'), "application/json")}
            resp = await client.post("/file/share-file-upload", files=files)
            assert resp.status_code == 200
            data = resp.json()
            assert data["code"] == "000000"
            res_data = data["data"]
            assert "fileId" in res_data
            assert res_data["filename"] == "shared_workflow.json"
            assert res_data["type"] == 1
    finally:
        app.dependency_overrides.pop(get_db, None)


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
