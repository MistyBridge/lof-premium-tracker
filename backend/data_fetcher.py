# -*- coding: utf-8 -*-
"""
LOF Fund Data Fetcher — 缓存管理 + 数据源编排

数据抓取委托给 datasource 包（主: AkShare, 备: Legacy），
本模块负责缓存管理、溢价率计算、费率加载和历史数据降级。
"""
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

import requests

from config import Config
from history_db import get_history_db
from fee_fetcher import fetch_fees_batch, load_fee_cache, save_fee_cache
from datasource.manager import get_datasource_manager

logger = logging.getLogger(__name__)


class LOFDataFetcher:
    """LOF 基金数据抓取器 — 缓存管理 + 数据编排"""

    def __init__(self):
        self._lock: threading.RLock = threading.RLock()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._last_fetch_time: Optional[datetime] = None
        self._fetch_error: Optional[str] = None
        self._ds = get_datasource_manager()
        self._http: Optional[requests.Session] = None

    def _sess(self) -> requests.Session:
        if self._http is None:
            self._http = requests.Session()
            self._http.trust_env = False
        return self._http

    # ── Public API ──────────────────────────────────

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

    # ── History Loading ─────────────────────────────

    def load_from_history(self, history_db) -> bool:
        """从 history_db 加载最近一天数据作为缓存初始化"""
        try:
            dates = history_db.get_available_dates()
            if not dates:
                logger.info("No history data available for fallback")
                return False

            latest_date = dates[0]
            logger.info("Loading fallback data from history date: %s", latest_date)

            name_map = {}
            cache_path = os.path.join(os.path.dirname(__file__), "sz_lof_codes.json")
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        name_map = json.load(f)
                except Exception:
                    pass

            rows = history_db.get_snapshot_by_date(latest_date)
            if not rows:
                logger.info("No data found in history for latest date")
                return False

            cache = {}
            for r in rows:
                code = r["code"]
                premium = r["premium_rate"]
                price = r["price"] or 0
                nav = r["nav"] or 0
                db_amount = r["amount"]
                amount = db_amount if db_amount and db_amount > 0 else None
                db_name = r.get("name", "")
                name = db_name or name_map.get(code, code)

                premium_status = None
                if premium is not None:
                    premium_status = "溢价" if premium > 0 else "折价" if premium < 0 else "平价"

                cache[code] = {
                    "code": code, "name": name,
                    "price": price, "nav": nav,
                    "premium_rate": premium, "premium_status": premium_status,
                    "amount": amount, "volume": None, "change_pct": None,
                    "nav_date": latest_date, "is_formal_nav": True,
                    "_from_history": True, "_history_date": latest_date,
                }

            with self._lock:
                if not self._cache:
                    self._cache = cache
                    self._last_fetch_time = datetime.now(timezone.utc)
                    self._fetch_error = None

            logger.info("Loaded %d funds from history (%s)", len(cache), latest_date)
            return True
        except Exception as e:
            logger.warning("Failed to load from history: %s", e)
            return False

    def load_from_seed(self, seed_path: str = None) -> bool:
        """从 history_seed.json 加载预置数据到缓存和 PostgreSQL"""
        if seed_path is None:
            seed_path = os.path.join(os.path.dirname(__file__), "history_seed.json")
        if not os.path.exists(seed_path):
            logger.info("Seed file not found: %s", seed_path)
            return False

        try:
            with open(seed_path, "r", encoding="utf-8") as f:
                seed_data = json.load(f)
        except Exception as e:
            logger.warning("Failed to load seed file: %s", e)
            return False

        hdb = get_history_db()
        dates = sorted(seed_data.keys(), reverse=True)
        total_rows = 0
        for date_str in dates:
            date_funds = seed_data[date_str]
            funds_dict = {}
            for code, fund_data in date_funds.items():
                premium = fund_data.get("premium_rate")
                if premium is None:
                    continue
                funds_dict[code] = {
                    "code": code, "name": fund_data.get("name", code),
                    "price": fund_data.get("price", 0), "nav": fund_data.get("nav"),
                    "premium_rate": premium,
                    "premium_status": "溢价" if premium > 0 else "折价" if premium < 0 else "平价",
                    "amount": fund_data.get("amount", 0), "volume": 0,
                    "change_pct": fund_data.get("change_pct", 0),
                    "nav_date": date_str, "is_formal_nav": True,
                }
                total_rows += 1
            hdb.save_snapshot(funds_dict, date=date_str)

        logger.info("Seed data loaded: %d dates, %d records written", len(dates), total_rows)
        return self.load_from_history(hdb)

    # ── Main Fetch Orchestration ────────────────────

    def fetch_all(self) -> bool:
        """
        数据抓取主流程（使用 DataSourceManager 主备切换）：
          1. 价格行情 → datasource (AkShare → Legacy)
          2. NAV 净值  → datasource (AkShare → Legacy, 逐基金降级)
          3. 溢价率计算
          4. 申购状态  → lsjz API
          5. 费率数据  → fee_fetcher (缓存 + 爬虫)
        """
        try:
            logger.info("=== LOF data fetch started ===")
            t0 = time.time()

            # Step 1: 价格行情 (整体降级: AkShare → Legacy)
            all_prices = self._ds.fetch_all_prices()
            logger.info("Prices fetched: %d funds", len(all_prices))

            if not all_prices:
                logger.warning("No prices from any data source, aborting fetch")
                return False

            # Step 2: NAV 净值 (逐基金降级)
            funds_list = list(all_prices.values())
            enriched = self._ds.fetch_nav_batch(funds_list)
            logger.info("NAV enriched: %d funds", len(enriched))

            # Step 3: 溢价率计算
            for fund in enriched.values():
                price = fund.get("price", 0)
                nav = fund.get("nav")
                if price > 0 and nav and nav > 0:
                    prem = round((price - nav) / nav * 100, 3)
                    fund["premium_rate"] = prem
                    fund["premium_status"] = "溢价" if prem > 0 else "折价" if prem < 0 else "平价"
                else:
                    code = fund.get("code", "")
                    with self._lock:
                        cached = self._cache.get(code)
                    if cached and cached.get("nav") and cached.get("premium_rate") is not None:
                        fund["nav"] = cached["nav"]
                        fund["nav_date"] = cached.get("nav_date")
                        fund["is_formal_nav"] = cached.get("is_formal_nav", True)
                        fund["premium_rate"] = cached["premium_rate"]
                        fund["premium_status"] = cached["premium_status"]
                        old_nav = cached["nav"]
                        if price > 0 and old_nav > 0:
                            new_prem = round((price - old_nav) / old_nav * 100, 3)
                            fund["premium_rate"] = new_prem
                            fund["premium_status"] = "溢价" if new_prem > 0 else "折价" if new_prem < 0 else "平价"
                    else:
                        fund["premium_rate"] = None
                        fund["premium_status"] = None

            # Step 4: 申购状态
            purchase_map = self._fetch_purchase_status(list(enriched.keys()))
            for code, can_purchase in purchase_map.items():
                if code in enriched:
                    enriched[code]["can_purchase"] = can_purchase
            for code, fund in enriched.items():
                if "can_purchase" not in fund:
                    fund["can_purchase"] = None

            # Step 5: 费率数据
            fee_cache = load_fee_cache()
            cache_is_fresh = False
            if fee_cache:
                cached_count = len(set(fee_cache.keys()) & set(enriched.keys()))
                if cached_count >= len(enriched) * 0.8:
                    cache_is_fresh = True
                    logger.info("Using fee cache: %d/%d funds", cached_count, len(enriched))

            if not cache_is_fresh:
                try:
                    fee_data = fetch_fees_batch(list(enriched.keys()), concurrency=10)
                    fee_cache.update(fee_data)
                    save_fee_cache(fee_cache)
                except Exception as ex:
                    logger.warning("Fee batch fetch failed: %s", ex)

            for code, fund in enriched.items():
                fee = fee_cache.get(code, {})
                fund["purchase_fee_rate"] = fee.get("purchase_fee_rate")
                fund["redemption_fee_rate"] = fee.get("redemption_fee_rate")
                fund["purchase_limit"] = fee.get("purchase_limit")

            # 更新缓存
            with self._lock:
                self._cache = enriched
                self._last_fetch_time = datetime.now(timezone.utc)
                self._fetch_error = None

            elapsed = time.time() - t0
            nav_ok = sum(1 for v in enriched.values() if v.get("nav") is not None)
            prem_ok = sum(1 for v in enriched.values() if v.get("premium_rate") is not None)
            logger.info("Done: %d LOFs, %d NAV, %d premium, %.1fs",
                        len(enriched), nav_ok, prem_ok, elapsed)
            logger.info("=== LOF data fetch complete ===")
            return True

        except Exception as e:
            logger.exception("Fetch failed: %s", e)
            with self._lock:
                self._fetch_error = str(e)
            return False

    # ── Purchase Status (lsjz API) ──────────────────

    def _fetch_purchase_status(self, codes: List[str]) -> Dict[str, bool]:
        """批量查询申购状态"""
        result: Dict[str, bool] = {}
        lock = threading.Lock()
        sem = threading.Semaphore(15)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://fundf10.eastmoney.com/",
        }

        def fetch_one(code: str) -> None:
            with sem:
                try:
                    url = f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex=1&pageSize=1"
                    resp = self._sess().get(url, headers=headers, timeout=10)
                    resp.encoding = "utf-8"
                    data = resp.json()
                    if data.get("ErrCode") == 0:
                        lsjz_list = (data.get("Data") or {}).get("LSJZList") or []
                        if lsjz_list:
                            sgzt = lsjz_list[0].get("SGZT", "")
                            can = "开放" in sgzt or "限制大额" in sgzt
                            with lock:
                                result[code] = can
                except Exception:
                    pass

        threads: List[threading.Thread] = []
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

        logger.info("Purchase status: %d/%d", len(result), len(codes))
        return result


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
