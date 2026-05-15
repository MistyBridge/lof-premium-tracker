# -*- coding: utf-8 -*-
"""
主数据源 — AkShare
日常数据抓取使用 AkShare，获取全市场 LOF 基金行情和历史数据
"""
import json
import logging
import re
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import Config
from datasource.base import LOFDataSource

logger = logging.getLogger(__name__)


def _safe_float(val, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ── NAV Headers (fundgz — AkShare 无盘中估算净值) ──

_FUNDGZ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://fund.eastmoney.com/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Connection": "keep-alive",
}

_LSJZ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://fundf10.eastmoney.com/",
    "Accept": "*/*",
}


class AkShareSource(LOFDataSource):
    """主数据源：使用 AkShare 获取 LOF 基金数据"""

    name = "AkShare"

    def __init__(self):
        self._session: Optional[requests.Session] = None

    def _sess(self) -> requests.Session:
        if self._session is None:
            s = requests.Session()
            s.trust_env = False
            retry = Retry(total=2, backoff_factor=1.0,
                          status_forcelist={502, 503, 504},
                          allowed_methods={"GET"})
            adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=30)
            s.mount("http://", adapter)
            s.mount("https://", adapter)
            self._session = s
        return self._session

    # ── Public API ──────────────────────────────────

    def fetch_all_prices(self) -> Dict[str, dict]:
        """使用 ak.fund_lof_spot_em() 获取全量 LOF 行情"""
        try:
            import akshare as ak
        except ImportError:
            logger.warning("AkShare not installed, cannot fetch prices")
            return {}

        try:
            df = ak.fund_lof_spot_em()
        except Exception as e:
            logger.warning("AkShare fund_lof_spot_em() failed: %s", e)
            return {}

        if df is None or df.empty:
            logger.warning("AkShare returned empty DataFrame")
            return {}

        result: Dict[str, dict] = {}
        for _, row in df.iterrows():
            code = str(row.get("代码", "")).strip()
            if not code or len(code) != 6 or not code.isdigit():
                continue

            price = _safe_float(row.get("最新价"), 0)
            if price <= 0:
                continue

            result[code] = {
                "code": code,
                "name": str(row.get("名称", "")).strip() or code,
                "price": price,
                "change_pct": round(_safe_float(row.get("涨跌幅"), 0), 3),
                "volume": int(_safe_float(row.get("成交量"), 0)),
                "amount": round(_safe_float(row.get("成交额"), 0), 2),
            }

        logger.info("AkShare: %d LOF prices fetched", len(result))
        return result

    def fetch_single_nav(self, code: str) -> Dict[str, Any]:
        """
        NAV/估算净值 — AkShare 无盘中估算净值功能，
        必须使用 fundgz API。此方法与后备数据源共用 fundgz。
        """
        return self._fetch_nav_from_fundgz(code)

    def fetch_nav_batch(self, funds: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """批量 NAV — AkShare 无盘中估算净值，使用 fundgz 批量获取"""
        result: Dict[str, Dict[str, Any]] = {}
        lock = threading.Lock()
        sem = threading.Semaphore(10)
        total = len(funds)
        MAX_RETRIES = 2

        def fetch_one(fund: Dict[str, Any]) -> None:
            code = fund["code"]
            with sem:
                nav_info = None
                for attempt in range(MAX_RETRIES + 1):
                    try:
                        nav_info = self._fetch_nav_from_fundgz(code)
                        break
                    except Exception as ex:
                        if attempt < MAX_RETRIES:
                            time.sleep(0.5 * (attempt + 1))
                        else:
                            logger.warning("AkShare NAV fetch failed %s: %s", code, ex)
                if nav_info is None:
                    nav_info = {"nav": None, "nav_date": None, "prev_nav": None, "is_formal_nav": False}
                with lock:
                    result[code] = {**fund, **nav_info}

        threads: List[threading.Thread] = []
        for i, fund in enumerate(funds):
            t = threading.Thread(target=fetch_one, args=(fund,))
            t.start()
            threads.append(t)
            if len(threads) >= 50:
                for tt in threads:
                    tt.join()
                threads = []
                logger.info("AkShare NAV progress: %d/%d", min(i + 1, total), total)
        for tt in threads:
            tt.join()

        # 2nd pass
        missing = [f for f in funds if f["code"] not in result or result[f["code"]].get("nav") is None]
        if missing:
            logger.info("AkShare NAV 2nd pass: %d funds missing, retrying...", len(missing))
            for fund in missing:
                code = fund["code"]
                try:
                    nav_info = self._fetch_nav_from_fundgz(code)
                    if nav_info.get("nav") is not None:
                        with lock:
                            result[code] = {**fund, **nav_info}
                except Exception:
                    pass

        nav_ok = sum(1 for v in result.values() if v.get("nav") is not None)
        logger.info("AkShare NAV batch: %d/%d with NAV", nav_ok, total)
        return result

    def fetch_kline(self, code: str, start_date: str, end_date: str) -> Dict[str, dict]:
        """使用 ak.fund_lof_hist_em() 获取日K线"""
        try:
            import akshare as ak
        except ImportError:
            return {}

        try:
            df = ak.fund_lof_hist_em(
                symbol=code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="",
            )
        except Exception as e:
            logger.debug("AkShare fund_lof_hist_em(%s) failed: %s", code, e)
            return {}

        if df is None or df.empty:
            return {}

        result = {}
        name = str(df.iloc[0].get("名称", "")) if "名称" in df.columns else ""
        for _, row in df.iterrows():
            date_raw = str(row.get("日期", ""))
            if not date_raw:
                continue
            # AkShare 返回 YYYY-MM-DD 格式
            date = date_raw.strip()[:10]
            price = _safe_float(row.get("收盘"), 0)
            amount = _safe_float(row.get("成交额"), 0)
            change_pct = _safe_float(row.get("涨跌幅"), 0)
            if price <= 0:
                continue
            result[date] = {
                "price": price,
                "amount": amount,
                "change_pct": change_pct,
                "name": name,
            }
        return result

    def fetch_nav_history(self, code: str, start_date: str, end_date: str) -> Dict[str, float]:
        """使用 ak.fund_open_fund_info_em(indicator="单位净值走势") 获取历史净值"""
        try:
            import akshare as ak
        except ImportError:
            return {}

        try:
            df = ak.fund_open_fund_info_em(
                symbol=code,
                indicator="单位净值走势",
            )
        except Exception as e:
            logger.debug("AkShare fund_open_fund_info_em(%s) failed: %s", code, e)
            return {}

        if df is None or df.empty:
            return {}

        result = {}
        for _, row in df.iterrows():
            date_raw = str(row.get("净值日期", ""))
            if not date_raw:
                continue
            date = date_raw.strip()[:10]
            if start_date and date < start_date:
                continue
            if end_date and date > end_date:
                continue
            nav = _safe_float(row.get("单位净值"), 0)
            if nav > 0:
                result[date] = nav
        return result

    def health_check(self) -> bool:
        try:
            import akshare as ak
            df = ak.fund_lof_spot_em()
            return df is not None and not df.empty
        except Exception:
            return False

    # ── fundgz NAV (AkShare 无盘中估算净值) ─────────

    def _fetch_nav_from_fundgz(self, code: str) -> Dict[str, Any]:
        """fundgz + lsjz 交叉验证，盘中优先用估算净值(gsz)"""
        url = Config.FUND_NAV_URL.format(code=code)
        try:
            resp = self._sess().get(url, headers=_FUNDGZ_HEADERS, timeout=Config.REQUEST_TIMEOUT)
            resp.encoding = "utf-8"
            text = resp.text.strip()
        except Exception:
            return self._fetch_nav_from_lsjz(code)

        m = re.search(r"\((.+)\)\s*;?\s*$", text, re.DOTALL)
        if not m:
            return self._fetch_nav_from_lsjz(code)

        try:
            data = json.loads(m.group(1).strip().rstrip(";").rstrip(")"))
        except json.JSONDecodeError:
            return self._fetch_nav_from_lsjz(code)

        today = datetime.now().strftime("%Y-%m-%d")
        jzrq = data.get("jzrq", "")  # 净值日期
        dwjz = data.get("dwjz")  # 最新官方净值
        gsz = data.get("gsz")  # 盘中估算净值
        prev_str = data.get("jjjz")  # 前一交易日净值
        gztime = data.get("gztime", "")

        # Step 1: lsjz 交叉验证，有今日官方净值则优先
        lsjz_info = self._fetch_nav_from_lsjz(code)
        if lsjz_info.get("nav_date") == today and lsjz_info.get("nav"):
            return lsjz_info

        # Step 2: fundgz 今日官方净值
        if jzrq == today and dwjz:
            nav = _safe_float(dwjz)
            prev = _safe_float(prev_str, nav)
            return {
                "nav": round(nav, 4),
                "prev_nav": round(prev, 4),
                "nav_date": jzrq,
                "is_formal_nav": True,
            }

        # Step 3: 盘中估算净值 gsz
        if gsz and _safe_float(gsz) > 0:
            nav = _safe_float(gsz)
            prev = _safe_float(dwjz, nav) if dwjz else _safe_float(prev_str, nav)
            return {
                "nav": round(nav, 4),
                "prev_nav": round(prev, 4),
                "nav_date": str(gztime) if gztime else today,
                "is_formal_nav": False,
            }

        # Step 4: fundgz 昨日官方净值（兜底）
        if dwjz:
            nav = _safe_float(dwjz)
            prev = _safe_float(prev_str, nav)
            return {
                "nav": round(nav, 4),
                "prev_nav": round(prev, 4),
                "nav_date": jzrq,
                "is_formal_nav": True,
            }

        # Step 5: lsjz 兜底
        if lsjz_info.get("nav"):
            return lsjz_info

        return {"nav": None, "nav_date": None, "is_formal_nav": False}

    def _fetch_nav_from_lsjz(self, code: str) -> Dict[str, Any]:
        url = f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex=1&pageSize=1"
        try:
            resp = self._sess().get(url, headers=_LSJZ_HEADERS, timeout=Config.REQUEST_TIMEOUT)
            resp.encoding = "utf-8"
            data = resp.json()
            if data.get("ErrCode") != 0:
                return {"nav": None, "nav_date": None, "is_formal_nav": False, "can_purchase": None}
            lsjz_list = (data.get("Data") or {}).get("LSJZList") or []
            if not lsjz_list:
                return {"nav": None, "nav_date": None, "is_formal_nav": False, "can_purchase": None}
            latest = lsjz_list[0]
            nav_str = latest.get("DWJZ")
            date_str = latest.get("FSRQ")
            sgzt = latest.get("SGZT", "")
            can_purchase = "开放" in sgzt or "限制大额" in sgzt
            if not nav_str:
                return {"nav": None, "nav_date": None, "is_formal_nav": False, "can_purchase": can_purchase}
            nav = _safe_float(nav_str)
            if nav <= 0:
                return {"nav": None, "nav_date": None, "is_formal_nav": False, "can_purchase": can_purchase}
            return {
                "nav": round(nav, 4),
                "prev_nav": round(nav, 4),
                "nav_date": date_str or None,
                "is_formal_nav": True,
                "can_purchase": can_purchase,
            }
        except Exception as ex:
            logger.debug("lsjz fallback failed for %s: %s", code, ex)
            return {"nav": None, "nav_date": None, "is_formal_nav": False, "can_purchase": None}
