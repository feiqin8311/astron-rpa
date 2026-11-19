# ruff: noqa: B008
import mimetypes
import secrets
import time
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

# Snowflake 纪元时间戳: 2024-01-01 00:00:00 UTC = 1704067200000 ms
EPOCH_MS = 1704067200000
_last_timestamp = -1
_sequence = 0


def generate_file_id() -> str:
    """生成与 MySQL BIGINT 及 Snowflake 算法兼容的 63 位纯正整数 ID 字符串。

    兼容 shared_file.file_id (BIGINT(20)) 与 file.file_id (VARCHAR(50))，
    避免十六进制 UUID 写入 BIGINT 字段时发生数值转换异常。
    """
    global _last_timestamp, _sequence
    now_ms = int(time.time() * 1000)
    if now_ms == _last_timestamp:
        _sequence = (_sequence + 1) & 0xFFF
        if _sequence == 0:
            time.sleep(0.001)
            now_ms = int(time.time() * 1000)
    else:
        _sequence = secrets.randbelow(32)
    _last_timestamp = now_ms

    time_part = max(0, now_ms - EPOCH_MS) & 0x1FFFFFFFFFF
    worker_part = secrets.randbelow(0x400)
    val = (time_part << 22) | (worker_part << 12) | (_sequence & 0xFFF)
    return str(val)


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

    file_id = generate_file_id()
    ext = _get_file_extension(filename)
    now_utc = datetime.now(UTC)
    date_prefix = now_utc.strftime("%Y-%m-%d")
    # 路径规范：rpa/YYYY-MM-DD/{fileId}{ext}，不包含原始文件名，严格保证长度在 file.path VARCHAR(100) 以内
    relative_path = f"rpa/{date_prefix}/{file_id}{ext}"

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
    file_id: str | None = Query(None, alias="fileId", description="文件唯一标识"),
    file_id_snake: str | None = Query(None, alias="file_id", description="文件唯一标识 (下划线别名)"),
    disposition: str = Query("attachment", description="内容处置方式: attachment 或 inline"),
    db: AsyncSession = Depends(get_db),
):
    """根据 fileId 下载文件，保持与原有 resource-service 的完整兼容"""
    target_id = file_id or file_id_snake
    if not target_id:
        return Response(
            content='{"code":"900003","message":"缺少文件标识","data":null}',
            status_code=400,
            media_type="application/json",
        )

    stmt = select(FileDB).where(FileDB.file_id == target_id, FileDB.deleted == 0)
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
    except (FileNotFoundError, ValueError):
        return Response(
            content='{"code":"900003","message":"底层文件存储丢失","data":null}',
            status_code=404,
            media_type="application/json",
        )

    filename = file_record.file_name or file_record.path.rsplit("/", 1)[-1] or "download"
    encoded_filename = quote(filename.encode("utf-8"))

    media_type, _ = mimetypes.guess_type(filename)
    media_type = media_type or "application/octet-stream"

    disp = "inline" if disposition == "inline" else "attachment"
    headers = {
        "Content-Disposition": f"{disp}; filename*=UTF-8''{encoded_filename}",
        "Access-Control-Expose-Headers": "Content-Disposition",
    }
    return Response(content=content, media_type=media_type, headers=headers)


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
            "fileName": file.filename,
        },
    }
