# -*- coding: utf-8 -*-
"""
后备数据源 — 封装东方财富 / 腾讯 / 天天基金等原有 API
当主数据源 (AkShare) 不可用时自动降级使用
"""
import json
import logging
import os
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

# ═══════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════

SSE_LOF_PREFIXES = ("501", "502")
SZ_LOF_RANGES: List[range] = [range(160000, 170000), range(184000, 185000)]
_SZ_LOF_CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sz_lof_codes.json")
_SZ_LOF_SCAN_INTERVAL_DAYS = 7

# ═══════════════════════════════════════════════════════════
# Utilities
# ═══════════════════════════════════════════════════════════

def _safe_float(val, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _jparse(text: str) -> dict:
    text = text.strip()
    m = re.search(r"^jQuery\s*\((.+)\)", text, re.DOTALL)
    if m:
        raw = m.group(1).strip().rstrip(";").rstrip(")")
        return json.loads(raw)
    return json.loads(text)


def _is_sze_lof(code: str) -> bool:
    try:
        n = int(code)
        return any(n in r for r in SZ_LOF_RANGES)
    except (ValueError, TypeError):
        return False


def _is_sse_lof(code: str) -> bool:
    return code.startswith(SSE_LOF_PREFIXES)


# ═══════════════════════════════════════════════════════════
# HTTP
# ═══════════════════════════════════════════════════════════

_EM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Referer": "http://quote.eastmoney.com/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Connection": "keep-alive",
}

_TT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://gu.qq.com/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Connection": "keep-alive",
}

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


def _make_session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False
    retry = Retry(
        total=3, backoff_factor=1.0,
        status_forcelist={502, 503, 504, 429, 403},
        allowed_methods={"GET"},
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=60)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


# ═══════════════════════════════════════════════════════════
# Tencent QT Parser
# ═══════════════════════════════════════════════════════════

def _parse_tencent_qt(text: str) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for line in text.strip().splitlines():
        if "~" not in line:
            continue
        key = line.split("=")[0].strip()
        if not key.startswith("v_"):
            continue
        suffix = key[2:]
        code = suffix[2:]
        parts = line.split("~")
        if len(parts) < 5:
            continue

        price = parts[3] if parts[3] != "-" else None
        prev = parts[4] if parts[4] != "-" else None
        name = parts[1]

        if price is None or price == "":
            continue

        try:
            price_f = float(price)
            prev_f = float(prev) if prev else price_f
        except (ValueError, TypeError):
            continue

        change_pct = round((price_f - prev_f) / prev_f * 100, 3) if prev_f else 0.0

        volume_raw = parts[36] if len(parts) > 36 else ""
        turn_raw = parts[57] if len(parts) > 57 else ""
        volume = int(_safe_float(volume_raw)) if volume_raw not in ("", "-") else 0
        amount = round(_safe_float(turn_raw, 0.0) * 10000, 2) if turn_raw not in ("", "-") else 0.0
        if amount == 0.0 and price_f > 0 and volume > 0:
            amount = round(price_f * volume * 100, 2)

        result[code] = {
            "code": code, "name": name, "price": price_f,
            "prev_close": prev_f, "change_pct": change_pct,
            "volume": volume, "amount": amount,
        }
    return result


# ═══════════════════════════════════════════════════════════
# SZ LOF Code Cache
# ═══════════════════════════════════════════════════════════

_SZ_LOF_CODES: Optional[List[str]] = None


def _load_sz_lof_cache() -> dict:
    if os.path.exists(_SZ_LOF_CACHE_PATH):
        try:
            with open(_SZ_LOF_CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Failed to load SZ LOF cache: %s", e)
    return {}


def _is_sz_cache_stale(cache: dict) -> bool:
    meta = cache.get("_meta", {})
    updated = meta.get("updated_at", "")
    if not updated:
        return True
    try:
        last = datetime.fromisoformat(updated)
        return (datetime.now() - last).days >= _SZ_LOF_SCAN_INTERVAL_DAYS
    except (ValueError, TypeError):
        return True


def _get_sz_lof_codes() -> List[str]:
    global _SZ_LOF_CODES
    if _SZ_LOF_CODES is not None:
        return _SZ_LOF_CODES
    cache = _load_sz_lof_cache()
    _SZ_LOF_CODES = [k for k in cache.keys() if not k.startswith("_")]
    logger.info("Loaded %d SZ LOF codes from cache", len(_SZ_LOF_CODES))
    return _SZ_LOF_CODES


# ═══════════════════════════════════════════════════════════
# LegacySource
# ═══════════════════════════════════════════════════════════

class LegacySource(LOFDataSource):
    """后备数据源：东方财富 push2delay + 腾讯 qt.gtimg.cn + 天天基金 fundgz"""

    name = "Legacy"

    def __init__(self):
        self._session: Optional[requests.Session] = None

    def _sess(self) -> requests.Session:
        if self._session is None:
            self._session = _make_session()
        return self._session

    # ── Public API ──────────────────────────────────

    def fetch_all_prices(self) -> Dict[str, dict]:
        sse = self._fetch_sse_from_em()
        sz_codes = self._maybe_refresh_sz_codes()
        sz = self._fetch_sz_from_qt(sz_codes)
        all_prices: Dict[str, dict] = {}
        for code, fund in sse.items():
            all_prices[code] = fund
        for code, price_data in sz.items():
            if code not in all_prices:
                all_prices[code] = price_data
        logger.info("Legacy: %d prices (SSE=%d, SZ=%d)", len(all_prices), len(sse), len(sz))
        return all_prices

    def fetch_single_nav(self, code: str) -> Dict[str, Any]:
        return self._fetch_nav_single(code)

    def fetch_nav_batch(self, funds: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        return self._fetch_nav_batch(funds)

    def fetch_kline(self, code: str, start_date: str, end_date: str) -> Dict[str, dict]:
        return self._fetch_kline(code, start_date, end_date)

    def fetch_nav_history(self, code: str, start_date: str, end_date: str) -> Dict[str, float]:
        return self._fetch_nav_history(code, start_date, end_date)

    def health_check(self) -> bool:
        try:
            resp = self._sess().get(
                "https://push2delay.eastmoney.com/api/qt/clist/get"
                "?pn=1&pz=1&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281"
                "&fltt=2&invt=2&fid=f3&fs=m:1+t:9&fields=f12",
                headers=_EM_HEADERS, timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False

    # ── SSE Price Fetching ──────────────────────────

    def _fetch_sse_from_em(self) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        seen: set = set()
        for pn in range(1, 25):
            url = (
                "https://push2delay.eastmoney.com/api/qt/clist/get"
                f"?pn={pn}&pz=100&po=1&np=1"
                f"&ut=bd1d9ddb04089700cf9c27f6f7426281"
                f"&fltt=2&invt=2&fid=f3"
                f"&fs=m:1+t:9"
                f"&fields=f12,f14,f2,f3,f5,f20"
            )
            resp = None
            for attempt in range(3):
                try:
                    resp = self._sess().get(url, headers=_EM_HEADERS, timeout=Config.REQUEST_TIMEOUT)
                    break
                except Exception as ex:
                    logger.warning("SSE pn=%d attempt %d failed: %s", pn, attempt + 1, ex)
                    if attempt < 2:
                        time.sleep(2 ** attempt)
            if resp is None or resp.status_code != 200:
                break

            resp.encoding = "utf-8"
            try:
                data = _jparse(resp.text)
            except Exception as ex:
                logger.warning("SSE pn=%d parse failed: %s", pn, ex)
                break

            items = (data.get("data") or {}) or {}
            diff = items.get("diff", [])
            total = items.get("total", 0)
            if not diff:
                break

            for item in diff:
                code = str(item.get("f12", "")).strip()
                if not re.match(r"^\d{6}$", code) or code in seen:
                    continue
                seen.add(code)
                if not _is_sse_lof(code):
                    continue
                price_raw = item.get("f2")
                if price_raw == "-" or price_raw is None:
                    continue
                price = _safe_float(price_raw)
                if price <= 0:
                    continue
                result[code] = {
                    "code": code.zfill(6),
                    "name": str(item.get("f14", "")).strip(),
                    "price": price,
                    "change_pct": round(_safe_float(item.get("f3"), 0), 3),
                    "volume": int(_safe_float(item.get("f5"), 0)),
                    "amount": round(_safe_float(item.get("f20"), 0), 2),
                }
            if len(seen) >= total:
                break
            time.sleep(0.2)
        return result

    # ── SZ LOF Code Management ──────────────────────

    def _maybe_refresh_sz_codes(self) -> List[str]:
        cache = _load_sz_lof_cache()
        if _is_sz_cache_stale(cache):
            logger.info("SZ LOF cache stale, refreshing from push2delay...")
            try:
                new_codes = self._fetch_sz_codes_from_em()
                if new_codes:
                    merged = {}
                    for k, v in cache.items():
                        if not k.startswith("_"):
                            merged[k] = v
                    merged.update(new_codes)
                    merged["_meta"] = {"updated_at": datetime.now().isoformat(), "count": len(new_codes)}
                    with open(_SZ_LOF_CACHE_PATH, "w", encoding="utf-8") as f:
                        json.dump(merged, f, ensure_ascii=False, indent=2)
                    global _SZ_LOF_CODES
                    _SZ_LOF_CODES = list(new_codes.keys())
                    logger.info("SZ LOF cache refreshed: %d codes", len(new_codes))
            except Exception as e:
                logger.warning("SZ LOF cache refresh failed: %s, using stale", e)
        return _get_sz_lof_codes()

    def _fetch_sz_codes_from_em(self) -> Dict[str, str]:
        result: Dict[str, str] = {}
        seen: set = set()
        for pn in range(1, 25):
            url = (
                "https://push2delay.eastmoney.com/api/qt/clist/get"
                f"?pn={pn}&pz=100&po=1&np=1"
                f"&ut=bd1d9ddb04089700cf9c27f6f7426281"
                f"&fltt=2&invt=2&fid=f3"
                f"&fs=m:0+t:9"
                f"&fields=f12,f14"
            )
            resp = None
            for attempt in range(3):
                try:
                    resp = self._sess().get(url, headers=_EM_HEADERS, timeout=Config.REQUEST_TIMEOUT)
                    break
                except Exception as ex:
                    logger.warning("SZ scan pn=%d attempt %d failed: %s", pn, attempt + 1, ex)
                    if attempt < 2:
                        time.sleep(2 ** attempt)
            if resp is None or resp.status_code != 200:
                break
            resp.encoding = "utf-8"
            try:
                data = _jparse(resp.text)
            except Exception as ex:
                logger.warning("SZ scan pn=%d parse failed: %s", pn, ex)
                break

            items = (data.get("data") or {}) or {}
            diff = items.get("diff", [])
            total = items.get("total", 0)
            if not diff:
                break
            for item in diff:
                code = str(item.get("f12", "")).strip()
                if not re.match(r"^\d{6}$", code) or code in seen:
                    continue
                seen.add(code)
                if not _is_sze_lof(code):
                    continue
                name = str(item.get("f14", "")).strip()
                result[code] = name
            if len(seen) >= total:
                break
            time.sleep(0.15)
        logger.info("SZ LOF code scan complete: %d found", len(result))
        return result

    # ── SZ Price Fetching ───────────────────────────

    def _fetch_sz_from_qt(self, codes: List[str]) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        BATCH = 100
        for i in range(0, len(codes), BATCH):
            batch = codes[i:i + BATCH]
            qt_codes = ",".join(f"sz{c}" for c in batch)
            url = f"https://qt.gtimg.cn/q={qt_codes}"
            try:
                resp = self._sess().get(url, headers=_TT_HEADERS, timeout=Config.REQUEST_TIMEOUT)
                resp.encoding = resp.apparent_encoding or "gbk"
                parsed = _parse_tencent_qt(resp.text)
                result.update(parsed)
            except Exception as ex:
                logger.warning("SZ qt batch %d failed: %s", i // BATCH + 1, ex)
            time.sleep(0.1)
        return result

    # ── NAV Fetching ────────────────────────────────

    def _fetch_nav_batch(self, funds: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
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
                        nav_info = self._fetch_nav_single(code)
                        break
                    except Exception as ex:
                        if attempt < MAX_RETRIES:
                            time.sleep(0.5 * (attempt + 1))
                        else:
                            logger.warning("NAV fetch failed %s after %d attempts: %s", code, MAX_RETRIES + 1, ex)
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
                logger.info("NAV progress: %d/%d", min(i + 1, total), total)
        for tt in threads:
            tt.join()

        # 2nd pass for missed funds
        missing = [f for f in funds if f["code"] not in result or result[f["code"]].get("nav") is None]
        if missing:
            logger.info("NAV 2nd pass: %d funds missing NAV, retrying...", len(missing))
            for fund in missing:
                code = fund["code"]
                try:
                    nav_info = self._fetch_nav_single(code)
                    if nav_info.get("nav") is not None:
                        with lock:
                            result[code] = {**fund, **nav_info}
                except Exception as ex:
                    logger.warning("NAV 2nd pass failed %s: %s", code, ex)

        nav_ok = sum(1 for v in result.values() if v.get("nav") is not None)
        logger.info("NAV batch complete: %d/%d with NAV", nav_ok, total)
        return result

    def _fetch_nav_single(self, code: str) -> Dict[str, Any]:
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

    # ── K-line & NAV History ────────────────────────

    def _fetch_kline(self, code: str, start_date: str, end_date: str) -> Dict[str, dict]:
        market = "1" if code.startswith(("501", "502")) else "0"
        secid = f"{market}.{code}"
        url = (
            f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
            f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
            f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
            f"&klt=101&fqt=0&beg={start_date}&end={end_date}"
        )
        KLINE_HEADERS = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "http://quote.eastmoney.com/",
            "Accept": "*/*",
        }
        try:
            resp = self._sess().get(url, headers=KLINE_HEADERS, timeout=10)
            data = resp.json()
            if data.get("rc") != 0 or not data.get("data") or not data["data"].get("klines"):
                return {}
            result = {}
            name = data["data"].get("name", "")
            for line in data["data"]["klines"]:
                parts = line.split(",")
                if len(parts) < 7:
                    continue
                date = parts[0]
                price = _safe_float(parts[2])
                amount = _safe_float(parts[6])
                change_pct = _safe_float(parts[8])
                if price <= 0:
                    continue
                result[date] = {"price": price, "amount": amount, "change_pct": change_pct, "name": name}
            return result
        except Exception as e:
            logger.debug("K-line fetch failed for %s: %s", code, e)
            return {}

    def _fetch_nav_history(self, code: str, start_date: str, end_date: str) -> Dict[str, float]:
        NAV_HEADERS = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://fund.eastmoney.com/",
            "Accept": "*/*",
        }
        url = (
            f"https://api.fund.eastmoney.com/f10/lsjz"
            f"?fundCode={code}&pageIndex=1&pageSize=15"
            f"&startDate={start_date}&endDate={end_date}"
        )
        try:
            resp = self._sess().get(url, headers=NAV_HEADERS, timeout=10)
            data = resp.json()
            lsjz_list = (data.get("Data") or {}).get("LSJZList") or []
            result = {}
            for item in lsjz_list:
                date = item.get("FSRQ")
                nav_str = item.get("DWJZ")
                if date and nav_str:
                    nav = _safe_float(nav_str)
                    if nav > 0:
                        result[date] = nav
            return result
        except Exception as e:
            logger.debug("NAV history fetch failed for %s: %s", code, e)
            return {}
