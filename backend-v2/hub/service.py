"""
Hub 编排器 — 只做三件事:
1. 调一个 Service 完成完整请求
2. 跨 Service 协调
3. 缓存失效触发

不直接查 DB / 不直接读写 Redis / 不做业务计算。
所有返回值统一包装为 {code: 0, data: ..., meta: ...}
"""
import logging
from typing import Any, Optional

from cache import cache_delete, cache_delete_pattern

logger = logging.getLogger("app")


def ok(data: Any = None, meta: Any = None, message: str = "success") -> dict:
    """统一成功响应包装"""
    resp: dict[str, Any] = {"code": 0, "message": message}
    if data is not None:
        resp["data"] = data
    if meta is not None:
        resp["meta"] = meta
    return resp


class ServiceHub:
    """
    中台编排器，注入 session_factory，路由层通过 Depends 使用。
    """

    def __init__(self, session_factory):
        self._sf = session_factory

    # ── 基金 ────────────────────────────────────────────────

    async def get_fund_list(self, **kwargs):
        from services.fund_service import get_fund_list
        result = await get_fund_list(self._sf, **kwargs)
        return ok(data=result.get("data"), meta=result.get("meta"))

    async def get_fund_detail(self, code: str):
        from services.fund_service import get_fund_detail
        return ok(data=await get_fund_detail(self._sf, code))

    async def get_fund_batch(self, codes: list[str]):
        from services.fund_service import get_fund_batch
        return ok(data=await get_fund_batch(self._sf, codes))

    async def get_fund_chart(self, code: str, days: int = 30):
        from services.fund_service import get_fund_chart
        return ok(data=await get_fund_chart(self._sf, code, days))

    async def get_fund_holdings(self, code: str):
        from services.fund_service import get_fund_holdings
        return ok(data=await get_fund_holdings(self._sf, code))

    # ── 资产 ────────────────────────────────────────────────

    async def get_asset_list(self, **kwargs):
        from services.asset_service import get_asset_list
        result = await get_asset_list(self._sf, **kwargs)
        return ok(data=result.get("data"), meta=result.get("meta"))

    async def get_asset_detail(self, code: str):
        from services.asset_service import get_asset_detail
        return ok(data=await get_asset_detail(self._sf, code))

    async def get_asset_funds(self, code: str):
        from services.asset_service import get_asset_funds
        return ok(data=await get_asset_funds(self._sf, code))

    async def get_asset_chart(self, code: str, days: int = 30):
        from services.asset_service import get_asset_chart
        return ok(data=await get_asset_chart(self._sf, code, days))

    # ── 预计收益 ────────────────────────────────────────────────

    async def calc_profit(self, code: str, **kwargs):
        from services.profit_service import get_fund_profit
        return ok(data=await get_fund_profit(self._sf, code, **kwargs))

    # ── 日线数据 ────────────────────────────────────────────

    async def get_fund_daily(self, code: str, **kwargs):
        from services.data_service import get_fund_daily
        result = await get_fund_daily(self._sf, code, **kwargs)
        return ok(data=result.get("data"), meta=result.get("meta"))

    async def get_asset_daily(self, code: str, **kwargs):
        from services.data_service import get_asset_daily
        result = await get_asset_daily(self._sf, code, **kwargs)
        return ok(data=result.get("data"), meta=result.get("meta"))

    async def batch_query(self, codes: list[str], **kwargs):
        from services.data_service import batch_query
        result = await batch_query(self._sf, codes, **kwargs)
        return ok(data=result.get("data"), meta=result.get("meta"))

    # ── 公式 ────────────────────────────────────────────────

    async def list_formulas(self, user_id: str):
        from services.formula_service import list_formulas
        return ok(data=await list_formulas(self._sf, user_id))

    async def get_formula(self, user_id: str, formula_id: int):
        from services.formula_service import get_formula
        return ok(data=await get_formula(self._sf, user_id, formula_id))

    async def create_formula(self, user_id: str, data: dict):
        from services.formula_service import create_formula
        result = await create_formula(self._sf, user_id, data)
        await self._invalidate_formula_cache(user_id)
        return ok(data=result)

    async def update_formula(self, user_id: str, formula_id: int, data: dict, version: int):
        from services.formula_service import update_formula
        result = await update_formula(self._sf, user_id, formula_id, data, version)
        await self._invalidate_formula_cache(user_id)
        return ok(data=result)

    async def delete_formula(self, user_id: str, formula_id: int):
        from services.formula_service import delete_formula
        await delete_formula(self._sf, user_id, formula_id)
        await self._invalidate_formula_cache(user_id)
        return ok(message="公式已删除")

    async def validate_expression(self, expression: str):
        from services.formula_service import validate_expression
        return ok(data=await validate_expression(expression))

    # ── 公式组 ──────────────────────────────────────────────

    async def list_formula_groups(self, user_id: str):
        from services.formula_service import list_formula_groups
        return ok(data=await list_formula_groups(self._sf, user_id))

    async def create_formula_group(self, user_id: str, data: dict):
        from services.formula_service import create_formula_group
        result = await create_formula_group(self._sf, user_id, data)
        await self._invalidate_formula_cache(user_id)
        return ok(data=result)

    async def update_formula_group(self, user_id: str, group_id: int, data: dict):
        from services.formula_service import update_formula_group
        result = await update_formula_group(self._sf, user_id, group_id, data)
        await self._invalidate_formula_cache(user_id)
        return ok(data=result)

    async def delete_formula_group(self, user_id: str, group_id: int):
        from services.formula_service import delete_formula_group
        await delete_formula_group(self._sf, user_id, group_id)
        await self._invalidate_formula_cache(user_id)
        return ok(message="公式组已删除")

    # ── 预警 ────────────────────────────────────────────────

    async def list_alerts(self, user_id: str):
        from services.alert_service import list_alerts
        return ok(data=await list_alerts(self._sf, user_id))

    async def create_alert(self, user_id: str, data: dict):
        from services.alert_service import create_alert
        return ok(data=await create_alert(self._sf, user_id, data))

    async def delete_alert(self, user_id: str, alert_id: int):
        from services.alert_service import delete_alert
        await delete_alert(self._sf, user_id, alert_id)
        return ok(message="预警已删除")

    async def toggle_alert(self, user_id: str, alert_id: int, active: bool):
        from services.alert_service import toggle_alert
        return ok(data=await toggle_alert(self._sf, user_id, alert_id, active))

    # ── 系统 ────────────────────────────────────────────────

    async def get_health(self):
        from services.system_service import get_health
        return ok(data=await get_health(self._sf))

    async def get_monitor(self):
        from services.system_service import get_monitor
        return ok(data=await get_monitor())

    async def diagnose_redis(self):
        from services.system_service import diagnose_redis
        return ok(data=await diagnose_redis())

    async def diagnose_db(self):
        from services.system_service import diagnose_db
        return ok(data=await diagnose_db(self._sf))

    async def diagnose_fetcher(self):
        from services.system_service import diagnose_fetcher
        return ok(data=await diagnose_fetcher(self._sf))

    async def diagnose_fund(self, code: str):
        from services.system_service import diagnose_fund
        return ok(data=await diagnose_fund(self._sf, code))

    async def diagnose_queue(self):
        from services.system_service import diagnose_queue
        return ok(data=await diagnose_queue())

    async def ops_mv_refresh(self, user_id: str):
        from services.system_service import ops_mv_refresh
        result = await ops_mv_refresh(self._sf, user_id)
        if result.get("status") == "ok":
            await cache_delete("snapshot:fund_list")
        return ok(data=result)

    async def ops_cache_clear(self, user_id: str, pattern: str = "*"):
        from services.system_service import ops_cache_clear
        return ok(data=await ops_cache_clear(user_id, pattern))

    async def get_audit_log(self, limit: int = 50):
        from services.system_service import get_audit_log
        return ok(data=await get_audit_log(self._sf, limit))

    # ── 缓存失效 ────────────────────────────────────────────

    async def _invalidate_formula_cache(self, user_id: str) -> None:
        """清除用户的公式相关缓存"""
        await cache_delete_pattern(f"formula:{user_id}:*")
