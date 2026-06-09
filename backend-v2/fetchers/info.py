"""
基金基础信息+持仓采集 - fundf10 HTML 爬取
"""
import asyncio
import json
import logging
import re
import time
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings
from constants import FUNDINFO_BATCH_SIZE, FUNDINFO_BATCH_DELAY
from mq import publish_event
from metrics import metrics
from . import clean_code, safe_float, safe_int

logger = logging.getLogger("app")

FEE_URL = "https://fundf10.eastmoney.com/jjfl_{code}.html"
HOLDINGS_URL = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={code}&topline=10"
INFO_URL = "https://fundf10.eastmoney.com/jbgk_{code}.html"
EMPTY_HOLDINGS_THRESHOLD = 5  # 连续N只持仓为空才中断（QDII/债基可能无持仓）
PROGRESS_FILE = "fetch_progress.json"

async def fetch_info(client: httpx.AsyncClient, codes: list[str], force: bool = False) -> list[dict]:
    """
    采集 fundf10 数据。
    force=True: 直接使用传入的 codes，跳过进度文件（用于测试和手动触发）。
    """
    if not codes:
        return []
    start = time.monotonic()
    if force:
        codes_to_fetch = [clean_code(c) for c in codes]
    else:
        progress = _load_progress()
        last_code = progress.get("last_code", "")
        failed_codes = [clean_code(c) for c in progress.get("failed_codes", [])]
        codes_to_fetch = _get_batch_codes(codes, last_code, failed_codes)
    if not codes_to_fetch:
        return []
    logger.info("[INFO] 本次采集: %d 只基金", len(codes_to_fetch))
    results = []
    current_failed = []
    empty_count = 0
    for idx, code in enumerate(codes_to_fetch):
        retry_count = 0
        max_retries = 2
        success = False
        while retry_count <= max_retries and not success:
            try:
                info = await _fetch_single_info(client, code)
                if info:
                    results.append(info)
                    if info.get("holdings") == []:
                        empty_count += 1
                        if empty_count >= EMPTY_HOLDINGS_THRESHOLD:
                            logger.warning("[INFO] 连续%d只持仓为空（可能是债基/QDII），继续采集", empty_count)
                    else:
                        empty_count = 0
                    success = True
                else:
                    if retry_count < max_retries:
                        retry_count += 1
                        await asyncio.sleep(3)
                    else:
                        current_failed.append(code)
                        logger.warning("[INFO] %s 重试%d次后仍失败", code, max_retries)
                        success = True  # 跳出重试循环
            except Exception as e:
                if retry_count < max_retries:
                    retry_count += 1
                    logger.warning("[INFO] %s 异常(重试%d): %s", code, retry_count, e)
                    await asyncio.sleep(3)
                else:
                    logger.warning("[INFO] %s 最终失败: %s", code, e)
                    current_failed.append(code)
                    success = True
        _save_progress(code, codes_to_fetch, current_failed)
        if idx < len(codes_to_fetch) - 1:
            await asyncio.sleep(FUNDINFO_BATCH_DELAY)
    elapsed = time.monotonic() - start
    metrics.record_fetch("info_fundf10", len(results) > 0, elapsed * 1000)
    await publish_event("info", {"data": results, "fetch_source": "fundf10", "count": len(results)})
    logger.info("[INFO] 完成: %d/%d 成功, %.1fs", len(results), len(codes_to_fetch), elapsed)
    return results

async def _fetch_single_info(client: httpx.AsyncClient, code: str) -> dict | None:
    code = clean_code(code)
    fee, holdings_data, basic = await asyncio.gather(
        _fetch_fee(client, code), _fetch_holdings(client, code), _fetch_basic_info(client, code),
        return_exceptions=True)

    # 诊断日志
    fee_ok = isinstance(fee, dict) and bool(fee)
    hold_ok = isinstance(holdings_data, dict) and bool(holdings_data.get("holdings"))
    basic_ok = isinstance(basic, dict) and bool(basic)
    if not fee_ok or not basic_ok:
        logger.warning("[INFO] %s 部分失败: fee=%s(%s) holdings=%s(%s) basic=%s(%s)",
                       code,
                       type(fee).__name__, fee if isinstance(fee, Exception) else "ok" if fee_ok else "empty",
                       type(holdings_data).__name__, "ok" if hold_ok else "empty",
                       type(basic).__name__, basic if isinstance(basic, Exception) else "ok" if basic_ok else "empty")

    # market 从代码前缀推断: 5/6开头=SH, 其他=SZ
    market = "SH" if code.startswith(("5", "6")) else "SZ"
    result = {"code": code, "fetch_source": "fundf10", "market": market}
    if fee_ok:
        result.update(fee)
    if isinstance(holdings_data, dict):
        result["holdings"] = holdings_data.get("holdings", [])
        result["holding_quarter"] = holdings_data.get("quarter")
    else:
        result["holdings"] = []
    if basic_ok:
        result.update(basic)
    return result

_F10_HEADERS = {"Referer": "https://fundf10.eastmoney.com/"}


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=False)
@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=False)
async def _fetch_fee(client, code):
    try:
        r = await client.get(FEE_URL.format(code=code), headers=_F10_HEADERS, timeout=15)
        r.raise_for_status()
        return _parse_fee(r.text)
    except Exception:
        return {}

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=False)
async def _fetch_holdings(client, code):
    try:
        r = await client.get(HOLDINGS_URL.format(code=code), headers=_F10_HEADERS, timeout=15)
        r.raise_for_status()
        return _parse_holdings(r.text)
    except Exception:
        return []

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=False)
async def _fetch_basic_info(client, code):
    try:
        r = await client.get(INFO_URL.format(code=code), headers=_F10_HEADERS, timeout=15)
        r.raise_for_status()
        return _parse_info(r.text)
    except Exception:
        return {}

def _parse_fee(html):
    """
    解析 fundf10 费率页面。
    关键: label 和 value 在同一个 <tr> 的两个 <td> 中，用 </td><td> 精确锚定。
    """
    result = {}

    # ── 申购费率 ──
    # 结构1: <strike>1.50%</strike> 0.15%（优惠费率）
    # 结构2: <td>1.20%</td>（无优惠标签）
    m = re.search(r'申购费率.*?<table[^>]*>(.*?)</table>', html, re.DOTALL)
    if m:
        table = m.group(1)
        # 优先找 strike（优惠费率）
        strike = re.search(r"<strike[^>]*>([\d.]+)%</strike>", table)
        if strike:
            result["purchase_fee_rate"] = safe_float(strike.group(1))
        else:
            # 无 strike 时，找 tbody 中第一个百分比
            tbody_m = re.search(r'<tbody>(.*?)</tbody>', table, re.DOTALL)
            if tbody_m:
                pct = re.search(r'>([\d.]+)%', tbody_m.group(1))
                if pct:
                    result["purchase_fee_rate"] = safe_float(pct.group(1))

    # ── 赎回费率（取 tbody 第一个百分比）──
    m = re.search(r'赎回费率.*?<tbody>(.*?)</tbody>', html, re.DOTALL)
    if m:
        tbody = m.group(1)
        pct = re.search(r'>([\d.]+)%', tbody)
        if pct:
            result["redemption_fee_rate"] = safe_float(pct.group(1))

    # ── 申购状态 ──
    m = re.search(r'申购状态</td>\s*<td[^>]*>(.*?)</td>', html, re.DOTALL)
    if m:
        t = m.group(1).strip()
        result["purchase_status"] = "suspended" if ("暂停" in t or "停止" in t or "封闭" in t) else "open"

    # ── 赎回状态 ──
    m = re.search(r'赎回状态</td>\s*<td[^>]*>(.*?)</td>', html, re.DOTALL)
    if m:
        t = m.group(1).strip()
        result["redeem_status"] = "suspended" if ("暂停" in t or "停止" in t) else "open"

    # ── 限购金额 ──
    m = re.search(r'日累计申购限额</td>\s*<td[^>]*>(.*?)</td>', html, re.DOTALL)
    if m:
        t = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if "无限额" in t or "无限制" in t or "---" in t or not t:
            result["purchase_limit"] = None
        else:
            val = _num(t)
            if val is not None:
                limit_val = val
                if "亿" in t:
                    limit_val = val * 100000000
                elif "万" in t:
                    limit_val = val * 10000
                # 限额 >= 10亿 视为无限额
                if limit_val >= 1000000000:
                    result["purchase_limit"] = None
                else:
                    result["purchase_limit"] = limit_val

    # 暂停申购 → 限额强制为0
    if result.get("purchase_status") == "suspended":
        result["purchase_limit"] = 0

    # ── 赎回到账天数（"卖出确认日"在费率页面）──
    # 结构: <td class="th w110">卖出确认日</td><td style="width: 272px;">T+2</td>
    m = re.search(r'卖出确认日</td>\s*<td[^>]*>(.*?)</td>', html, re.DOTALL)
    if m:
        t = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        d = re.search(r'T\+(\d+)', t)
        if d:
            result["redeem_days"] = int(d.group(1))

    return result

def _parse_holdings(text):
    """
    解析持仓页面。返回 dict: {"holdings": [...], "quarter": "2026Q1"}
    topline=10 时表格有 9 列。
    注意: apidata 是 JavaScript 对象字面量（key 无引号），不能用 json.loads。
    用正则直接提取 content 值和 arryear。
    """
    # 提取 content: "...", arryear 之间的内容
    m = re.search(r'content\s*:\s*"(.*?)",\s*arryear', text, re.DOTALL)
    if not m:
        return {"holdings": [], "quarter": None}
    content = m.group(1)

    if not content:
        return {"holdings": [], "quarter": None}

    # 提取季度: "2026年1季度股票投资明细" → "2026Q1"
    quarter = None
    qm = re.search(r'(\d{4})年(\d)季度', content)
    if qm:
        quarter = f"{qm.group(1)}Q{qm.group(2)}"

    rows = re.findall(r'<td[^>]*>(.*?)</td>', content, re.DOTALL)
    COLS = 9  # topline=10 时每行 9 列
    holdings = []
    for i in range(0, len(rows), COLS):
        if i + COLS - 1 >= len(rows):
            break
        rank = safe_int(_strip_html(rows[i]).strip())
        code = _strip_html(rows[i + 1]).strip()
        name = _strip_html(rows[i + 2]).strip()
        pct = safe_float(_strip_html(rows[i + 6]).replace('%', ''))
        shares = safe_float(_strip_html(rows[i + 7]).replace(',', ''))
        if code and name:
            holdings.append({
                "rank": rank or (len(holdings) + 1),
                "code": code,
                "name": name,
                "pct": pct,
                "shares": shares,
            })
    return {"holdings": holdings, "quarter": quarter}


def _strip_html(s: str) -> str:
    """去除 HTML 标签"""
    return re.sub(r'<[^>]+>', '', s)

def _parse_info(html):
    """
    解析 fundf10 基本概况页面 (jbgk)。
    eastmoney HTML 不规范: <td> 常无 </td> 闭合，直接接 <th>。
    用 _th_td 提取 <th>关键词</th><td>值</td> 结构。
    """
    result = {}

    # 基金全称（用于推断 fund_type）
    full_name = _th_td(html, "基金全称")
    if full_name:
        result["name"] = full_name

    raw_type = _th_td(html, "基金类型")
    if raw_type:
        result["fund_type"] = _normalize_fund_type(raw_type)

    index = _th_td(html, "跟踪标的")
    if index and "无跟踪" not in index and "---" not in index:
        result["index_code"] = index

    aum_text = _th_td(html, "净资产规模")
    if aum_text:
        s = _num(aum_text)
        if s:
            result["aum"] = s if "亿" in aum_text else s / 10000 if "万" in aum_text else s

    # 成立日期: "2015年05月27日 / 3.965亿份" → "2015-05-27"
    date_text = _th_td(html, "成立日期/规模")
    if date_text:
        dm = re.search(r'(\d{4})年(\d{2})月(\d{2})日', date_text)
        if dm:
            result["listing_date"] = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}"

    return result


def _th_td(html: str, keyword: str) -> str | None:
    """
    从 <th>关键词</th><td>值</td> 或 <th>关键词</th><td>值<th> 提取值。
    eastmoney HTML 的 <td> 常无 </td>，下一个 <th> 直接跟在值后面。
    """
    m = re.search(
        re.escape(keyword) + r'</th>\s*<td[^>]*>(.*?)(?:</td>|<th|</tr>)',
        html, re.DOTALL,
    )
    if m:
        return re.sub(r'<[^>]+>', '', m.group(1)).strip()
    return None


def _normalize_fund_type(raw: str) -> str:
    """
    将基金类型标准化为 LOF/ETF/QDII。
    fundf10 返回的是投资风格（如"混合型-偏股"），不是交易类型。
    需要从原始文本中找 LOF/ETF/QDII 关键词。
    """
    upper = raw.upper()
    if "QDII" in upper:
        return "QDII"
    if "ETF" in upper:
        return "ETF"
    if "LOF" in upper or "上市开放式" in upper:
        return "LOF"
    # fundf10 返回投资风格时，保留原始值供上层参考
    return raw.strip()[:20] if raw.strip() else "OTHER"

def _pct(text):
    m = re.search(r'([\d.]+)\s*%', text)
    return safe_float(m.group(1)) if m else None

def _num(text):
    m = re.search(r'([\d,.]+)', text)
    return safe_float(m.group(1).replace(',','')) if m else None

def _get_batch_codes(all_codes, last_code, failed_codes):
    to_fetch = failed_codes[:FUNDINFO_BATCH_SIZE]
    if len(to_fetch) >= FUNDINFO_BATCH_SIZE:
        return to_fetch
    remaining = FUNDINFO_BATCH_SIZE - len(to_fetch)
    start_idx = 0
    if last_code and last_code in all_codes:
        try:
            start_idx = all_codes.index(last_code) + 1
        except ValueError:
            start_idx = 0
    return to_fetch + all_codes[start_idx:start_idx + remaining]

def _load_progress():
    try:
        with open(PROGRESS_FILE, "r") as f: return json.load(f)
    except Exception:
        return {}

def _save_progress(last_code, batch_codes, failed):
    try:
        with open(PROGRESS_FILE, "w") as f:
            json.dump({"last_code": last_code, "failed_codes": failed}, f)
    except Exception:
        pass
