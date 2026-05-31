"""
日线K线采集 — push2his 主源 + AkShare 备源
"""
import asyncio
import logging
import time
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from constants import LSJZ_CONCURRENCY, FETCH_INTERVAL_MIN
from mq import publish_event
from metrics import metrics
from . import clean_code, safe_float

logger = logging.getLogger("app")

# ── push2his 配置 ─────────────────────────────────────────────
PUSH2HIS_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
PUSH2HIS_FIELDS = "f51,f52,f53,f54,f55,f56,f57,f59,f61"

# push2 备用端点
PUSH2_URL_ALT = "https://push2.eastmoney.com/api/qt/stock/kline/get"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    reraise=True,
)
async def _fetch_kline_push2his(client: httpx.AsyncClient, secid: str) -> dict | None:
    """push2his K线请求 (带重试)"""
    params = {
        "secid": secid,
        "fields2": PUSH2HIS_FIELDS,
        "klt": 101,       # 日线
        "fqt": 1,         # 前复权
        "end": "20500101", # 全部历史
        "lmt": 365,       # 最多365天
    }

    _KLINE_HEADERS = {"Referer": "https://quote.eastmoney.com/"}

    # 先尝试 push2his
    try:
        resp = await client.get(PUSH2HIS_URL, params=params, headers=_KLINE_HEADERS, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        if result.get("rc") == 0 and result.get("data", {}).get("klines"):
            return result
    except Exception as e:
        logger.debug("[HISTORICAL] push2his 失败: %s", e)

    # 降级到 push2
    try:
        resp = await client.get(PUSH2_URL_ALT, params=params, headers=_KLINE_HEADERS, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        if result.get("rc") == 0 and result.get("data", {}).get("klines"):
            return result
    except Exception as e:
        logger.debug("[HISTORICAL] push2 备用端点也失败: %s", e)

    return None


def _make_secid(code: str) -> str:
    """构建 secid: 深市 0.{code}, 沪市 1.{code}"""
    c = clean_code(code)
    if c.startswith(("15", "16", "17", "18")):
        return f"0.{c}"  # 深市
    return f"1.{c}"       # 沪市


async def _fetch_kline_tencent(client: httpx.AsyncClient, code: str) -> list[dict] | None:
    """腾讯K线备源（push2his 被封时使用）"""
    try:
        c = clean_code(code)
        prefix = "sz" if c.startswith(("15", "16", "17", "18")) else "sh"
        symbol = f"{prefix}{c}"
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        params = {"param": f"{symbol},day,,,365,qfq"}
        resp = await client.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # 腾讯返回格式: {"code":0,"data":{"sz161725":{"day":[["2025-01-02","0.59","0.58","0.60","0.57","100000"], ...]}}}
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
            # 估算成交额: close * volume（腾讯返回的volume是股数）
            amount = round(close * volume, 2) if close and volume else None
            # 计算涨跌幅
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
    """AkShare 备源 (同步库, 需 to_thread)"""
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


async def fetch_historical(client: httpx.AsyncClient, codes: list[str]) -> list[dict]:
    """
    批量获取日线K线

    主源: push2his / 备源: AkShare

    Args:
        client: httpx.AsyncClient
        codes: 基金代码列表

    Returns:
        K线数据列表 [{code, klines: [...]}, ...]
    """
    if not codes:
        return []

    start = time.monotonic()
    sem = asyncio.Semaphore(LSJZ_CONCURRENCY)
    results: list[dict] = []
    tencent_codes: list[str] = []
    akshare_codes: list[str] = []

    async def _task(code: str) -> None:
        async with sem:
            secid = _make_secid(code)
            try:
                data = await _fetch_kline_push2his(client, secid)
                if data:
                    klines_raw = data.get("data", {}).get("klines", [])
                    klines = _parse_push2his_klines(klines_raw)
                    if klines:
                        results.append({
                            "code": clean_code(code),
                            "klines": klines,
                            "fetch_source": "push2his",
                        })
                        return
            except Exception as e:
                logger.debug("[HISTORICAL] push2his %s 失败: %s", code, e)

            # 降级到腾讯K线
            tencent_codes.append(code)

    # 并发采集 push2his
    await asyncio.gather(*[_task(c) for c in codes])

    # 腾讯K线降级
    if tencent_codes:
        logger.info("[HISTORICAL] %d 只基金降级到腾讯K线", len(tencent_codes))
        for code in tencent_codes:
            klines = await _fetch_kline_tencent(client, code)
            if klines:
                results.append({
                    "code": clean_code(code),
                    "klines": klines,
                    "fetch_source": "tencent_kline",
                })
            else:
                akshare_codes.append(code)
            await asyncio.sleep(FETCH_INTERVAL_MIN)

    # AkShare 降级（最终兜底）
    if akshare_codes:
        logger.info("[HISTORICAL] %d 只基金降级到 AkShare", len(akshare_codes))
        for code in akshare_codes:
            klines = await _fetch_kline_akshare(code)
            if klines:
                results.append({
                    "code": clean_code(code),
                    "klines": klines,
                    "fetch_source": "akshare",
                })
            await asyncio.sleep(FETCH_INTERVAL_MIN)

    elapsed = time.monotonic() - start
    ok = len(results) > 0
    metrics.record_fetch("historical", ok, elapsed * 1000)

    await publish_event("kline", {
        "data": results,
        "count": len(results),
    })

    logger.info("[HISTORICAL] 完成: %d/%d 成功, %.1fs", len(results), len(codes), elapsed)
    return results


def _parse_push2his_klines(klines_raw: list[str]) -> list[dict]:
    """解析 push2his K线数据"""
    items = []
    for line in klines_raw:
        parts = line.split(",")
        if len(parts) < 9:
            continue

        close = safe_float(parts[2])
        volume = safe_float(parts[5])

        # 跳过停牌日 (close <= 0 或 volume < 0)
        if close is None or close <= 0:
            continue
        if volume is not None and volume < 0:
            continue

        items.append({
            "trade_date": parts[0],
            "open": safe_float(parts[1]),
            "close": close,
            "high": safe_float(parts[3]),
            "low": safe_float(parts[4]),
            "volume": volume,
            "amount": safe_float(parts[6]),
            "change_pct": safe_float(parts[7]),
            "turnover_rate": safe_float(parts[8]),
            "fetch_source": "push2his",
        })

    return items
