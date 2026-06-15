"""系统路由"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text

from hub import get_hub
from hub.service import ServiceHub
from cache import is_redis_available, cache_get
from trade_calendar import is_trading_day, is_calendar_loaded

logger = logging.getLogger("app")

router = APIRouter(tags=["system"])


@router.get("/api/v1/health")
async def health(hub: ServiceHub = Depends(get_hub)):
    return await hub.get_health()


@router.get("/api/v1/diagnostics")
async def diagnostics(hub: ServiceHub = Depends(get_hub)):
    """
    公开诊断端点（无需管理员权限）。
    用于排查实时数据采集链路问题。
    """
    from cache import get_stream_length
    from metrics import metrics

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "calendar_loaded": is_calendar_loaded(),
        "is_trading_day": is_trading_day(),
        "redis_available": await is_redis_available(),
        "metrics": metrics.get_metrics(),
    }

    # 检查 Redis 实时数据
    from utils import beijing_now
    today = beijing_now().strftime("%Y%m%d")
    rt_close = await cache_get(f"rt:close:{today}")
    rt_all = await cache_get("rt:all")
    result["rt_close_count"] = len(rt_close) if rt_close else 0
    result["rt_all_count"] = len(rt_all) if rt_all else 0

    # 检查 fund_category 表中的代码数量
    sf = hub._sf
    try:
        async with sf() as session:
            row = await session.execute(text(
                "SELECT category, COUNT(*) FROM fund_category GROUP BY category"
            ))
            result["fund_categories"] = {r[0]: r[1] for r in row.fetchall()}
    except Exception as e:
        result["fund_categories_error"] = str(e)

    # Stream 队列状态
    result["stream_length"] = await get_stream_length()

    return {"code": 0, "data": result}
