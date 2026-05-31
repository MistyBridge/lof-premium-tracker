"""
预警 CRUD + 条件触发检查
条件格式: {"op": "and", "conditions": [{"field": "premium_rate", "op": ">", "value": 5}]}
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from exceptions import BadRequestException, NotFoundException

logger = logging.getLogger("app")

COMPARE_OPS = {
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


# ── CRUD ────────────────────────────────────────────────────


async def list_alerts(session_factory, user_id: str) -> list[dict]:
    """列出用户的预警规则"""
    async with session_factory() as session:
        result = await session.execute(text(
            "SELECT * FROM user_alert WHERE user_id = :uid ORDER BY created_at DESC"
        ), {"uid": user_id})
        return [dict(r._mapping) for r in result.fetchall()]


async def create_alert(session_factory, user_id: str, data: dict) -> dict:
    """创建预警"""
    condition = data.get("condition")
    if not condition or not isinstance(condition, dict):
        raise BadRequestException("condition 必须是 JSON 对象")
    _validate_condition(condition)

    async with session_factory() as session:
        result = await session.execute(text("""
            INSERT INTO user_alert (user_id, name, fund_code, condition, is_active)
            VALUES (:uid, :name, :code, :cond::jsonb, :active) RETURNING *
        """), {
            "uid": user_id,
            "name": data.get("name", ""),
            "code": data.get("fund_code"),
            "cond": json.dumps(condition, ensure_ascii=False),
            "active": data.get("is_active", True),
        })
        await session.commit()
        return dict(result.first()._mapping)


async def delete_alert(session_factory, user_id: str, alert_id: int) -> None:
    """删除预警"""
    async with session_factory() as session:
        result = await session.execute(text(
            "DELETE FROM user_alert WHERE id = :id AND user_id = :uid RETURNING id"
        ), {"id": alert_id, "uid": user_id})
        await session.commit()
        if not result.first():
            raise NotFoundException(f"预警 {alert_id} 不存在")


async def toggle_alert(session_factory, user_id: str, alert_id: int, active: bool) -> dict:
    """启用/禁用预警"""
    async with session_factory() as session:
        result = await session.execute(text("""
            UPDATE user_alert SET is_active = :active, updated_at = NOW()
            WHERE id = :id AND user_id = :uid RETURNING *
        """), {"id": alert_id, "uid": user_id, "active": active})
        await session.commit()
        row = result.first()
        if not row:
            raise NotFoundException(f"预警 {alert_id} 不存在")
        return dict(row._mapping)


# ── 条件检查 ────────────────────────────────────────────────


async def check_alerts(session_factory, realtime_data: dict) -> list[dict]:
    """
    消费者调用：检查所有活跃预警是否触发。
    realtime_data: {code: {field: value, ...}}
    返回触发的预警列表。
    """
    async with session_factory() as session:
        result = await session.execute(text(
            "SELECT * FROM user_alert WHERE is_active = TRUE"
        ))
        alerts = [dict(r._mapping) for r in result.fetchall()]

    triggered = []
    for alert in alerts:
        fund_code = alert.get("fund_code")
        condition = alert.get("condition", {})

        # 获取对应基金数据
        if fund_code:
            fund_data = realtime_data.get(fund_code)
            if not fund_data:
                continue
            if _evaluate_condition(condition, fund_data):
                triggered.append(alert)
                await _mark_triggered(session_factory, alert["id"])
        else:
            # 全局预警：检查所有基金
            for code, data in realtime_data.items():
                if _evaluate_condition(condition, data):
                    triggered.append({**alert, "triggered_code": code})
                    await _mark_triggered(session_factory, alert["id"])
                    break

    return triggered


# ── 内部辅助 ────────────────────────────────────────────────


def _validate_condition(condition: dict) -> None:
    """校验条件格式"""
    op = condition.get("op")
    if op not in ("and", "or"):
        raise BadRequestException("condition.op 必须是 and/or")

    conds = condition.get("conditions")
    if not isinstance(conds, list) or len(conds) == 0:
        raise BadRequestException("condition.conditions 必须是非空数组")

    for c in conds:
        if c.get("op") not in COMPARE_OPS:
            raise BadRequestException(f"不支持的操作符: {c.get('op')}")
        if "field" not in c or "value" not in c:
            raise BadRequestException("条件必须包含 field 和 value")


def _evaluate_condition(condition: dict, data: dict) -> bool:
    """求值条件"""
    op = condition.get("op", "and")
    conds = condition.get("conditions", [])

    results = []
    for c in conds:
        field = c.get("field")
        cmp_op = c.get("op")
        threshold = c.get("value")
        value = data.get(field)

        if value is None:
            results.append(False)
            continue

        try:
            results.append(COMPARE_OPS[cmp_op](float(value), float(threshold)))
        except (ValueError, TypeError):
            results.append(False)

    if op == "and":
        return all(results)
    return any(results)


async def _mark_triggered(session_factory, alert_id: int) -> None:
    """标记预警触发时间"""
    try:
        async with session_factory() as session:
            await session.execute(text(
                "UPDATE user_alert SET last_triggered_at = NOW() WHERE id = :id"
            ), {"id": alert_id})
            await session.commit()
    except Exception:
        logger.error("标记预警触发失败: %d", alert_id, exc_info=True)
