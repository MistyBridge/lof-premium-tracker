"""
日线K线采集 — 腾讯 K线主源 + AkShare 兜底

2026-06-30:
  - push2his 已封禁 (rc=102)，切换为腾讯 K线主源
  - 腾讯/AkShare 全并发模式，Semaphore 控流
  - 日终只取 10 天，大幅减少请求量
  - per-fund 超时保护 + 分批进度日志
"""
import asyncio
import logging
import time
from typing import Any

import httpx

from constants import LSJZ_CONCURRENCY
from mq import publish_event
from metrics import metrics
from . import clean_code, safe_float

logger = logging.getLogger("app")

# ── 腾讯 K线 配置（主源）─────────────────────────────────────
TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

# ── 日终任务参数 ──────────────────────────────────────────────
DAILY_KLINE_DAYS = 10        # 日终只取最近 10 天
KLINE_TIMEOUT_PER_FUND = 20  # 单只基金超时（秒）
KLINE_PROGRESS_EVERY = 200   # 每 N 只输出进度
KLINE_MAX_RUNTIME = 600      # 最大运行时间（秒）
FALLBACK_CONCURRENCY = 3     # AkShare 并发数（慢源，需控制）


async def _fetch_kline_tencent(
    client: httpx.AsyncClient, code: str,
) -> list[dict] | None:
    """腾讯 K线 — 主源"""
    try:
        c = clean_code(code)
        prefix = "sz" if c.startswith(("15", "16", "17", "18")) else "sh"
        symbol = f"{prefix}{c}"
        params = {"param": f"{symbol},day,,,365,qfq"}
        resp = await client.get(TENCENT_KLINE_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0:
            return None

        stock_data = data.get("data", {}).get(symbol, {})
        klines_raw = stock_data.get("day") or stock_data.get("qfqday") or []
        if not klines_raw:
            return None

        items = []
        prev_close = None
        for row in klines_raw:
            if len(row) < 6:
                continue
            close = safe_float(row[2])
            if not close or close <= 0:
                continue
            volume = safe_float(row[5])
            # 腾讯 volume 是股数 → 估算成交额
            amount = round(close * volume, 2) if close and volume else None
            change_pct = None
            if prev_close and prev_close > 0:
                change_pct = round((close - prev_close) / prev_close * 100, 4)
            prev_close = close

            items.append({
                "trade_date": row[0],
                "open": safe_float(row[1]),
                "close": close,
                "high": safe_float(row[3]),
                "low": safe_float(row[4]),
                "volume": volume,
                "amount": amount,
                "change_pct": change_pct,
                "turnover_rate": None,
                "fetch_source": "tencent_kline",
            })
        return items if items else None
    except Exception as e:
        logger.debug("[HISTORICAL] 腾讯K线 %s 失败: %s", code, e)
        return None


async def _fetch_kline_akshare(code: str) -> list[dict] | None:
    """AkShare 兜底（同步库，to_thread 执行）"""
    try:
        import akshare as ak
        df = await asyncio.to_thread(
            ak.fund_etf_hist_em,
            symbol=code,
            period="daily",
            adjust="qfq",
        )
        if df is None or df.empty:
            return None

        items = []
        for _, row in df.iterrows():
            items.append({
                "trade_date": str(row.get("日期", "")),
                "open": safe_float(row.get("开盘")),
                "close": safe_float(row.get("收盘")),
                "high": safe_float(row.get("最高")),
                "low": safe_float(row.get("最低")),
                "volume": safe_float(row.get("成交量")),
                "amount": safe_float(row.get("成交额")),
                "change_pct": safe_float(row.get("涨跌幅")),
                "turnover_rate": safe_float(row.get("换手率")),
                "fetch_source": "akshare",
            })
        return items
    except Exception as e:
        logger.debug("[HISTORICAL] AkShare %s 失败: %s", code, e)
        return None


async def _with_timeout(coro, timeout: float):
    """包装协程，超时/异常返回 None"""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except (asyncio.TimeoutError, Exception):
        return None


async def fetch_historical(
    client: httpx.AsyncClient,
    codes: list[str],
    days: int = 365,
) -> list[dict]:
    """
    批量获取日线K线

    主源: 腾讯 K线 (并发) → 降级: AkShare (并发)

    Args:
        client: httpx.AsyncClient
        codes: 基金代码列表
        days: 取最近 N 天（日终用 10，seed 用 365）
    """
    if not codes:
        return []

    start = time.monotonic()
    total = len(codes)
    logger.info("[HISTORICAL] 开始: %d 只基金, days=%d, 主源=腾讯K线", total, days)

    results: list[dict] = []
    akshare_codes: list[str] = []
    tencent_ok = 0
    tencent_fail = 0

    # ── 第 1 级：腾讯 K线 并发 ──
    sem = asyncio.Semaphore(LSJZ_CONCURRENCY)

    async def _task_tencent(code: str) -> None:
        nonlocal tencent_ok, tencent_fail
        async with sem:
            klines = await _with_timeout(
                _fetch_kline_tencent(client, code),
                KLINE_TIMEOUT_PER_FUND,
            )
            if klines:
                klines = klines[-days:] if len(klines) > days else klines
                results.append({
                    "code": clean_code(code),
                    "klines": klines,
                    "fetch_source": "tencent_kline",
                })
                tencent_ok += 1
            else:
                tencent_fail += 1
                akshare_codes.append(code)

    # 分批执行 + 进度日志
    tasks = [_task_tencent(c) for c in codes]
    for i in range(0, len(tasks), KLINE_PROGRESS_EVERY):
        chunk = tasks[i:i + KLINE_PROGRESS_EVERY]
        await asyncio.gather(*chunk)
        elapsed = time.monotonic() - start
        logger.info(
            "[HISTORICAL] 腾讯K线 进度: %d/%d (ok=%d fail=%d) %.0fs",
            min(i + KLINE_PROGRESS_EVERY, total), total,
            tencent_ok, tencent_fail, elapsed,
        )
        if elapsed > KLINE_MAX_RUNTIME:
            logger.warning(
                "[HISTORICAL] 超时 %.0fs, 已收集 %d 只, 停止采集",
                elapsed, len(results),
            )
            break

    # ── 第 2 级：AkShare 并发降级 ──
    if akshare_codes and time.monotonic() - start < KLINE_MAX_RUNTIME:
        logger.info("[HISTORICAL] AkShare 降级: %d 只基金", len(akshare_codes))
        ak_sem = asyncio.Semaphore(FALLBACK_CONCURRENCY)
        ak_ok = 0

        async def _task_ak(code: str) -> None:
            nonlocal ak_ok
            async with ak_sem:
                klines = await _with_timeout(
                    _fetch_kline_akshare(code),
                    KLINE_TIMEOUT_PER_FUND * 3,  # AkShare 更慢
                )
                if klines:
                    klines = klines[-days:] if len(klines) > days else klines
                    results.append({
                        "code": clean_code(code),
                        "klines": klines,
                        "fetch_source": "akshare",
                    })
                    ak_ok += 1

        await asyncio.gather(*[_task_ak(c) for c in akshare_codes])
        logger.info("[HISTORICAL] AkShare 完成: ok=%d", ak_ok)

    elapsed = time.monotonic() - start
    ok = len(results) > 0
    metrics.record_fetch("historical", ok, elapsed * 1000)

    # 转换为 process_kline 期望的格式: {code: [klines]}
    kdata = {item["code"]: item["klines"] for item in results if item.get("klines")}
    if kdata:
        await publish_event("kline", {"type": "fund", "data": kdata})

    logger.info(
        "[HISTORICAL] 完成: %d/%d (tencent=%d ak=%d), %.1fs",
        len(results), total, tencent_ok,
        len(results) - tencent_ok, elapsed,
    )
    return results
