# -*- coding: utf-8 -*-
"""
热门基金曲线图数据预渲染缓存

每5分钟自动刷新：
  - Top5 溢价率最高基金
  - Top5 折价率最高基金
  预计算 7日/30日/365日 三个时间范围的图表数据

过期策略：
  - 每日0点全部缓存自动过期
  - 数据变动（价格/净值/溢价率变更）时自动重渲染
  - 不再热门的基金自动清除缓存
"""
import logging
import threading
from datetime import datetime
from typing import Dict, Optional

from history_db import filter_and_forward_fill

logger = logging.getLogger(__name__)


class ChartCache:
    """热门基金曲线图数据缓存（线程安全）"""

    def __init__(self):
        self._cache: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._last_date: Optional[str] = None

    def refresh(self, hdb, all_funds: dict):
        """
        每5分钟调用一次，刷新热门基金缓存。
        hdb: HistoryDB 实例
        all_funds: {code: {premium_rate, price, nav, name, ...}, ...}
        """
        today = datetime.now().strftime("%Y-%m-%d")

        # 每日过期：新的一天清空所有旧缓存
        if self._last_date != today:
            with self._lock:
                self._cache.clear()
                self._last_date = today
            logger.info("ChartCache: daily reset, all cached charts cleared")

        # 找到 Top5 溢价 + Top5 折价
        valid = [
            (code, fund) for code, fund in all_funds.items()
            if fund.get("premium_rate") is not None
        ]
        if not valid:
            return

        premium_top = sorted(valid, key=lambda x: x[1]["premium_rate"], reverse=True)[:5]
        discount_top = sorted(valid, key=lambda x: x[1]["premium_rate"])[:5]

        target_codes = set()
        for code, _ in premium_top + discount_top:
            target_codes.add(code)

        for code in target_codes:
            fund = all_funds.get(code)
            if not fund:
                continue

            # 数据指纹：判断是否需要重新渲染
            data_hash = self._make_hash(fund)

            with self._lock:
                cached = self._cache.get(code)

            if cached and cached.get("data_hash") == data_hash:
                continue  # 数据未变，保留缓存

            # 预渲染三个时间范围的图表数据
            charts = {}
            for days in [7, 30, 365]:
                raw = hdb.get_kline_history(code=code, days=days)
                charts[str(days)] = filter_and_forward_fill(raw)

            entry = {
                "code": code,
                "name": fund.get("name"),
                "data_hash": data_hash,
                "updated_at": datetime.now().isoformat(),
                "charts": charts,
            }

            with self._lock:
                self._cache[code] = entry

            logger.debug("ChartCache: updated %s %s", code, fund.get("name"))

        # 清理不再是热门基金的缓存
        with self._lock:
            stale = [c for c in self._cache if c not in target_codes]
            for c in stale:
                del self._cache[c]

        logger.info("ChartCache: refreshed %d hot fund charts (top5 premium + top5 discount)",
                     len(target_codes))

    def get(self, code: str) -> Optional[dict]:
        """获取缓存的曲线图数据，返回 None 表示未缓存"""
        with self._lock:
            return self._cache.get(code)

    def invalidate(self, code: str):
        """手动使某只基金缓存失效"""
        with self._lock:
            if code in self._cache:
                del self._cache[code]
                logger.debug("ChartCache: invalidated %s", code)

    def get_stats(self) -> dict:
        """获取缓存统计信息"""
        with self._lock:
            return {
                "cached_count": len(self._cache),
                "cached_codes": list(self._cache.keys()),
                "last_date": self._last_date,
            }

    @staticmethod
    def _make_hash(fund: dict) -> str:
        """生成数据指纹"""
        return f"{fund.get('premium_rate')}|{fund.get('price')}|{fund.get('nav')}"


# ── Singleton ─────────────────────────────────────
_instance: Optional[ChartCache] = None
_inst_lock = threading.Lock()


def get_chart_cache() -> ChartCache:
    global _instance
    if _instance is None:
        with _inst_lock:
            if _instance is None:
                _instance = ChartCache()
    return _instance
