# -*- coding: utf-8 -*-
"""
LOF Fund Fee Data Fetcher

Fetches per-fund fee rates from East Money:
  - Purchase fee rate (申购费率, 天天基金优惠) from pingzhongdata API
  - Redemption fee rate (赎回费率, shortest/最短档) from jjfl HTML page
  - Daily purchase limit (日累计申购限额) from jjfl HTML page

These values change rarely (monthly or less), so they are cached
and refreshed on a longer interval than price/NAV data.
"""
import re, json, time, logging, threading, os
from typing import Dict, Optional, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

_FEE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://fund.eastmoney.com/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# Cache file path (same directory as this file)
_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fee_cache.json")


def _make_session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False
    retry = Retry(total=2, backoff_factor=1.0,
                  status_forcelist={502, 503, 504},
                  allowed_methods={"GET"})
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=30)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def _parse_purchase_limit_from_html(html: str) -> Optional[float]:
    """
    Parse 日累计申购限额 from jjfl HTML page.
    Returns: float (amount in 元) or None.
    "无限额" → None (no limit)
    "10.00元" → 10.0
    "100.00元" → 100.0
    """
    idx = html.find("日累计申购限额")
    if idx < 0:
        return None
    chunk = html[idx:idx+200]
    m = re.search(r'日累计申购限额.*?<td[^>]*>(.*?)</td>', chunk, re.DOTALL)
    if not m:
        return None
    val = re.sub(r'<[^>]+>', '', m.group(1)).strip()
    if not val or '无限额' in val or '---' in val:
        return None  # no limit
    # Extract number
    nm = re.search(r'([\d,.]+)\s*元', val)
    if nm:
        try:
            return float(nm.group(1).replace(',', ''))
        except ValueError:
            return None
    return None


def _parse_redemption_fee_from_html(html: str) -> Optional[float]:
    """
    Parse the shortest-period redemption fee rate from jjfl HTML.
    Returns: float (percentage, e.g., 1.5 for 1.5%) or None.
    """
    # Find "赎回费率" section (after the purchase fee section)
    idx = html.find("赎回费率")
    if idx < 0:
        return None
    chunk = html[idx:idx+800]
    # Clean HTML tags
    text = re.sub(r'<[^>]+>', '|', chunk)
    text = re.sub(r'&nbsp;', ' ', text)
    # Find first percentage after 赎回费率 header
    # Pattern: ... | <period> | <rate>% | ...
    rates = re.findall(r'(\d+\.\d+)%', text)
    if rates:
        try:
            return float(rates[0])
        except ValueError:
            return None
    return None


def fetch_fee_for_code(code: str, session: requests.Session) -> Dict[str, Any]:
    """
    Fetch fee data for a single fund code.
    Returns: {
        purchase_fee_rate: float | None,  # 申购优惠费率(%), e.g., 0.12
        redemption_fee_rate: float | None, # 赎回费率最短档(%), e.g., 1.5
        purchase_limit: float | None,     # 日累计申购限额(元), None=无限额
    }
    """
    result = {
        "purchase_fee_rate": None,
        "redemption_fee_rate": None,
        "purchase_limit": None,
    }

    # 1. Get purchase fee rate from pingzhongdata (fast, small response)
    try:
        url = f"https://fund.eastmoney.com/pingzhongdata/{code}.js"
        resp = session.get(url, headers=_FEE_HEADERS, timeout=10)
        resp.encoding = "utf-8"
        text = resp.text
        # Extract fund_Rate (天天基金优惠费率)
        m = re.search(r'var\s+fund_Rate\s*=\s*"([\d.]+)"', text)
        if m:
            result["purchase_fee_rate"] = float(m.group(1))
    except Exception as ex:
        logger.debug(f"pingzhongdata fee fetch failed for {code}: {ex}")

    # 2. Get redemption fee rate and purchase limit from jjfl HTML page
    try:
        url = f"https://fundf10.eastmoney.com/jjfl_{code}.html"
        resp = session.get(url, headers={
            **_FEE_HEADERS,
            "Referer": f"https://fundf10.eastmoney.com/jjfl_{code}.html",
        }, timeout=10)
        resp.encoding = "utf-8"
        html = resp.text
        result["redemption_fee_rate"] = _parse_redemption_fee_from_html(html)
        result["purchase_limit"] = _parse_purchase_limit_from_html(html)
    except Exception as ex:
        logger.debug(f"jjfl fee fetch failed for {code}: {ex}")

    return result


def fetch_fees_batch(codes: list, concurrency: int = 10) -> Dict[str, Dict[str, Any]]:
    """
    Batch fetch fee data for multiple fund codes.
    Uses concurrent threads for speed.
    Returns: {code: {purchase_fee_rate, redemption_fee_rate, purchase_limit}}
    """
    result: Dict[str, Dict[str, Any]] = {}
    lock = threading.Lock()
    sem = threading.Semaphore(concurrency)
    session = _make_session()

    def fetch_one(code: str) -> None:
        with sem:
            try:
                fee_data = fetch_fee_for_code(code, session)
                with lock:
                    result[code] = fee_data
            except Exception:
                pass
            # Small delay to avoid rate limiting
            time.sleep(0.05)

    threads = []
    for code in codes:
        t = threading.Thread(target=fetch_one, args=(code,))
        t.start()
        threads.append(t)
        if len(threads) >= 50:
            for tt in threads:
                tt.join()
            threads = []

    for tt in threads:
        tt.join()

    logger.info(f"Fee data fetched: {len(result)}/{len(codes)} funds")
    return result


def load_fee_cache() -> Dict[str, Dict[str, Any]]:
    """Load fee data from local cache file."""
    if not os.path.exists(_CACHE_PATH):
        return {}
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_fee_cache(data: Dict[str, Dict[str, Any]]) -> None:
    """Save fee data to local cache file."""
    try:
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as ex:
        logger.warning(f"Failed to save fee cache: {ex}")
