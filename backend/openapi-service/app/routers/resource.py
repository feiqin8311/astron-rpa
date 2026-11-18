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


def _get_file_extension(filename: str) -> str:
    if "." in filename:
        return "." + filename.rsplit(".", 1)[-1].lower()
    return ""


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
    """上传文件并保存元数据"""
    file_id = str(uuid.uuid4()).replace("-", "")
    content = await file.read()
    now_utc = datetime.now(UTC)
    date_prefix = now_utc.strftime("%Y-%m-%d")
    relative_path = f"{date_prefix}/{file_id}_{file.filename}"

    storage = get_storage()
    await storage.save(relative_path, content, content_type=file.content_type or "")

    # 写入元数据表
    file_record = FileDB(
        file_id=file_id,
        path=relative_path,
        file_name=file.filename,
        create_time=now_utc,
        update_time=now_utc,
        deleted=0,
    )
    db.add(file_record)
    await db.commit()

    return {"code": "000000", "message": "success", "data": file_id}


@router.post("/upload-video")
async def upload_video_file(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传视频文件，校验后缀格式"""
    ext = _get_file_extension(file.filename or "")
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        msg = f"不支持的视频格式: {ext}，仅支持 {ALLOWED_VIDEO_EXTENSIONS}"
        return {"code": "900001", "message": msg, "data": None}

    return await upload_file(file=file, db=db)


@router.post("/share-file-upload")
async def share_file_upload(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传共享文件，返回结构化元数据"""
    upload_res = await upload_file(file=file, db=db)
    if upload_res.get("code") != "000000":
        return upload_res

    file_id = upload_res["data"]
    return {
        "code": "000000",
        "message": "success",
        "data": {
            "fileId": file_id,
            "type": 1,
            "filename": file.filename,
        },
    }
