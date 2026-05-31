"""
资产查询服务 — 列表/详情/关联基金/图表
"""
import logging
from typing import Optional

from sqlalchemy import text

from constants import PAGE_SIZE_DEFAULT, PAGE_SIZE_MAX
from exceptions import NotFoundException

logger = logging.getLogger("app")


async def get_asset_list(
    session_factory,
    page: int = 1,
    size: int = PAGE_SIZE_DEFAULT,
    search: Optional[str] = None,
    asset_type: Optional[str] = None,
) -> dict:
    """资产列表（分页+搜索）"""
    page = max(1, page)
    size = min(max(1, size), PAGE_SIZE_MAX)

    conditions = []
    params: dict = {}

    if search:
        conditions.append("(code LIKE :s OR name LIKE :s)")
        params["s"] = f"%{search}%"
    if asset_type:
        conditions.append("asset_type = :at")
        params["at"] = asset_type

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    async with session_factory() as session:
        count = await session.execute(
            text(f"SELECT COUNT(*) FROM asset_master {where}"), params
        )
        total = count.scalar() or 0

        params["limit"] = size
        params["offset"] = (page - 1) * size
        result = await session.execute(text(
            f"SELECT * FROM asset_master {where} "
            f"ORDER BY code ASC LIMIT :limit OFFSET :offset"
        ), params)
        rows = [dict(r._mapping) for r in result.fetchall()]

    return {
        "data": rows,
        "meta": {
            "page": page, "size": size, "total": total,
            "total_pages": (total + size - 1) // size if total > 0 else 0,
        },
    }


async def get_asset_detail(session_factory, code: str) -> dict:
    """资产详情"""
    async with session_factory() as session:
        row = await session.execute(
            text("SELECT * FROM asset_master WHERE code = :code"),
            {"code": code},
        )
        result = row.first()

    if not result:
        raise NotFoundException(f"资产 {code} 不存在")

    return dict(result._mapping)


async def get_asset_funds(session_factory, code: str) -> list[dict]:
    """持有该资产的基金列表"""
    async with session_factory() as session:
        result = await session.execute(text("""
            SELECT fam.fund_code, fam.weight, fi.name, fi.fund_type
            FROM fund_asset_map fam
            JOIN fund_info fi ON fam.fund_code = fi.code
            WHERE fam.asset_code = :code
            ORDER BY fam.weight DESC
        """), {"code": code})
        return [dict(r._mapping) for r in result.fetchall()]


async def get_asset_chart(session_factory, code: str, days: int = 30) -> list[dict]:
    """资产价格图表"""
    days = min(max(1, days), 365)

    async with session_factory() as session:
        result = await session.execute(text("""
            SELECT trade_date, close, change_pct, volume, amount
            FROM asset_daily
            WHERE code = :code
            ORDER BY trade_date DESC
            LIMIT :days
        """), {"code": code, "days": days})
        rows = [dict(r._mapping) for r in result.fetchall()]

    return list(reversed(rows))
