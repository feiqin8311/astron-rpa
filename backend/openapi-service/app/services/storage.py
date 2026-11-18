import io
import urllib.parse
from abc import ABC, abstractmethod
from pathlib import Path

from minio import Minio

from app.config import get_settings
from app.logger import get_logger

logger = get_logger(__name__)


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


class S3StorageDriver(StoragePort):
    """S3 / MinIO storage driver."""

    def __init__(
        self,
        endpoint_url: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        secure: bool = False,
    ):
        self.bucket = bucket
        parsed = urllib.parse.urlparse(endpoint_url)
        self.endpoint = parsed.netloc or endpoint_url
        is_secure = secure or parsed.scheme == "https"
        self.client = Minio(
            self.endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=is_secure,
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
        except Exception as e:
            logger.warning("Could not verify or create S3 bucket %s: %s", self.bucket, e)

    async def save(self, relative_path: str, data: bytes, content_type: str = "") -> str:
        clean_path = relative_path.lstrip("/\\")
        self.client.put_object(
            bucket_name=self.bucket,
            object_name=clean_path,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type or "application/octet-stream",
        )
        return clean_path

    async def read(self, relative_path: str) -> bytes:
        clean_path = relative_path.lstrip("/\\")
        try:
            response = self.client.get_object(self.bucket, clean_path)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except Exception as e:
            raise FileNotFoundError(f"Object {clean_path} not found in S3 bucket {self.bucket}: {e}") from e

    async def exists(self, relative_path: str) -> bool:
        clean_path = relative_path.lstrip("/\\")
        try:
            self.client.stat_object(self.bucket, clean_path)
            return True
        except Exception:
            return False


class LocalStorageDriver(StoragePort):
    """Local filesystem storage driver with optional fallback to legacy S3/MinIO."""

    def __init__(self, base_dir: str | None = None, fallback_driver: StoragePort | None = None):
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            settings = get_settings()
            self.base_dir = Path(getattr(settings, "STORAGE_LOCAL_DIR", "data/storage"))
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.fallback_driver = fallback_driver

    async def save(self, relative_path: str, data: bytes, content_type: str = "") -> str:
        clean_path = relative_path.lstrip("/\\")
        target_path = self.base_dir / clean_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(data)
        return clean_path

    async def read(self, relative_path: str) -> bytes:
        clean_path = relative_path.lstrip("/\\")
        target_path = self.base_dir / clean_path
        if target_path.exists():
            return target_path.read_bytes()

        # Fallback to legacy S3/MinIO if local file does not exist
        if self.fallback_driver:
            try:
                data = await self.fallback_driver.read(clean_path)
                # Cache locally so subsequent reads don't need S3 roundtrip
                try:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_bytes(data)
                except Exception as cache_err:
                    logger.warning("Failed to cache migrated S3 file locally: %s", cache_err)
                return data
            except Exception as e:
                logger.debug("Fallback storage read failed for %s: %s", clean_path, e)

        raise FileNotFoundError(f"File not found: {relative_path}")

    async def exists(self, relative_path: str) -> bool:
        clean_path = relative_path.lstrip("/\\")
        if (self.base_dir / clean_path).exists():
            return True
        if self.fallback_driver:
            return await self.fallback_driver.exists(clean_path)
        return False


_default_driver: StoragePort | None = None


def get_storage() -> StoragePort:
    global _default_driver
    if _default_driver is None:
        settings = get_settings()
        driver_type = getattr(settings, "STORAGE_DRIVER", "local").lower()

        # Build S3 driver if S3 credentials/URL are configured
        s3_driver: S3StorageDriver | None = None
        minio_url = getattr(settings, "MINIO_URL", "")
        if minio_url and getattr(settings, "MINIO_AK", "") and getattr(settings, "MINIO_SK", ""):
            try:
                s3_driver = S3StorageDriver(
                    endpoint_url=minio_url,
                    bucket=getattr(settings, "MINIO_BUCKET", "rpa-resource"),
                    access_key=settings.MINIO_AK,
                    secret_key=settings.MINIO_SK,
                )
            except Exception as e:
                logger.warning("Failed to initialize S3 storage driver: %s", e)

        if driver_type == "s3" and s3_driver is not None:
            _default_driver = s3_driver
        else:
            # Use LocalStorageDriver with optional S3 fallback for legacy files
            _default_driver = LocalStorageDriver(fallback_driver=s3_driver)
    return _default_driver


def set_storage(driver: StoragePort) -> None:
    global _default_driver
    _default_driver = driver
