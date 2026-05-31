"""
腾讯qt实时行情采集 — 成交额/换手率/涨跌幅/振幅/市值等
批量获取，50只/批，1秒间隔
"""
import asyncio
import logging
from datetime import date
from typing import Any

import httpx

from . import safe_float

logger = logging.getLogger("app")

QT_URL = "https://qt.gtimg.cn/q="
BATCH_SIZE = 50
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://qt.gtimg.cn/"}


def _parse_qt_line(line: str) -> dict | None:
    """
    解析腾讯qt单行数据
    字段索引:
    [1]名称 [2]代码 [3]最新价 [4]昨收 [5]今开
    [6]成交量(手) [31]涨跌额 [32]涨跌幅% [33]最高 [34]最低
    [37]成交额(万) [38]换手率% [43]振幅% [44]流通市值(亿) [45]总市值(亿)
    [47]涨停价 [48]跌停价 [49]量比 [81]单位净值
    """
    if "=" not in line:
        return None
    var_part, val_part = line.split("=", 1)
    val = val_part.strip().strip('";\n')
    if not val or len(val) < 10:
        return None

    fields = val.split("~")
    if len(fields) < 50:
        return None

    code_raw = var_part.split("_")[-1]
    code = code_raw[2:] if len(code_raw) > 2 else code_raw

    return {
        "code": code,
        "name": fields[1] if len(fields) > 1 else "",
        "close": safe_float(fields[3]),
        "prev_close": safe_float(fields[4]),
        "open": safe_float(fields[5]),
        "volume": safe_float(fields[6]),
        "change_amount": safe_float(fields[31]),
        "change_pct": safe_float(fields[32]),
        "high": safe_float(fields[33]),
        "low": safe_float(fields[34]),
        "amount_wan": safe_float(fields[37]),  # 万元
        "turnover_rate": safe_float(fields[38]),
        "amplitude": safe_float(fields[43]),
        "float_market_cap": safe_float(fields[44]),  # 亿
        "total_market_cap": safe_float(fields[45]),  # 亿
        "limit_up": safe_float(fields[47]),
        "limit_down": safe_float(fields[48]),
        "volume_ratio": safe_float(fields[49]),
        "nav": safe_float(fields[81]) if len(fields) > 81 else None,
    }


async def fetch_qt_batch(client: httpx.AsyncClient, codes: list[str]) -> list[dict]:
    """批量获取腾讯qt行情（50只/批）"""
    results = []
    for i in range(0, len(codes), BATCH_SIZE):
        batch = codes[i:i + BATCH_SIZE]
        qcodes = []
        for c in batch:
            prefix = "sh" if c.startswith(("5", "6")) else "sz"
            qcodes.append(f"{prefix}{c}")
        try:
            r = await client.get(f"{QT_URL}{','.join(qcodes)}", headers=HEADERS, timeout=15)
            for line in r.text.strip().split("\n"):
                parsed = _parse_qt_line(line)
                if parsed:
                    results.append(parsed)
        except Exception as e:
            logger.warning("[QT] batch %d failed: %s", i, e)
        await asyncio.sleep(1)
    return results