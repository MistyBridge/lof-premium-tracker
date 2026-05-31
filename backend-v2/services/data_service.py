"""
日线数据查询服务 — 字段白名单 + 日期校验 + 批量查询
"""
import logging
from datetime import date, datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import text

from constants import BATCH_QUERY_CODES_MAX, DAILY_QUERY_LIMIT_MAX
from exceptions import BadRequestException

logger = logging.getLogger("app")

# 字段白名单
FUND_DAILY_FIELDS = frozenset([
    "trade_date", "open", "high", "low", "close", "volume", "amount",
    "nav", "nav_date", "premium_rate", "turnover_rate", "change_pct",
    "float_share", "total_share", "nav_type", "data_source", "fetch_batch_id",
])

ASSET_DAILY_FIELDS = frozenset([
    "trade_date", "open", "high", "low", "close", "volume", "amount",
])


def _filter_fields(requested: Optional[list[str]], whitelist: frozenset[str]) -> tuple[list[str], list[str]]:
    """过滤字段，返回 (valid_fields, ignored_fields)"""
    if not requested:
        return sorted(whitelist), []

    valid = [f for f in requested if f in whitelist]
    ignored = [f for f in requested if f not in whitelist]

    if "trade_date" not in valid:
        valid.insert(0, "trade_date")

    return valid, ignored


def _validate_dates(
    from_date: Optional[str],
    to_date: Optional[str],
) -> tuple[date, date]:
    """校验日期参数，默认最近 60 天"""
    today = datetime.now(timezone.utc).date()

    if to_date:
        to_d = date.fromisoformat(to_date)
        if to_d > today:
            to_d = today
    else:
        to_d = today

    if from_date:
        from_d = date.fromisoformat(from_date)
    else:
        from_d = to_d - timedelta(days=60)

    if from_d > to_d:
        from_d, to_d = to_d, from_d

    return from_d, to_d


async def get_fund_daily(
    session_factory,
    code: str,
    fields: Optional[list[str]] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = DAILY_QUERY_LIMIT_MAX,
) -> dict:
    """基金历史日线查询"""
    code = code.zfill(6)
    from_d, to_d = _validate_dates(from_date, to_date)
    valid_fields, ignored = _filter_fields(fields, FUND_DAILY_FIELDS)
    limit = min(max(1, limit), DAILY_QUERY_LIMIT_MAX)
    select = ", ".join(valid_fields)

    async with session_factory() as session:
        result = await session.execute(text(f"""
            SELECT {select} FROM fund_daily
            WHERE code = :code
              AND trade_date BETWEEN :from_d AND :to_d
            ORDER BY trade_date ASC
            LIMIT :limit
        """), {"code": code, "from_d": from_d, "to_d": to_d, "limit": limit})
        rows = [dict(r._mapping) for r in result.fetchall()]

    return {
        "data": rows,
        "meta": {
            "code": code,
            "from_date": from_d.isoformat(),
            "to_date": to_d.isoformat(),
            "count": len(rows),
            "ignored_fields": ignored,
        },
    }


async def get_asset_daily(
    session_factory,
    code: str,
    fields: Optional[list[str]] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = DAILY_QUERY_LIMIT_MAX,
) -> dict:
    """资产历史日线查询"""
    from_d, to_d = _validate_dates(from_date, to_date)
    valid_fields, ignored = _filter_fields(fields, ASSET_DAILY_FIELDS)
    limit = min(max(1, limit), DAILY_QUERY_LIMIT_MAX)
    select = ", ".join(valid_fields)

    async with session_factory() as session:
        result = await session.execute(text(f"""
            SELECT {select} FROM asset_daily
            WHERE code = :code
              AND trade_date BETWEEN :from_d AND :to_d
            ORDER BY trade_date ASC
            LIMIT :limit
        """), {"code": code, "from_d": from_d, "to_d": to_d, "limit": limit})
        rows = [dict(r._mapping) for r in result.fetchall()]

    return {
        "data": rows,
        "meta": {
            "code": code,
            "from_date": from_d.isoformat(),
            "to_date": to_d.isoformat(),
            "count": len(rows),
            "ignored_fields": ignored,
        },
    }


async def batch_query(
    session_factory,
    codes: list[str],
    query_type: str = "fund",
    fields: Optional[list[str]] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> dict:
    """批量查询（最多 20 只）"""
    if len(codes) > BATCH_QUERY_CODES_MAX:
        raise BadRequestException(f"批量查询上限 {BATCH_QUERY_CODES_MAX} 只")

    codes = [c.zfill(6) for c in codes]
    from_d, to_d = _validate_dates(from_date, to_date)

    if query_type == "fund":
        whitelist = FUND_DAILY_FIELDS
        table = "fund_daily"
    else:
        whitelist = ASSET_DAILY_FIELDS
        table = "asset_daily"

    valid_fields, ignored = _filter_fields(fields, whitelist)
    select = ", ".join(valid_fields)

    async with session_factory() as session:
        result = await session.execute(text(f"""
            SELECT {select} FROM {table}
            WHERE code = ANY(:codes)
              AND trade_date BETWEEN :from_d AND :to_d
            ORDER BY code, trade_date ASC
        """), {"codes": codes, "from_d": from_d, "to_d": to_d})
        rows = [dict(r._mapping) for r in result.fetchall()]

    return {
        "data": rows,
        "meta": {
            "codes": codes,
            "from_date": from_d.isoformat(),
            "to_date": to_d.isoformat(),
            "count": len(rows),
            "ignored_fields": ignored,
        },
    }
