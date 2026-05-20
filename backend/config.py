# -*- coding: utf-8 -*-
"""
配置文件
"""
import os
from dotenv import load_dotenv
from urllib.parse import urlparse

# 加载 .env 文件（如果存在）
# 本地开发：读取 .env 中的变量
# Railway/生产环境：.env 不存在时，load_dotenv 不会报错，继续使用系统环境变量
load_dotenv()


def _parse_db_url(url: str) -> dict:
    """Parse DATABASE_URL into connection parameters."""
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "dbname": parsed.path.lstrip("/") or "lof_funds",
        "user": parsed.username or "postgres",
        "password": parsed.password or "",
    }


class Config:
    """应用配置"""

    # Flask
    # Railway 兼容
    HOST       = os.getenv("HOST", "0.0.0.0")
    PORT       = int(os.getenv("PORT", os.getenv("RAILWAY_PORT", 5000)))
    DEBUG      = os.getenv("DEBUG", "false").lower() == "true"

    # 数据刷新间隔（秒），默认 5 分钟
    REFRESH_INTERVAL_SECONDS = int(os.getenv("REFRESH_INTERVAL", 300))

    # ── PostgreSQL 数据库配置 ──
    # 优先使用 DATABASE_URL（Railway 自动注入），其次使用独立环境变量
    _db_params = _parse_db_url(os.getenv("DATABASE_URL", "")) if os.getenv("DATABASE_URL") else {}
    DB_HOST     = os.getenv("DB_HOST",     _db_params.get("host", "localhost"))
    DB_PORT     = int(os.getenv("DB_PORT", _db_params.get("port", 5432)))
    DB_NAME     = os.getenv("DB_NAME",     _db_params.get("dbname", "lof_funds"))
    DB_USER     = os.getenv("DB_USER",     _db_params.get("user", "postgres"))
    DB_PASSWORD = os.getenv("DB_PASSWORD", _db_params.get("password", ""))
    # 连接池配置
    DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", 2))
    DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", 10))

    # 天天基金网净值/估算净值 API（免费公开，无需Key）
    FUND_NAV_URL = "https://fundgz.1234567.com.cn/js/{code}.js"

    # 东方财富 push2 场内基金行情 API
    # m:0+t:9 = 深交所场内基金, m:1+t:9 = 上交所场内基金
    # 包含 LOF + ETF（需在代码层按代码前缀过滤出真正的LOF）

    # 请求超时（秒）
    REQUEST_TIMEOUT = 30

    # 日志
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
