from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "RPA OpenAPI"
    API_VERSION: str = "1.0"
    DATABASE_URL: str = "mysql+aiomysql://root:rpa123456@localhost:3306/rpa"
    DATABASE_USERNAME: str = "root"
    DATABASE_PASSWORD: str = "rpa123456"
    REDIS_URL: str = "redis://localhost:6379/0"

    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"
    STORAGE_DRIVER: str = "local"  # "local" or "s3"
    STORAGE_LOCAL_DIR: str = "data/storage"

    # URL credentials are disabled by default because query strings commonly
    # appear in browser history and proxy access logs.
    MCP_ALLOW_QUERY_API_KEY: bool = False
    # Browser origins are denied unless a deployer explicitly allows them.
    MCP_ALLOWED_ORIGINS: str = ""
    # Trusted deployment file; never supplied by an external caller. Empty keeps
    # historical callers available, but provides no community-node admission.
    INTEGRATION_POLICY_FILE: str = ""

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
