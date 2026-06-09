"""
Redis 缓存封装 — 全降级（Redis 不可用时不抛异常）
Key 命名规范见 constants.py
"""
import json
import logging
from typing import Any, Optional

import redis.asyncio as aioredis

from constants import PARTIAL_DATA_THRESHOLD

logger = logging.getLogger("app")

_pool: aioredis.Redis | None = None


async def init_redis(url: str, max_connections: int = 20) -> None:
    """初始化 Redis 连接池"""
    global _pool
    _pool = aioredis.from_url(
        url,
        decode_responses=True,
        max_connections=max_connections,
    )
    # 探活
    try:
        await _pool.ping()
        logger.info("Redis 连接成功: %s", url.split("@")[-1] if "@" in url else url)
    except Exception:
        logger.warning("Redis 连接失败，缓存将降级")


async def close_redis() -> None:
    """关闭连接池"""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Redis 连接已关闭")


async def is_redis_available() -> bool:
    """检查 Redis 是否可用"""
    if not _pool:
        return False
    try:
        await _pool.ping()
        return True
    except Exception:
        return False


# ── 通用缓存操作 ────────────────────────────────────────────


async def cache_get(key: str) -> Optional[Any]:
    """读缓存，Redis 不可用返回 None"""
    try:
        raw = await _pool.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def cache_set(key: str, data: Any, ttl: int) -> None:
    """写缓存，Redis 不可用静默跳过"""
    try:
        await _pool.set(key, json.dumps(data, ensure_ascii=False, default=str), ex=ttl)
    except Exception:
        pass


async def cache_delete(key: str) -> None:
    """删缓存"""
    try:
        await _pool.delete(key)
    except Exception:
        pass


async def cache_delete_pattern(pattern: str) -> None:
    """批量删除匹配的 key（用 SCAN 不阻塞）"""
    try:
        async for key in _pool.scan_iter(match=pattern, count=100):
            await _pool.delete(key)
    except Exception:
        pass


# ── 缓存击穿保护 ───────────────────────────────────────────


async def acquire_lock(key: str, ttl: int = 3) -> bool:
    """SET NX 分布式锁，获取成功返回 True"""
    try:
        return await _pool.set(key, "1", nx=True, ex=ttl)
    except Exception:
        return False  # 降级：拿不到锁，让请求穿透


async def release_lock(key: str) -> None:
    """释放锁"""
    await cache_delete(key)


# ── 部分数据防护 ───────────────────────────────────────────


async def safe_set_realtime(data: dict, threshold: float = PARTIAL_DATA_THRESHOLD / 100) -> bool:
    """
    实时行情写入前校验数据完整性。
    返回 True 表示写入成功，False 表示数据不完整被拒绝。
    """
    current_count = len(data)
    cached = await cache_get("rt:all")
    cached_count = len(cached) if cached else 0

    if cached_count > 0 and current_count < cached_count * threshold:
        logger.warning(
            "数据不完整拒绝写入: %d/%d（阈值 %.0f%%）",
            current_count, cached_count, threshold * 100,
        )
        return False

    await cache_set("rt:all", data, ttl=CACHE_RT_TTL)
    return True


async def get_redis_info() -> dict:
    """获取 Redis INFO，不可用返回空 dict"""
    try:
        if _pool:
            return await _pool.info()
    except Exception:
        pass
    return {}
