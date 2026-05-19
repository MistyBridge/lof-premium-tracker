# -*- coding: utf-8 -*-
"""
网易财经数据源 — LOF 实时行情
API: https://api.money.163.com/data/stock/detail?code=0501200
     或 https://quotes.money.163.com/service/chddata.html?code=0501200
"""
import logging
import time
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import Config
from datasource.base import LOFDataSource

logger = logging.getLogger(__name__)

_NETEASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://money.163.com/",
}


def _safe_float(val, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


class NeteaseSource(LOFDataSource):
    """网易财经 LOF 数据源"""

    name = "Netease"

    def __init__(self):
        self._session: Optional[requests.Session] = None

    def _sess(self) -> requests.Session:
        if self._session is None:
            s = requests.Session()
            s.trust_env = False
            s.mount("https://", HTTPAdapter(max_retries=Retry(total=1, backoff_factor=1.0)))
            self._session = s
        return self._session

    def _market_prefix(self, code: str) -> str:
        """网易代码前缀: 0=深交所, 1=上交所"""
        return "1" if code.startswith(("5", "6", "9")) else "0"

    def fetch_all_prices(self) -> Dict[str, dict]:
        return {}

    def fetch_single_price(self, code: str) -> Optional[Dict[str, Any]]:
        """获取单只基金实时行情（网易批量API）"""
        prefix = self._market_prefix(code)
        try:
            resp = self._sess().get(
                f"https://api.money.163.com/data/stock/detail",
                params={"code": f"{prefix}{code}"},
                headers=_NETEASE_HEADERS,
                timeout=Config.REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            d = (data.get("data") or {})
            if not d:
                return None
            name = d.get("name", "")
            price = _safe_float(d.get("price"))
            prev = _safe_float(d.get("yestclose"))
            volume = int(_safe_float(d.get("volume")))
            amount = round(_safe_float(d.get("turnover")), 2)
            if price <= 0:
                return None
            change_pct = round((price - prev) / prev * 100, 3) if prev > 0 else 0.0
            return {
                "code": code,
                "name": name,
                "price": price,
                "prev_close": prev,
                "change_pct": change_pct,
                "volume": volume,
                "amount": amount,
            }
        except Exception as e:
            logger.debug("Netease fetch_single_price(%s) failed: %s", code, e)
            return None

    def fetch_nav_history(self, code: str, start_date: str, end_date: str) -> Dict[str, float]:
        return {}

    def health_check(self) -> bool:
        try:
            resp = self._sess().get(
                "https://api.money.163.com/data/stock/detail",
                params={"code": "1000001"},
                headers=_NETEASE_HEADERS,
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False
