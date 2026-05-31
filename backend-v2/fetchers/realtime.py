"""
实时行情采集 — push2 主源 + 腾讯 qt 备源
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

# ── push2 配置 ────────────────────────────────────────────────
PUSH2_URL = "https://push2.eastmoney.com/api/qt/clist/get"
PUSH2_FIELDS = "f2,f3,f5,f6,f8,f10,f12,f13,f14,f15,f16,f18,f20,f21,f37,f38,f204"
PUSH2_PARAMS = {
    "pn": 1,
    "pz": 2000,
    "po": 1,
    "np": 1,
    "fltt": 2,
    "invt": 2,
    "fid": "f3",
    "fs": "b:MK0021,b:MK0022,b:MK0023,b:MK0024",  # 沪深LOF+ETF
    "fields": PUSH2_FIELDS,
}

# ── 腾讯 qt 备源 ──────────────────────────────────────────────
TENCENT_QT_URL = "https://qt.gtimg.cn/q="
TENCENT_BATCH_SIZE = 50

# ── 字段码抽查 ────────────────────────────────────────────────
SPOT_CHECK_COUNT = 5
SPOT_CHECK_DEVIATION = 0.20  # 20% 偏差阈值
SPOT_CHECK_MIN_PASS = 3      # 至少3只通过

# 全局: 记录上次采集数据量
_last_fetch_count: int = 0


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    reraise=True,
)
async def _fetch_push2(client: httpx.AsyncClient) -> dict:
    """push2 请求 (带 tenacity 重试)"""
    headers = {"Referer": "https://quote.eastmoney.com/"}
    resp = await client.get(PUSH2_URL, params=PUSH2_PARAMS, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


async def fetch_realtime(client: httpx.AsyncClient) -> list[dict]:
    """
    获取实时行情数据

    主源: push2 clist (单次批量)
    备源: 腾讯 qt (仅深市)

    Returns:
        原始数据列表 (保留 push2 字段名), 失败返回空列表
    """
    global _last_fetch_count
    start = time.monotonic()

    # ── 主源 push2 ──
    data = await _fetch_push2_realtime(client)
    if data:
        # 字段码抽查
        if not _spot_check_fields(data[:SPOT_CHECK_COUNT]):
            logger.error("[REALTIME] push2 字段码抽查失败, 可能字段映射变更")
            metrics.record_fetch("realtime_push2", False, 0, business_error=True)
            return []

        # 部分数据防护
        if _last_fetch_count > 0 and len(data) < _last_fetch_count * PARTIAL_DATA_THRESHOLD / 100:
            logger.warning(
                "[REALTIME] 数据量不足: %d < 80%% of %d, 保留旧数据",
                len(data), _last_fetch_count,
            )
            metrics.record_fetch("realtime_push2", False, 0, business_error=True)
            return []

        _last_fetch_count = len(data)
        elapsed = time.monotonic() - start
        metrics.record_fetch("realtime_push2", True, elapsed * 1000)

        await publish_event("realtime", {
            "data": data,
            "fetch_source": "push2",
            "count": len(data),
        })
        logger.info("[REALTIME] push2 成功: %d 条, %.1fs", len(data), elapsed)
        return data

    # ── 备源 腾讯 qt ──
    logger.warning("[REALTIME] push2 失败, 降级到腾讯 qt")
    data = await _fetch_tencent_realtime(client)
    if data:
        _last_fetch_count = len(data)
        elapsed = time.monotonic() - start
        metrics.record_fetch("realtime_tencent", True, elapsed * 1000)

        await publish_event("realtime", {
            "data": data,
            "fetch_source": "tencent",
            "count": len(data),
        })
        logger.info("[REALTIME] 腾讯备源成功: %d 条, %.1fs", len(data), elapsed)
        return data

    # 全部失败
    elapsed = time.monotonic() - start
    metrics.record_fetch("realtime", False, elapsed * 1000)
    logger.error("[REALTIME] 所有数据源失败")
    return []


async def _fetch_push2_realtime(client: httpx.AsyncClient) -> list[dict]:
    """从 push2 获取实时行情"""
    try:
        result = await _fetch_push2(client)
    except Exception as e:
        logger.error("[REALTIME] push2 请求失败: %s", e)
        return []

    if result.get("rc") != 0:
        logger.warning("[REALTIME] push2 业务错误: rc=%s", result.get("rc"))
        metrics.record_fetch("realtime_push2", False, 0, business_error=True)
        return []

    diff = result.get("data", {}).get("diff", [])
    if not diff:
        return []

    items = []
    for row in diff:
        if not isinstance(row, dict):
            continue
        row["fetch_source"] = "push2"
        row["code"] = clean_code(row.get("f12", ""))
        items.append(row)

    return items


async def _fetch_tencent_realtime(client: httpx.AsyncClient) -> list[dict]:
    """腾讯 qt 备源 (仅深市)"""
    codes = _load_sz_codes()
    if not codes:
        logger.warning("[REALTIME] 无深市代码列表, 腾讯备源跳过")
        return []

    all_items: list[dict] = []
    batches = [codes[i:i + TENCENT_BATCH_SIZE] for i in range(0, len(codes), TENCENT_BATCH_SIZE)]

    for idx, batch in enumerate(batches):
        codes_str = ",".join(f"sz{c}" for c in batch)
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
            # v_sz160644="..."
            code_raw = var_part.split("_")[-1]
            code = clean_code(code_raw[2:] if len(code_raw) > 2 else code_raw)

            fields = val_part.strip('"').split("~")
            if len(fields) < 10:
                continue

            items.append({
                "code": code,
                "f12": code,                      # 代码
                "f14": fields[1],                 # 名称
                "f2": safe_float(fields[3]),      # 最新价
                "f3": safe_float(fields[32]),     # 涨跌幅
                "f5": safe_float(fields[6]),      # 成交量
                "f6": safe_float(fields[37]),     # 成交额
                "f13": 0,                         # 市场 0=深市
                "fetch_source": "tencent",
            })
        except Exception:
            continue
    return items


def _spot_check_fields(sample: list[dict]) -> bool:
    """字段码抽查: 验证 f2(价格) vs f18(昨收) 偏差"""
    if len(sample) < SPOT_CHECK_COUNT:
        return True

    passed = 0
    for row in sample:
        price = safe_float(row.get("f2"))
        prev = safe_float(row.get("f18"))
        if price is None or prev is None or price <= 0 or prev <= 0:
            continue
        if abs(price - prev) / prev < SPOT_CHECK_DEVIATION:
            passed += 1

    return passed >= SPOT_CHECK_MIN_PASS


def _load_sz_codes() -> list[str]:
    """加载深市 LOF 代码列表"""
    try:
        import json
        with open("sz_lof_codes.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            return [clean_code(c) for c in data.get("codes", [])]
    except Exception:
        return []
