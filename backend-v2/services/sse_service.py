"""
SSE 增量推送服务 — 30秒心跳 + 并发限制 + 连接清理
非交易时段只发心跳，交易时段推送数据差异。
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from cache import cache_get
from constants import SSE_HEARTBEAT_INTERVAL, SSE_MAX_CONNECTIONS
from trade_calendar import is_trading_day

logger = logging.getLogger("app")

# 当前连接数
_connection_count = 0
_last_snapshot: dict[str, dict] = {}  # {code: {field: value}}


async def sse_generator(user_id: Optional[str] = None):
    """
    SSE 事件生成器（FastAPI StreamingResponse 用）。
    每次 yield 一个 SSE 事件字符串。
    """
    global _connection_count

    if _connection_count >= SSE_MAX_CONNECTIONS:
        yield _make_event("error", {"message": "连接数已满，请稍后重试"})
        return

    _connection_count += 1
    logger.info("SSE 连接建立: user=%s, 当前连接数=%d", user_id, _connection_count)

    try:
        while True:
            try:
                if is_trading_day():
                    # 交易时段：推送增量数据
                    changes = await _get_changes()
                    if changes:
                        yield _make_event("realtime", {"changes": changes})
                    else:
                        yield _make_event("heartbeat", {})
                else:
                    # 非交易时段：只发心跳
                    yield _make_event("heartbeat", {})

                await asyncio.sleep(SSE_HEARTBEAT_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("SSE 推送异常: %s", e)
                yield _make_event("error", {"message": "数据获取异常"})
                await asyncio.sleep(SSE_HEARTBEAT_INTERVAL)

    finally:
        _connection_count -= 1
        logger.info("SSE 连接断开: user=%s, 当前连接数=%d", user_id, _connection_count)


async def _get_changes() -> list[dict]:
    """对比当前和上次数据，返回变化列表"""
    global _last_snapshot

    current = await cache_get("rt:all")
    if not current:
        return []

    changes = []
    for code, data in current.items():
        prev = _last_snapshot.get(code, {})
        changed_fields = {}

        for field in ("realtime_price", "change_pct", "amount", "volume", "turnover_rate"):
            new_val = data.get(field)
            old_val = prev.get(field)
            if new_val is not None and new_val != old_val:
                changed_fields[field] = new_val

        if changed_fields:
            changes.append({"code": code, "fields": changed_fields})

    _last_snapshot = current
    return changes


def _make_event(event_type: str, data: dict) -> str:
    """格式化 SSE 事件"""
    payload = {
        "type": event_type,
        "ts": datetime.now(timezone.utc).isoformat(),
        **data,
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def get_connection_count() -> int:
    """当前 SSE 连接数"""
    return _connection_count
