from abc import ABC, abstractmethod
from pathlib import Path

from app.config import get_settings


class StoragePort(ABC):
    """Abstract storage port for file persistence."""

    @abstractmethod
    async def save(self, relative_path: str, data: bytes, content_type: str = "") -> str:
        """Save file bytes to relative_path. Returns relative stored path."""
        pass

    @abstractmethod
    async def read(self, relative_path: str) -> bytes:
        """Read file bytes from relative_path."""
        pass

    @abstractmethod
    async def exists(self, relative_path: str) -> bool:
        """Check if file exists."""
        pass


class LocalStorageDriver(StoragePort):
    """Local filesystem storage driver (for standalone / local-first RPA mode)."""

    def __init__(self, base_dir: str | None = None):
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            settings = get_settings()
            self.base_dir = Path(getattr(settings, "STORAGE_LOCAL_DIR", "data/storage"))
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def save(self, relative_path: str, data: bytes, content_type: str = "") -> str:
        clean_path = relative_path.lstrip("/\\")
        target_path = self.base_dir / clean_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(data)
        return clean_path

    async def read(self, relative_path: str) -> bytes:
        clean_path = relative_path.lstrip("/\\")
        target_path = self.base_dir / clean_path
        if not target_path.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")
        return target_path.read_bytes()

    async def exists(self, relative_path: str) -> bool:
        clean_path = relative_path.lstrip("/\\")
        return (self.base_dir / clean_path).exists()


_default_driver: StoragePort | None = None


def get_storage() -> StoragePort:
    global _default_driver
    if _default_driver is None:
        # Default to local storage driver; can be switched to S3 adapter
        _default_driver = LocalStorageDriver()
    return _default_driver


def set_storage(driver: StoragePort) -> None:
    global _default_driver
    _default_driver = driver
