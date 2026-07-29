"""
实时行情采集 — 腾讯 qt 主源（push2已封禁IP）

2026-06-15: 修复 — 代码列表加载增加数据库回退，解决生产环境
  all_lof_codes.json 路径问题导致采集静默失败的 bug。
"""
import logging
import time
from pathlib import Path
from typing import Any, Optional

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


async def fetch_realtime(
    client: httpx.AsyncClient,
    codes: Optional[list[str]] = None,
) -> list[dict]:
    """
    获取实时行情数据

    主源: 腾讯 qt (push2已封禁IP)

    Args:
        client: httpx 异步客户端
        codes: 可选的基金代码列表（scheduler 从 DB 获取后传入）。
               未传入时从 all_lof_codes.json 加载。

    Returns:
        原始数据列表, 失败返回空列表
    """
    global _last_fetch_count
    start = time.monotonic()

    # ── 主源 腾讯 qt ──
    data = await _fetch_tencent_realtime(client, codes)
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


async def _fetch_tencent_realtime(
    client: httpx.AsyncClient,
    codes: Optional[list[str]] = None,
) -> list[dict]:
    """腾讯 qt 主源 (沪深全部)"""
    # 优先使用传入的 codes（scheduler 从 DB 获取）
    if codes:
        funds = _build_fund_list(codes)
    else:
        funds = _load_fund_codes()

    if not funds:
        logger.error("[REALTIME] 无基金代码列表，采集跳过！codes参数=%s", "传入" if codes else "未传入")
        return []

    logger.info("[REALTIME] 开始腾讯采集: %d 只基金", len(funds))
    all_items: list[dict] = []
    batches = [funds[i:i + TENCENT_BATCH_SIZE] for i in range(0, len(funds), TENCENT_BATCH_SIZE)]
    failed_batches = 0

    for idx, batch in enumerate(batches):
        codes_str = ",".join(f"{'sz' if f['market'] == 'SZ' else 'sh'}{f['code']}" for f in batch)
        try:
            resp = await client.get(f"{TENCENT_QT_URL}{codes_str}", timeout=10)
            resp.raise_for_status()
            items = _parse_tencent_text(resp.text)
            all_items.extend(items)
        except Exception as e:
            failed_batches += 1
            logger.warning("[REALTIME] 腾讯批次 %d/%d 失败: %s", idx + 1, len(batches), e)

    if failed_batches > 0:
        logger.warning("[REALTIME] 腾讯采集: %d/%d 批次失败", failed_batches, len(batches))

    return all_items


def _build_fund_list(codes: list[str]) -> list[dict]:
    """从代码字符串列表构建基金列表（推断市场）"""
    result = []
    for raw in codes:
        code = clean_code(raw)
        if not code:
            continue
        # 推断市场: 5/6 开头 → 沪市, 其他 → 深市
        market = "SH" if code[0] in ("5", "6") else "SZ"
        result.append({"code": code, "market": market})
    return result


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

            price_val = safe_float(fields[3])
            volume_val = safe_float(fields[6])
            # 腾讯 qt 成交量(手) × 100 股/手 × 价格 = 成交额(元)
            realtime_amount = round(price_val * volume_val * 100, 2) if price_val and volume_val else None

            items.append({
                "code": code,
                "name": fields[1],                 # 名称
                "price": price_val,                 # 最新价
                "change_pct": safe_float(fields[32]),  # 涨跌幅
                "volume": volume_val,               # 成交量
                "amount": realtime_amount,           # 成交额（price × volume）
                "prev_close": safe_float(fields[4]),  # 昨收
                "market": market,                    # 市场 SH/SZ
                "fetch_source": "tencent",
            })
        except Exception:
            continue
    return items


def _load_fund_codes() -> list[dict]:
    """
    从 all_lof_codes.json 加载沪深 LOF/ETF 代码列表（兜底方案）。
    主路径: scheduler 从 DB 获取 codes 后直接传入 fetch_realtime(codes=...)。
    此函数仅在 codes 未传入时使用（如测试、手动触发）。
    """
    # 多路径探测: 优先 __file__ 相对路径，回退到 cwd
    json_paths = [
        Path(__file__).parent.parent / "all_lof_codes.json",  # backend-v2/all_lof_codes.json
        Path("all_lof_codes.json"),  # 当前工作目录
    ]
    for p in json_paths:
        try:
            if p.exists():
                import json
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data:
                    logger.info("[REALTIME] 从文件加载 %d 只基金代码: %s", len(data), p)
                    return [{"code": clean_code(d["code"]), "market": d.get("market", "SZ")} for d in data]
        except Exception as e:
            logger.warning("[REALTIME] 文件加载失败 %s: %s", p, e)

    logger.error("[REALTIME] all_lof_codes.json 未找到，请确保 scheduler 传入 codes 参数")
    return []
