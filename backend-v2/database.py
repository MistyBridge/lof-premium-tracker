"""
数据库连接 — SQLAlchemy async engine + session + 依赖注入
"""
import json
import logging
from datetime import datetime, date
from decimal import Decimal
from typing import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import Settings

logger = logging.getLogger("app")

# ── JSON 序列化兜底 ────────────────────────────────────────


def json_serializer(obj):
    """FastAPI JSONResponse 的 default 参数，处理 Decimal/datetime 等类型"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Type {type(obj)} not JSON serializable")


# ── Engine / Session 工厂（lifespan 中初始化） ──────────────

engine = None
async_session_factory = None


def init_engine(settings: Settings):
    """创建 async engine 和 session factory，在 lifespan 中调用"""
    global engine, async_session_factory

    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_pre_ping=True,
        pool_recycle=settings.DB_POOL_RECYCLE,
        echo=settings.DEBUG,
    )

    async_session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _set_statement_timeout(dbapi_conn, connection_record):
        """每个新连接设置查询超时 5 秒"""
        cursor = dbapi_conn.cursor()
        cursor.execute("SET statement_timeout = '5s'")
        cursor.close()

    logger.info(
        "数据库引擎初始化完成 (pool_size=%d, max_overflow=%d)",
        settings.DB_POOL_SIZE,
        settings.DB_MAX_OVERFLOW,
    )


async def dispose_engine():
    """关闭连接池，在 lifespan shutdown 中调用"""
    global engine, async_session_factory
    if engine:
        await engine.dispose()
        logger.info("数据库连接池已关闭")
        engine = None
        async_session_factory = None


# ── FastAPI 依赖注入 ────────────────────────────────────────


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends 注入，自动 commit/rollback"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_raw_conn():
    """获取 raw asyncpg 连接（migration / trade_calendar 用）"""
    async with engine.connect() as conn:
        yield conn