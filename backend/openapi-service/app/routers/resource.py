# ruff: noqa: B008
import uuid
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.file import FileDB
from app.services.storage import get_storage

router = APIRouter(prefix="/file", tags=["资源与文件服务"])

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".webm", ".ogg", ".avi", ".mov", ".mpeg"}
MAX_NORMAL_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_SHARE_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
CHUNK_SIZE = 1024 * 1024  # 1 MB


def _get_file_extension(filename: str) -> str:
    if "." in filename:
        return "." + filename.rsplit(".", 1)[-1].lower()
    return ""


def _get_share_file_type(filename: str) -> int:
    """根据文件名获取文件类型，与 resource-service FileType 枚举保持一致。
    TXT=1, DOC=2, PDF=3, OTHER=0
    """
    lower = filename.lower()
    if lower.endswith((".docx", ".doc")):
        return 2
    elif lower.endswith(".pdf"):
        return 3
    elif lower.endswith(".txt"):
        return 1
    return 0


async def _read_file_with_limit(file: UploadFile, max_size: int) -> bytes:
    """分块流式读取文件并进行大小限制校验，防止内存暴涨。"""
    chunks = []
    total_size = 0
    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > max_size:
            max_mb = max_size // (1024 * 1024)
            raise ValueError(f"文件大小不能超过{max_mb}MB")
        chunks.append(chunk)
    return b"".join(chunks)


async def _save_uploaded_file(
    file: UploadFile,
    db: AsyncSession,
    max_size: int = MAX_NORMAL_FILE_SIZE,
) -> dict:
    filename = file.filename or "unknown"
    try:
        content = await _read_file_with_limit(file, max_size)
    except ValueError as e:
        return {"code": "900001", "message": str(e), "data": None}

    if not content:
        return {"code": "900001", "message": "文件不能为空", "data": None}

    file_id = str(uuid.uuid4()).replace("-", "")
    now_utc = datetime.now(UTC)
    date_prefix = now_utc.strftime("%Y-%m-%d")
    relative_path = f"rpa/{date_prefix}/{file_id}_{filename}"

    storage = get_storage()
    await storage.save(relative_path, content, content_type=file.content_type or "")

    # 写入元数据表
    file_record = FileDB(
        file_id=file_id,
        path=relative_path,
        file_name=filename,
        create_time=now_utc,
        update_time=now_utc,
        deleted=0,
    )
    db.add(file_record)
    await db.commit()

    return {"code": "000000", "message": "success", "data": file_id}


@router.get("/download")
async def download_file(
    file_id: str = Query(..., alias="fileId", description="文件唯一标识"),
    db: AsyncSession = Depends(get_db),
):
    """根据 fileId 下载文件，保持与原有 resource-service 的完整兼容"""
    stmt = select(FileDB).where(FileDB.file_id == file_id, FileDB.deleted == 0)
    result = await db.execute(stmt)
    file_record = result.scalars().first()

    if not file_record:
        return Response(
            content='{"code":"900003","message":"文件不存在","data":null}',
            status_code=404,
            media_type="application/json",
        )

    storage = get_storage()
    try:
        content = await storage.read(file_record.path)
    except FileNotFoundError:
        return Response(
            content='{"code":"900003","message":"底层文件存储丢失","data":null}',
            status_code=404,
            media_type="application/json",
        )

    filename = file_record.file_name or "download"
    encoded_filename = quote(filename.encode("utf-8"))

    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
        "Access-Control-Expose-Headers": "Content-Disposition",
    }
    return Response(content=content, media_type="application/octet-stream", headers=headers)


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传文件并保存元数据 (最大 50MB)"""
    return await _save_uploaded_file(file, db, max_size=MAX_NORMAL_FILE_SIZE)


@router.post("/upload-video")
async def upload_video_file(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传视频文件，校验后缀格式 (最大 50MB)"""
    ext = _get_file_extension(file.filename or "")
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        msg = f"视频文件格式不支持，仅支持：{', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}"
        return {"code": "900001", "message": msg, "data": None}

    return await _save_uploaded_file(file, db, max_size=MAX_NORMAL_FILE_SIZE)


@router.post("/share-file-upload")
async def share_file_upload(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传共享文件，支持最大 100MB，返回结构化元数据与准确文件类型"""
    upload_res = await _save_uploaded_file(file, db, max_size=MAX_SHARE_FILE_SIZE)
    if upload_res.get("code") != "000000":
        return upload_res

    file_id = upload_res["data"]
    file_type = _get_share_file_type(file.filename or "")
    return {
        "code": "000000",
        "message": "success",
        "data": {
            "fileId": file_id,
            "type": file_type,
            "filename": file.filename,
        },
    }
