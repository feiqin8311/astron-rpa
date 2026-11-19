from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "AI Service"
    API_VERSION: str = "1.0"
    ENABLE_BILLING: bool = False  # 开源/单机模式默认关闭积分扣费与账本校验

    DATABASE_URL: str
    DATABASE_USERNAME: str
    DATABASE_PASSWORD: str
    REDIS_URL: str

    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"

    MONTHLY_GRANT_AMOUNT: int = 100000

    AICHAT_POINTS_COST: int = 100
    OCR_GENERAL_POINTS_COST: int = 50
    JFBYM_POINTS_COST: int = 10

    AICHAT_BASE_URL: str
    AICHAT_API_KEY: str

    CUA_BASE_URL: str
    CUA_API_KEY: str

    XFYUN_APP_ID: str
    XFYUN_API_SECRET: str
    XFYUN_API_KEY: str

    JFBYM_ENDPOINT: str = "http://api.jfbym.com/api/YmServer/customApi"
    JFBYM_API_TOKEN: str

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
