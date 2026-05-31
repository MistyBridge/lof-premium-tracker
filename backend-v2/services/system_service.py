"""
系统服务 — 健康检查/监控/诊断/操作/物化视图并发锁/审计
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import psutil
from sqlalchemy import text

from cache import is_redis_available, get_redis_info
from metrics import get_disk_usage_pct, metrics

logger = logging.getLogger("app")

# 物化视图刷新锁
_mv_lock = asyncio.Lock()


# ── 健康检查 ────────────────────────────────────────────────


async def get_health(session_factory) -> dict:
    """健康检查: DB/Redis/数据新鲜度"""
    status = {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

    # DB 检查
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        status["database"] = "ok"
    except Exception:
        status["database"] = "error"
        status["status"] = "degraded"

    # Redis 检查
    status["redis"] = "ok" if await is_redis_available() else "unavailable"

    # 数据新鲜度
    try:
        async with session_factory() as session:
            row = await session.execute(text(
                "SELECT MAX(trade_date) FROM fund_daily"
            ))
            latest = row.scalar()
            status["latest_data_date"] = latest.isoformat() if latest else None
    except Exception:
        status["latest_data_date"] = None

    return status


# ── 监控 ────────────────────────────────────────────────────


async def get_monitor() -> dict:
    """监控状态: metrics 快照 + 系统资源"""
    m = metrics.get_metrics()
    process = psutil.Process()
    m["memory_mb"] = round(process.memory_info().rss / 1024 / 1024, 1)
    m["disk_usage_pct"] = round(get_disk_usage_pct(), 1)
    return m


# ── 诊断 ────────────────────────────────────────────────────


async def diagnose_redis() -> dict:
    """Redis 详细状态"""
    if not await is_redis_available():
        return {"available": False}

    try:
        info = await get_redis_info()
        return {
            "available": True,
            "version": info.get("redis_version"),
            "used_memory_mb": round(info.get("used_memory", 0) / 1024 / 1024, 1),
            "connected_clients": info.get("connected_clients"),
            "keyspace_hits": info.get("keyspace_hits"),
            "keyspace_misses": info.get("keyspace_misses"),
        }
    except Exception:
        return {"available": False, "error": "info failed"}


async def diagnose_db(session_factory) -> dict:
    """数据库概览"""
    async with session_factory() as session:
        tables = []
        for table in [
            "fund_info", "fund_daily", "fund_fee", "fund_holdings",
            "fund_code_list", "asset_master", "asset_daily", "trade_calendar",
        ]:
            try:
                row = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
                tables.append({"name": table, "rows": row.scalar()})
            except Exception:
                tables.append({"name": table, "rows": -1})
        return {"tables": tables}


async def diagnose_fetcher(session_factory) -> dict:
    """采集状态详情"""
    m = metrics.get_metrics()
    fetch = m.get("fetch_status", {})

    # 最近 job_log
    async with session_factory() as session:
        result = await session.execute(text("""
            SELECT job_name, status, duration_ms, started_at
            FROM job_log ORDER BY started_at DESC LIMIT 10
        """))
        recent = [dict(r._mapping) for r in result.fetchall()]

    return {"fetch_status": fetch, "recent_jobs": recent}


async def diagnose_fund(session_factory, code: str) -> dict:
    """单基金数据状态"""
    code = code.zfill(6)
    async with session_factory() as session:
        info = await session.execute(text(
            "SELECT * FROM fund_info WHERE code = :c"
        ), {"c": code})
        daily_count = await session.execute(text(
            "SELECT COUNT(*) FROM fund_daily WHERE code = :c"
        ), {"c": code})
        latest = await session.execute(text(
            "SELECT MAX(trade_date) FROM fund_daily WHERE code = :c"
        ), {"c": code})

    info_row = info.first()
    latest_date = latest.scalar()
    return {
        "code": code,
        "info": dict(info_row._mapping) if info_row else None,
        "daily_count": daily_count.scalar(),
        "latest_daily": latest_date.isoformat() if latest_date else None,
    }


async def diagnose_queue() -> dict:
    """Stream 队列状态"""
    try:
        from mq import get_stream_length
        length = await get_stream_length()
        return {"stream_length": length}
    except Exception:
        return {"stream_length": -1, "error": "unavailable"}


# ── 操作 ────────────────────────────────────────────────────


async def ops_mv_refresh(session_factory, user_id: str) -> dict:
    """刷新物化视图（并发锁保护，原子获取锁避免 TOCTOU 竞态）"""
    acquired = _mv_lock.acquire_nowait()
    if not acquired:
        return {"status": "busy", "message": "物化视图刷新进行中，请稍后重试"}

    try:
        async with session_factory() as session:
            async with session.begin():
                await session.execute(text(
                    "REFRESH MATERIALIZED VIEW CONCURRENTLY fund_snapshot"
                ))
        await _write_audit(session_factory, user_id, "ops_mv_refresh", None, "success")
        return {"status": "ok", "message": "物化视图刷新完成"}
    except Exception as e:
        await _write_audit(session_factory, user_id, "ops_mv_refresh", None, f"failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        _mv_lock.release()


async def ops_cache_clear(user_id: str, pattern: str = "*") -> dict:
    """清空缓存"""
    from cache import cache_delete_pattern
    await cache_delete_pattern(pattern)
    return {"status": "ok", "pattern": pattern}


# ── 审计 ────────────────────────────────────────────────────


async def get_audit_log(session_factory, limit: int = 50) -> list[dict]:
    """审计日志"""
    async with session_factory() as session:
        result = await session.execute(text(
            "SELECT * FROM admin_audit_log ORDER BY created_at DESC LIMIT :lim"
        ), {"lim": limit})
        return [dict(r._mapping) for r in result.fetchall()]


async def _write_audit(
    session_factory,
    user_id: str,
    action: str,
    target: Optional[str],
    detail: str,
) -> None:
    """写审计日志"""
    try:
        async with session_factory() as session:
            await session.execute(text("""
                INSERT INTO admin_audit_log (user_id, action, target, detail)
                VALUES (:uid, :action, :target, :detail)
            """), {
                "uid": user_id,
                "action": action,
                "target": target,
                "detail": detail,
            })
            await session.commit()
    except Exception:
        logger.error("审计日志写入失败", exc_info=True)
