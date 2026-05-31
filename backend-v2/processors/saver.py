"""
saver — 批量 UPSERT + 分批事务 + 物化视图刷新
每批 100 条独立事务，单批失败不影响其他批次。
"""
import asyncio
import json
import logging
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from models import FundDaily, FundFee, FundHoldings, FundInfo

logger = logging.getLogger("consumer")

BATCH_SIZE = 100


async def batch_upsert(
    session_factory,
    model,
    records: list[dict],
    conflict_columns: list[str],
    batch_size: int = BATCH_SIZE,
) -> dict:
    """
    通用批量 UPSERT（ON CONFLICT DO UPDATE）。
    返回 {"total": N, "success": N, "failed_batches": [...]}
    """
    total = len(records)
    success = 0
    failed_batches: list[dict] = []

    for i in range(0, total, batch_size):
        batch = records[i: i + batch_size]
        batch_num = i // batch_size

        try:
            async with session_factory() as session:
                async with session.begin():
                    stmt = pg_insert(model).values(batch)
                    update_cols = {
                        c.name: stmt.excluded[c.name]
                        for c in model.__table__.columns
                        if c.name not in conflict_columns
                    }
                    stmt = stmt.on_conflict_do_update(
                        index_elements=conflict_columns,
                        set_=update_cols,
                    )
                    await session.execute(stmt)

            success += len(batch)
            logger.debug("batch %d: %d rows saved", batch_num, len(batch))

        except Exception as e:
            failed_batches.append({
                "batch_num": batch_num,
                "start": i,
                "count": len(batch),
                "error": str(e),
            })
            logger.error("batch %d failed: %s", batch_num, e)

        if i + batch_size < total:
            await asyncio.sleep(0.1)

    return {"total": total, "success": success, "failed_batches": failed_batches}


# ── 便捷函数 ────────────────────────────────────────────────


async def save_daily_batch(session_factory, records: list[dict]) -> dict:
    """写 fund_daily"""
    return await batch_upsert(session_factory, FundDaily, records, ["code", "trade_date"])


async def save_info_batch(session_factory, records: list[dict]) -> dict:
    """写 fund_info"""
    return await batch_upsert(session_factory, FundInfo, records, ["code"])


async def save_fee_batch(session_factory, records: list[dict]) -> dict:
    """写 fund_fee"""
    return await batch_upsert(session_factory, FundFee, records, ["code"])


async def save_holdings_batch(session_factory, records: list[dict]) -> dict:
    """写 fund_holdings"""
    return await batch_upsert(session_factory, FundHoldings, records, ["code"])


# ── 物化视图刷新 ────────────────────────────────────────────


async def refresh_materialized_view(session_factory) -> None:
    """CONCURRENTLY 模式不锁读"""
    try:
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("REFRESH MATERIALIZED VIEW CONCURRENTLY fund_snapshot")
                )
        logger.info("物化视图 fund_snapshot 刷新完成")
    except Exception:
        logger.error("物化视图刷新失败", exc_info=True)


# ── 分区检查 ────────────────────────────────────────────────


async def ensure_partition(session_factory, target_date: date) -> None:
    """确保 asset_daily 目标月份分区存在"""
    partition_name = f"asset_daily_{target_date.strftime('%Y%m')}"
    start = target_date.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1)

    try:
        async with session_factory() as session:
            async with session.begin():
                exists = await session.execute(
                    text("SELECT 1 FROM pg_tables WHERE tablename = :name"),
                    {"name": partition_name},
                )
                if not exists.first():
                    await session.execute(text(
                        f"CREATE TABLE IF NOT EXISTS {partition_name} "
                        f"PARTITION OF asset_daily "
                        f"FOR VALUES FROM ('{start}') TO ('{end}')"
                    ))
                    logger.info("分区创建: %s", partition_name)
    except Exception:
        logger.error("分区检查失败: %s", partition_name, exc_info=True)


# ── 进度记录 ────────────────────────────────────────────────


async def save_progress(session_factory, task_name: str, result: dict) -> None:
    """记录执行进度到 fetch_progress"""
    failed_codes = [str(b.get("error", "")) for b in result.get("failed_batches", [])]

    try:
        async with session_factory() as session:
            async with session.begin():
                await session.execute(text("""
                    INSERT INTO fetch_progress (task_name, total, completed, failed_codes, updated_at)
                    VALUES (:name, :total, :completed, :failed::jsonb, NOW())
                    ON CONFLICT (task_name) DO UPDATE SET
                        total = EXCLUDED.total,
                        completed = EXCLUDED.completed,
                        failed_codes = EXCLUDED.failed_codes,
                        updated_at = NOW()
                """), {
                    "name": task_name,
                    "total": result["total"],
                    "completed": result["success"],
                    "failed": json.dumps(failed_codes),
                })
    except Exception:
        logger.error("进度记录失败: %s", task_name, exc_info=True)


async def save_job_log(
    session_factory,
    job_name: str,
    result: dict,
    batch_id: str,
) -> None:
    """记录 job 执行日志"""
    status = "success" if not result.get("failed_batches") else "failed"
    detail = json.dumps(result, ensure_ascii=False, default=str)

    try:
        async with session_factory() as session:
            async with session.begin():
                await session.execute(text("""
                    INSERT INTO job_log (job_name, status, detail, started_at, finished_at)
                    VALUES (:name, :status, :detail::text, NOW(), NOW())
                """), {
                    "name": job_name,
                    "status": status,
                    "detail": detail,
                })
    except Exception:
        logger.error("job_log 写入失败", exc_info=True)
