"""
净值+申赎采集 — 天天基金 lsjz API (Semaphore并发)
"""
import asyncio
import logging
import time
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from constants import LSJZ_CONCURRENCY, LSJZ_INTERVAL
from mq import publish_event
from metrics import metrics
from . import clean_code, safe_float

logger = logging.getLogger("app")

# ── lsjz API 配置 ─────────────────────────────────────────────
LSJZ_URL = "https://api.fund.eastmoney.com/f10/lsjz"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    reraise=True,
)
async def _fetch_single_nav(client: httpx.AsyncClient, code: str) -> dict | None:
    """单只基金净值请求 (带重试)"""
    params = {
        "fundCode": code,
        "pageIndex": 1,
        "pageSize": 5,
    }
    headers = {"Referer": "https://fundf10.eastmoney.com/"}
    resp = await client.get(LSJZ_URL, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    result = resp.json()

    if result.get("ErrCode", -1) != 0:
        logger.warning("[FUNDAMENTAL] %s 业务错误: ErrCode=%s", code, result.get("ErrCode"))
        return None

    lsjz_list = result.get("Data", {}).get("LSJZList", [])
    if not lsjz_list:
        return None

    latest = lsjz_list[0]
    nav = safe_float(latest.get("DWJZ"))
    nav_date = latest.get("FSRQ", "")

    if nav is None or nav <= 0 or not nav_date:
        return None

    return {
        "code": code,
        "nav": nav,
        "nav_date": nav_date,
        "purchase_status": _parse_purchase_status(latest.get("SGZT", "")),
        "redeem_status": _parse_redeem_status(latest.get("SHZT", "")),
        "daily_return": safe_float(latest.get("RZZL")),
        "fetch_source": "lsjz",
    }


async def fetch_fundamental(client: httpx.AsyncClient, codes: list[str]) -> list[dict]:
    """
    批量获取基金净值+申赎状态

    Args:
        client: httpx.AsyncClient
        codes: 基金代码列表

    Returns:
        净值数据列表
    """
    if not codes:
        return []

    start = time.monotonic()
    sem = asyncio.Semaphore(LSJZ_CONCURRENCY)
    results: list[dict] = []
    failed: list[str] = []

    async def _task(code: str) -> None:
        async with sem:
            try:
                await asyncio.sleep(LSJZ_INTERVAL)
                data = await _fetch_single_nav(client, code)
                if data:
                    results.append(data)
                else:
                    failed.append(code)
            except Exception as e:
                logger.debug("[FUNDAMENTAL] %s 失败: %s", code, e)
                failed.append(code)

    # 第一轮并发
    await asyncio.gather(*[_task(c) for c in codes])

    # 重试失败的
    if failed:
        logger.info("[FUNDAMENTAL] 重试 %d 只失败基金", len(failed))
        retry_failed: list[str] = []
        async def _retry_task(code: str) -> None:
            async with sem:
                try:
                    await asyncio.sleep(LSJZ_INTERVAL)
                    data = await _fetch_single_nav(client, code)
                    if data:
                        results.append(data)
                    else:
                        retry_failed.append(code)
                except Exception:
                    retry_failed.append(code)

        await asyncio.gather(*[_retry_task(c) for c in failed])

    elapsed = time.monotonic() - start
    ok = len(results) > 0
    metrics.record_fetch("fundamental_lsjz", ok, elapsed * 1000, business_error=not ok and len(codes) > 0)

    await publish_event("nav", {
        "data": results,
        "fetch_source": "lsjz",
        "count": len(results),
    })

    logger.info("[FUNDAMENTAL] 完成: %d/%d 成功, %.1fs", len(results), len(codes), elapsed)
    return results


def _parse_purchase_status(raw: str) -> str:
    """解析申购状态"""
    if not raw:
        return "unknown"
    if "开放" in raw:
        return "open"
    if "暂停" in raw:
        return "suspended"
    if "限制大额" in raw:
        return "restricted"
    return "unknown"


def _parse_redeem_status(raw: str) -> str:
    """解析赎回状态"""
    if not raw:
        return "unknown"
    if "开放" in raw:
        return "open"
    if "暂停" in raw:
        return "suspended"
    return "unknown"
