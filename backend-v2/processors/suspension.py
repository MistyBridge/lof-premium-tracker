"""
停牌判断模块 — 组合判断规则

规则（以最近交易日 fund_daily 为基准）:
1. volume > 0 → 正常交易 (trading)
2. close IS NULL 或 close <= 0 → 无交易数据 → 停牌 (suspended)
3. volume = 0 + 申购状态含"暂停" → 停牌 (suspended)
4. 连续2天 volume = 0 → 停牌 (suspended)
5. 无 fund_daily 记录 → 停牌 (suspended)

存储:
  - fund_daily.suspension_status: 每日持久化
  - Redis suspension:all: 每5分钟快照更新，供 API 实时读取
"""
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("app")


def judge_suspension(
    volume: Optional[float],
    close: Optional[float],
    prev_volume: Optional[float] = None,
    sgzt: Optional[str] = None,
) -> str:
    """
    单只基金停牌判断

    Args:
        volume: 当日成交量（手）
        close: 当日收盘价
        prev_volume: 前一日成交量
        sgzt: 申购状态

    Returns:
        'trading' / 'suspended'
    """
    # 有成交量 → 正常交易
    if volume is not None and volume > 0:
        return "trading"

    # 无收盘价 → 停牌
    if close is None or close <= 0:
        return "suspended"

    # close > 0 但 volume = 0
    if sgzt and ("暂停" in sgzt or "停止" in sgzt):
        return "suspended"
    if prev_volume is not None and prev_volume == 0:
        return "suspended"

    return "suspended"


async def batch_update_suspension(session_factory) -> dict:
    """
    批量更新停牌状态（覆盖 fund_info 中所有基金）

    流程:
    1. 读取 fund_info 全量基金列表
    2. 读取 fund_daily 最近2天数据
    3. 读取 fund_fee 申购状态
    4. 逐基金判断 → 更新 fund_daily + 写入 Redis suspension:all

    Returns:
        {"trading": N, "suspended": N}
    """
    from cache import cache_set
    from sqlalchemy import text

    stats = {"trading": 0, "suspended": 0}

    async with session_factory() as session:
        # 1. 全量基金列表
        all_funds = await session.execute(text("SELECT code FROM fund_info"))
        all_codes = {r[0] for r in all_funds.fetchall()}

        # 2. 最近2天 fund_daily
        ranked = await session.execute(text("""
            WITH ranked AS (
                SELECT code, trade_date, volume, close,
                       ROW_NUMBER() OVER (PARTITION BY code ORDER BY trade_date DESC) as rn
                FROM fund_daily
            )
            SELECT r1.code, r1.trade_date, r1.volume, r1.close,
                   r2.volume as prev_volume
            FROM ranked r1
            LEFT JOIN ranked r2 ON r1.code = r2.code AND r2.rn = 2
            WHERE r1.rn = 1
        """))
        daily_map = {}
        for r in ranked.fetchall():
            m = dict(r._mapping)
            daily_map[m["code"]] = {
                "trade_date": m["trade_date"],
                "volume": float(m["volume"]) if m["volume"] else None,
                "close": float(m["close"]) if m["close"] else None,
                "prev_volume": float(m["prev_volume"]) if m["prev_volume"] else None,
            }

        # 3. 申购状态
        fee_rows = await session.execute(text(
            "SELECT code, purchase_status FROM fund_fee"
        ))
        fee_map = {r[0]: r[1] for r in fee_rows.fetchall()}

        # 4. 逐基金判断
        suspension_map = {}
        for code in all_codes:
            d = daily_map.get(code)
            sgzt = fee_map.get(code)

            if d:
                status = judge_suspension(
                    volume=d["volume"], close=d["close"],
                    prev_volume=d["prev_volume"], sgzt=sgzt,
                )
                # 更新 fund_daily
                await session.execute(text(
                    "UPDATE fund_daily SET suspension_status = :s "
                    "WHERE code = :c AND trade_date = :d"
                ), {"s": status, "c": code, "d": d["trade_date"]})
            else:
                # 无日线数据 → 停牌
                status = "suspended"

            stats[status] += 1
            suspension_map[code] = {
                "status": status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

        await session.commit()

    # 5. 写入 Redis（每5分钟快照读取）
    await cache_set("suspension:all", suspension_map, ttl=600)

    logger.info("停牌判断完成: trading=%d, suspended=%d, 共%d只",
                stats["trading"], stats["suspended"], len(all_codes))
    return stats