# -*- coding: utf-8 -*-
"""
新浪财经数据源 — LOF 实时行情
API: https://hq.sinajs.cn/list=sh501200,sz160505
返回格式: var hq_str_sh501200="名称,今开,昨收,现价,最高,最低,...,成交量,成交额,..."
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

_SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn/",
}


def _safe_float(val, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


class SinaSource(LOFDataSource):
    """新浪财经 LOF 数据源"""

    name = "Sina"

    def __init__(self):
        self._session: Optional[requests.Session] = None

    def _sess(self) -> requests.Session:
        if self._session is None:
            s = requests.Session()
            s.trust_env = False
            s.mount("https://", HTTPAdapter(max_retries=Retry(total=1, backoff_factor=1.0)))
            self._session = s
        return self._session

    def fetch_all_prices(self) -> Dict[str, dict]:
        """新浪不支持批量获取LOF列表，此方法仅供降级时逐基金调用"""
        return {}

    def fetch_single_price(self, code: str) -> Optional[Dict[str, Any]]:
        """获取单只基金实时行情"""
        market = "sh" if code.startswith(("5", "6", "9")) else "sz"
        try:
            resp = self._sess().get(
                f"https://hq.sinajs.cn/list={market}{code}",
                headers=_SINA_HEADERS,
                timeout=Config.REQUEST_TIMEOUT,
            )
            resp.encoding = "gbk"
            text = resp.text
            if "hq_str_" not in text:
                return None
            # 解析: var hq_str_sh501200="name,open,prev,price,high,low,buy,sell,volume,amount,..."
            start = text.find('"') + 1
            end = text.rfind('"')
            if start <= 0 or end <= start:
                return None
            parts = text[start:end].split(",")
            if len(parts) < 10:
                return None
            name = parts[0]
            price = _safe_float(parts[3])  # 当前价
            prev = _safe_float(parts[2])   # 昨收
            volume = int(_safe_float(parts[8]))  # 成交量(股)
            amount = round(_safe_float(parts[9]), 2)  # 成交额(元)
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
            logger.debug("Sina fetch_single_price(%s) failed: %s", code, e)
            return None

    def fetch_nav_history(self, code: str, start_date: str, end_date: str) -> Dict[str, float]:
        return {}

    def health_check(self) -> bool:
        try:
            resp = self._sess().get(
                "https://hq.sinajs.cn/list=sh000001",
                headers=_SINA_HEADERS,
                timeout=10,
            )
            return resp.status_code == 200 and "hq_str_" in resp.text
        except Exception:
            return False
