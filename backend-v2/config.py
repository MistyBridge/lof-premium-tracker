"""
配置管理 — Pydantic Settings
从 .env 文件和环境变量读取，必填项缺失时阻止启动。
"""
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """集中配置，Pydantic v2 自动校验类型和必填项。"""

    # === 应用 ===
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False

    # === 数据库 ===
    DATABASE_URL: str  # 必填，格式: postgresql+asyncpg://user:pass@host:5432/dbname
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5
    DB_POOL_RECYCLE: int = 3600

    # === Redis ===
    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    REDIS_MAX_CONNECTIONS: int = 20

    # === 采集参数 ===
    REFRESH_INTERVAL_SEC: int = 300
    FEE_TTL_SEC: int = 86400
    FUNDINFO_BATCH_SIZE: int = 300
    FUNDINFO_BATCH_DELAY_SEC: float = 2.0

    # === 告警 ===
    ALERT_WEBHOOK_URL: Optional[str] = None
    ALERT_THRESHOLD: int = 3

    # === 鉴权 ===
    SUPABASE_JWT_SECRET: str  # 必填
    ADMIN_EMAILS: str = ""

    # === CORS ===
    CORS_ORIGINS: str = "https://jinkuaicha.com"
    CORS_ALLOW_METHODS: str = "GET,POST,PUT,DELETE,OPTIONS"
    CORS_ALLOW_HEADERS: str = "Authorization,Content-Type"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# 模块级单例（lifespan 中也会设置）
try:
    settings = Settings()
except Exception:
    settings = None