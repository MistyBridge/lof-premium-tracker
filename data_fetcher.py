# -*- coding: utf-8 -*-
"""
LOF Fund Data Fetcher

Data Sources:
  SSE market prices -> push2delay.eastmoney.com  (m:1+t:9, paginated)
  SZ  market prices -> qt.gtimg.cn               (batch, code scan)
  NAV/Estimated NAV  -> fundgz.1234567.com.cn     (fundgz API)

Code Strategy:
  SSE LOF: filter push2delay by code prefix 501xxx/502xxx
  SZ  LOF: hardcoded scan results from qt.gtimg.cn (160xxx-169xxx, 184xxx)
"""
import re, json, time, logging, threading, os
from datetime import datetime
from typing import Dict, List, Optional, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import Config

logger = logging.getLogger(__name__)

# ── SSE LOF code prefixes ────────────────────────
# 501xxx / 502xxx: Shanghai Stock Exchange LOF funds
# (confirmed from push2delay m:1+t:9 + name verification)
SSE_LOF_PREFIXES = ("501", "502")

# ── SZ LOF code prefixes ────────────────────────
# SZ LOF codes: 160xxx-169xxx, 184xxx (scanned from qt.gtimg.cn)
SZ_LOF_RANGES: List[range] = [
    range(160000, 170000),
    range(184000, 185000),
]


def _is_sze_lof(code: str) -> bool:
    """Check if code is a known SZ LOF (160xxx-169xxx, 184xxx)"""
    try:
        n = int(code)
        return any(n in r for r in SZ_LOF_RANGES)
    except (ValueError, TypeError):
        return False


def _is_sse_lof(code: str) -> bool:
    return code.startswith(SSE_LOF_PREFIXES)


def _is_lof_code(code: str) -> bool:
    return _is_sse_lof(code) or _is_sze_lof(code)


# ── Utility ──────────────────────────────────────

def _safe_float(val, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _jparse(text: str) -> dict:
    """Parse JSONP or JSON response from East Money API"""
    text = text.strip()
    m = re.search(r"^jQuery\s*\((.+)\)", text, re.DOTALL)
    if m:
        raw = m.group(1).strip().rstrip(";").rstrip(")")
        return json.loads(raw)
    return json.loads(text)


def _make_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=3, backoff_factor=1.0,
        status_forcelist={502, 503, 504, 429, 403},
        allowed_methods={"GET"},
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=60)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


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


# ── Tencent QT parser ────────────────────────────
# qt.gtimg.cn response: v_{prefix}{code}="51~Name~Code~Price~PrevClose~..."
# Field index (0-based): 0=type(51=fund), 1=name, 2=code,
#   3=price, 4=prev_close, 5=open, 32=update_time

def _parse_tencent_qt(text: str) -> Dict[str, Dict[str, Any]]:
    """Parse batch Tencent qt.gtimg.cn response"""
    result: Dict[str, Dict[str, Any]] = {}
    for line in text.strip().splitlines():
        if "~" not in line:
            continue
        # Extract code from key: v_sz166009 or v_sh501018
        key = line.split("=")[0].strip()
        if not key.startswith("v_"):
            continue
        suffix = key[2:]  # sz166009 or sh501018
        market_prefix = suffix[:2]  # sz or sh
        code = suffix[2:]

        parts = line.split("~")
        if len(parts) < 5:
            continue

        price = parts[3] if parts[3] != "-" else None
        prev  = parts[4] if parts[4] != "-" else None
        name  = parts[1]

        if price is None or price == "":
            continue

        try:
            price_f = float(price)
            prev_f  = float(prev) if prev else price_f
        except (ValueError, TypeError):
            continue

        # change_pct
        change_pct = round((price_f - prev_f) / prev_f * 100, 3) if prev_f else 0.0

        # Tencent qt.gtimg.cn fields:
        #   36 = volume (成交量，单位：手 / lots)
        #   57 = turnover (成交额，单位：万元 / 万元)
        volume_raw = parts[36] if len(parts) > 36 else ""
        turn_raw   = parts[57] if len(parts) > 57 else ""
        volume = int(_safe_float(volume_raw)) if volume_raw not in ("", "-") else 0
        # 成交额字段57是万元，需转为元
        amount = round(_safe_float(turn_raw, 0.0) * 10000, 2) if turn_raw not in ("", "-") else 0.0
        # 若成交额字段为空（停牌/极低成交），用 price * volume * 100 估算
        if amount == 0.0 and price_f > 0 and volume > 0:
            amount = round(price_f * volume * 100, 2)

        result[code] = {
            "code":        code,
            "name":        name,
            "price":       price_f,
            "prev_close":  prev_f,
            "change_pct":  change_pct,
            "volume":      volume,
            "amount":      amount,
        }

    return result


# ── SZ LOF code list (scanned from qt.gtimg.cn 160xxx-169xxx, 184xxx) ──
# Complete list: SZ LOF codes from Tencent scan
_SZ_LOF_CODES: List[str] = None


def _get_sz_lof_codes() -> List[str]:
    global _SZ_LOF_CODES
    if _SZ_LOF_CODES is not None:
        return _SZ_LOF_CODES

    # Try loading from cached JSON file
    cache_path = os.path.join(os.path.dirname(__file__), "sz_lof_codes.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            _SZ_LOF_CODES = list(data.keys())
            logger.info(f"Loaded {_SZ_LOF_CODES.__len__()} SZ LOF codes from cache")
            return _SZ_LOF_CODES
        except Exception as e:
            logger.warning(f"Failed to load SZ LOF cache: {e}")

    # Fallback: empty (will be populated from scan)
    _SZ_LOF_CODES = []
    return _SZ_LOF_CODES


# ── Main Fetcher ─────────────────────────────────

class LOFDataFetcher:

    def __init__(self):
        self._lock: threading.RLock = threading.RLock()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._last_fetch_time: Optional[datetime] = None
        self._fetch_error: Optional[str] = None
        self.__session: Optional[requests.Session] = None
        self._sz_lof_price_cache: Dict[str, Dict[str, Any]] = {}

    def _sess(self) -> requests.Session:
        if self.__session is None:
            self.__session = _make_session()
        return self.__session

    # ── public API ──────────────────────────────────

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return dict(self._cache)

    def get_one(self, code: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._cache.get(code.strip().zfill(6))

    @property
    def last_fetch_time(self) -> Optional[datetime]:
        with self._lock:
            return self._last_fetch_time

    @property
    def fetch_error(self) -> Optional[str]:
        with self._lock:
            return self._fetch_error

    def fetch_all(self) -> bool:
        """
        Fetch all LOF fund data:
          1. Get SSE LOF codes + prices from push2delay (m:1+t:9, paginated)
          2. Get SZ LOF codes from local scan results
          3. Get SZ LOF prices from Tencent qt.gtimg.cn (batch)
          4. Get NAV/Estimated NAV from fundgz API
          5. Calculate premium rate
        """
        try:
            logger.info("=== LOF data fetch started ===")
            t0 = time.time()

            # Step 1: Fetch SSE LOF codes + prices (push2delay, paginated)
            sse_funds = self._fetch_sse_lof_from_em()
            logger.info(f"SSE LOF funds: {len(sse_funds)}")

            # Step 2: SZ LOF prices from Tencent qt API
            sz_codes = _get_sz_lof_codes()
            sz_prices = self._fetch_sz_prices_from_qt(sz_codes)
            logger.info(f"SZ LOF prices fetched: {len(sz_prices)}")

            # Step 3: Combine (dedup by code)
            all_prices: Dict[str, Dict[str, Any]] = {}
            for code, fund in sse_funds.items():
                all_prices[code] = fund
            for code, price_data in sz_prices.items():
                if code not in all_prices:
                    all_prices[code] = price_data

            # Step 4: Fetch NAV in batch
            enriched = self._fetch_nav_batch(list(all_prices.values()))

            # Step 5: Calculate premium rate
            for fund in enriched.values():
                price = fund.get("price", 0)
                nav   = fund.get("nav")
                if price > 0 and nav and nav > 0:
                    prem = round((price - nav) / nav * 100, 3)
                    fund["premium_rate"]   = prem
                    fund["premium_status"] = (
                        "溢价" if prem > 0 else "折价" if prem < 0 else "平价"
                    )
                else:
                    fund["premium_rate"]   = None
                    fund["premium_status"] = None

            # Step 6: Update cache atomically
            with self._lock:
                self._cache = enriched
                self._last_fetch_time = datetime.now()
                self._fetch_error = None

            elapsed = time.time() - t0
            nav_ok = sum(1 for v in enriched.values() if v.get("nav") is not None)
            prem_ok = sum(1 for v in enriched.values() if v.get("premium_rate") is not None)
            logger.info(
                f"Done: {len(enriched)} LOFs, {nav_ok} with NAV, "
                f"{prem_ok} with premium, {elapsed:.1f}s"
            )
            logger.info("=== LOF data fetch complete ===")
            return True

        except Exception as e:
            logger.exception(f"Fetch failed: {e}")
            with self._lock:
                self._fetch_error = str(e)
            return False

    # ── private: SSE ───────────────────────────────

    def _fetch_sse_lof_from_em(self) -> Dict[str, Dict[str, Any]]:
        """
        Fetch all SSE (Shanghai) exchange-listed fund prices from push2delay.
        Uses fs=m:1+t:9 (场内基金), paginates through all pages,
        then filters to LOF codes (501xxx, 502xxx).
        """
        result: Dict[str, Dict[str, Any]] = {}
        seen: set = set()

        for pn in range(1, 25):  # max ~14 pages needed for 1274 items
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
                    resp = self._sess().get(
                        url, headers=_EM_HEADERS, timeout=Config.REQUEST_TIMEOUT
                    )
                    break
                except Exception as ex:
                    logger.warning(f"SSE pn={pn} attempt {attempt+1} failed: {ex}")
                    if attempt < 2:
                        time.sleep(2 ** attempt)

            if resp is None or resp.status_code != 200:
                break

            resp.encoding = "utf-8"
            try:
                data = _jparse(resp.text)
            except Exception as ex:
                logger.warning(f"SSE pn={pn} parse failed: {ex}")
                break

            items = (data.get("data") or {}) or {}
            diff  = items.get("diff", [])
            total = items.get("total", 0)

            if not diff:
                break

            for item in diff:
                code = str(item.get("f12", "")).strip()
                if not re.match(r"^\d{6}$", code) or code in seen:
                    continue
                seen.add(code)

                # Filter: SSE LOF codes (501xxx, 502xxx)
                if not _is_sse_lof(code):
                    continue

                price_raw = item.get("f2")
                if price_raw == "-" or price_raw is None:
                    continue
                price = _safe_float(price_raw)
                if price <= 0:
                    continue

                result[code] = {
                    "code":       code.zfill(6),
                    "name":       str(item.get("f14", "")).strip(),
                    "price":      price,
                    "change_pct": round(_safe_float(item.get("f3"), 0), 3),
                    "volume":     int(_safe_float(item.get("f5"), 0)),
                    "amount":     round(_safe_float(item.get("f20"), 0), 2),
                }

            if len(seen) >= total:
                break
            time.sleep(0.2)

        return result

    # ── private: SZ ────────────────────────────────

    def _fetch_sz_prices_from_qt(self, codes: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Fetch SZ LOF prices from Tencent qt.gtimg.cn in batches.
        Each batch: up to 100 codes, comma-separated.
        """
        result: Dict[str, Dict[str, Any]] = {}
        BATCH = 100

        for i in range(0, len(codes), BATCH):
            batch = codes[i:i + BATCH]
            # Prefix with "sz" for Tencent
            qt_codes = ",".join(f"sz{c}" for c in batch)
            url = f"https://qt.gtimg.cn/q={qt_codes}"

            try:
                resp = self._sess().get(url, headers=_TT_HEADERS, timeout=Config.REQUEST_TIMEOUT)
                # 腾讯 qt.gtimg.cn 返回 GBK 编码，必须用 apparent_encoding 或直接 gbk
                resp.encoding = resp.apparent_encoding or "gbk"
                parsed = _parse_tencent_qt(resp.text)
                result.update(parsed)
            except Exception as ex:
                logger.warning(f"SZ qt batch {i//BATCH+1} failed: {ex}")

            time.sleep(0.1)

        return result

    # ── private: NAV ───────────────────────────────

    def _fetch_nav_batch(self, funds: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        Batch fetch NAV/Estimated NAV from fundgz.1234567.com.cn.
        Max 30 concurrent threads.
        """
        result: Dict[str, Dict[str, Any]] = {}
        sem = threading.Semaphore(30)
        total = len(funds)

        def fetch_one(fund: Dict[str, Any]) -> None:
            code = fund["code"]
            with sem:
                try:
                    nav_info = self._fetch_single_nav(code)
                    result[code] = {**fund, **nav_info}
                except Exception as ex:
                    logger.debug(f"NAV fetch failed {code}: {ex}")
                    result[code] = {**fund, "nav": None, "nav_date": None}

        threads: List[threading.Thread] = []
        for i, fund in enumerate(funds):
            t = threading.Thread(target=fetch_one, args=(fund,))
            t.start()
            threads.append(t)

            if len(threads) >= 100:
                for tt in threads:
                    tt.join()
                threads = []
                logger.info(f"NAV progress: {min(i + 1, total)}/{total}")

        for tt in threads:
            tt.join()

        logger.info(f"NAV batch complete: {total}/{total}")
        return result

    def _fetch_single_nav(self, code: str) -> Dict[str, Any]:
        """
        Fetch NAV/Estimated NAV from 天天基金网 fundgz API.
        URL: https://fundgz.1234567.com.cn/js/{code}.js
        Returns: { nav, prev_nav, nav_date, is_formal_nav }
        """
        url  = Config.FUND_NAV_URL.format(code=code)
        resp = self._sess().get(url, headers=_FUNDGZ_HEADERS, timeout=Config.REQUEST_TIMEOUT)
        resp.encoding = "utf-8"
        text = resp.text.strip()

        m = re.search(r"\((.+)\)\s*;?\s*$", text, re.DOTALL)
        if not m:
            return {"nav": None, "nav_date": None, "is_formal_nav": False}

        try:
            data = json.loads(m.group(1).strip().rstrip(";").rstrip(")"))
        except json.JSONDecodeError:
            return {"nav": None, "nav_date": None, "is_formal_nav": False}

        nav_str  = data.get("dwjz")   # current unit NAV (estimated during trading)
        prev_str = data.get("jjjz")    # previous trading day NAV
        gztime   = data.get("gztime") # estimated NAV update time

        if not nav_str:
            return {"nav": None, "nav_date": None, "is_formal_nav": False}

        nav  = _safe_float(nav_str)
        prev = _safe_float(prev_str, nav)

        gztime_str = str(gztime) if gztime else ""
        is_formal  = "15:00" in gztime_str or "15:30" in gztime_str

        return {
            "nav":           round(nav,  4),
            "prev_nav":      round(prev, 4),
            "nav_date":      gztime_str or None,
            "is_formal_nav": is_formal,
        }


# ── Singleton ─────────────────────────────────────
_instance: Optional[LOFDataFetcher] = None
_inst_lock = threading.Lock()


def get_fetcher() -> LOFDataFetcher:
    global _instance
    if _instance is None:
        with _inst_lock:
            if _instance is None:
                _instance = LOFDataFetcher()
    return _instance
