"""
实时行情采集 — 腾讯 qt 主源（push2已封禁IP）
"""
import logging
import time
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import settings
from constants import PARTIAL_DATA_THRESHOLD
from mq import publish_event
from metrics import metrics
from . import clean_code, safe_float

logger = logging.getLogger("app")

# ── 腾讯 qt 主源 ──────────────────────────────────────────────
TENCENT_QT_URL = "https://qt.gtimg.cn/q="
TENCENT_BATCH_SIZE = 50

# 全局: 记录上次采集数据量
_last_fetch_count: int = 0


async def fetch_realtime(client: httpx.AsyncClient) -> list[dict]:
    """
    获取实时行情数据

    主源: 腾讯 qt (push2已封禁IP)

    Returns:
        原始数据列表, 失败返回空列表
    """
    global _last_fetch_count
    start = time.monotonic()

    # ── 主源 腾讯 qt ──
    data = await _fetch_tencent_realtime(client)
    if data:
        # 部分数据防护
        if _last_fetch_count > 0 and len(data) < _last_fetch_count * PARTIAL_DATA_THRESHOLD / 100:
            logger.warning(
                "[REALTIME] 数据量不足: %d < 80%% of %d, 保留旧数据",
                len(data), _last_fetch_count,
            )
            metrics.record_fetch("realtime_tencent", False, 0, business_error=True)
            return []

        _last_fetch_count = len(data)
        elapsed = time.monotonic() - start
        metrics.record_fetch("realtime_tencent", True, elapsed * 1000)

        await publish_event("realtime", {
            "data": data,
            "fetch_source": "tencent",
            "count": len(data),
        })
        logger.info("[REALTIME] 腾讯成功: %d 条, %.1fs", len(data), elapsed)
        return data

    # 全部失败
    elapsed = time.monotonic() - start
    metrics.record_fetch("realtime", False, elapsed * 1000)
    logger.error("[REALTIME] 所有数据源失败")
    return []


async def _fetch_tencent_realtime(client: httpx.AsyncClient) -> list[dict]:
    """腾讯 qt 主源 (沪深全部)"""
    funds = _load_fund_codes()
    if not funds:
        logger.warning("[REALTIME] 无基金代码列表, 腾讯源跳过")
        return []

    all_items: list[dict] = []
    batches = [funds[i:i + TENCENT_BATCH_SIZE] for i in range(0, len(funds), TENCENT_BATCH_SIZE)]

    for idx, batch in enumerate(batches):
        codes_str = ",".join(f"{'sz' if f['market'] == 'SZ' else 'sh'}{f['code']}" for f in batch)
        try:
            resp = await client.get(f"{TENCENT_QT_URL}{codes_str}", timeout=10)
            resp.raise_for_status()
            items = _parse_tencent_text(resp.text)
            all_items.extend(items)
        except Exception as e:
            logger.warning("[REALTIME] 腾讯批次 %d 失败: %s", idx, e)

    return all_items


def _parse_tencent_text(text: str) -> list[dict]:
    """解析腾讯 qt 文本响应"""
    items = []
    for line in text.strip().split("\n"):
        if "=" not in line:
            continue
        try:
            var_part, val_part = line.split("=", 1)
            # v_sz160644="..." 或 v_sh502000="..."
            code_raw = var_part.split("_")[-1]
            market_prefix = code_raw[:2].lower() if len(code_raw) > 2 else ""
            code = clean_code(code_raw[2:] if len(code_raw) > 2 else code_raw)
            # 市场判断: sh=沪市, sz=深市
            market = "SH" if market_prefix == "sh" else "SZ"

            fields = val_part.strip('"').split("~")
            if len(fields) < 10:
                continue

            items.append({
                "code": code,
                "name": fields[1],                 # 名称
                "price": safe_float(fields[3]),     # 最新价
                "change_pct": safe_float(fields[32]),  # 涨跌幅
                "volume": safe_float(fields[6]),    # 成交量
                "amount": safe_float(fields[37]) * 10000,   # 成交额（万元→元）
                "prev_close": safe_float(fields[4]),  # 昨收
                "market": market,                    # 市场 SH/SZ
                "fetch_source": "tencent",
            })
        except Exception:
            continue
    return items


def _load_fund_codes() -> list[dict]:
    """加载沪深 LOF/ETF 代码列表"""
    try:
        import json
        with open("all_lof_codes.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            return [{"code": clean_code(d["code"]), "market": d.get("market", "SZ")} for d in data]
    except Exception:
        return []
