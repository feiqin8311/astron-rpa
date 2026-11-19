from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Integer, String

from app.database import Base


class FileDB(Base):
    """文件元数据模型，映射原有 resource-service 的 file 数据表"""

    __tablename__ = "file"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(String(64), index=True, nullable=False)
    path = Column(String(500), nullable=False)
    file_name = Column(String(255), nullable=True)
    create_time = Column(DateTime, default=lambda: datetime.now(UTC))
    update_time = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    deleted = Column(Integer, default=0)
