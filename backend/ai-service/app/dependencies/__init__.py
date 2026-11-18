from fastapi import Depends, Header, HTTPException
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.redis_op import get_redis
from app.services.point import UserPointService


def get_user_id_from_header(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    user_id: str | None = Header(default=None, alias="user_id"),
) -> str:
    """
    从请求头中获取用户ID，优先解析 X-User-Id，如果不存在则解析 user_id。
    当未启用计费（单机/开源模式）时，默认回退为 local-user。
    """
    header_user_id = x_user_id or user_id

    if header_user_id is None:
        if not get_settings().ENABLE_BILLING:
            return "local-user"
        raise HTTPException(
            status_code=401,
            detail="Missing X-User-Id or user_id header.",
        )
    return header_user_id


def get_user_point_service(db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)) -> UserPointService:
    return UserPointService(db, redis)
