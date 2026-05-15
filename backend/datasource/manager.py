# -*- coding: utf-8 -*-
"""
数据源管理器 — 主备切换 + 逐基金降级 + 熔断机制
"""
import logging
import time
from typing import Any, Dict, List, Optional

from datasource.base import LOFDataSource

logger = logging.getLogger(__name__)

FAILURE_THRESHOLD = 3        # 连续失败次数阈值
COOLDOWN_SECONDS = 300       # 熔断冷却时间（5分钟）


class DataSourceManager:
    """
    数据源管理器
    - 日常使用主数据源 (AkShare)
    - 连续失败3次 → 触发熔断，跳过主源直接用后备源
    - 熔断冷却5分钟后自动重试主源
    - 价格数据整体降级 / NAV逐基金降级
    """

    def __init__(self, primary: LOFDataSource, fallback: Optional[LOFDataSource] = None):
        self.primary = primary
        self.fallback = fallback
        self._failure_count = 0
        self._circuit_open_until = 0.0
        logger.info("DataSourceManager: primary=%s, fallback=%s",
                     primary.name, fallback.name if fallback else "None")

    def _should_try_primary(self) -> bool:
        """检查是否应该尝试主源（熔断检查）"""
        if self.primary is None:
            return False
        if self._failure_count >= FAILURE_THRESHOLD:
            now = time.time()
            if now < self._circuit_open_until:
                return False
            # 冷却时间到，重试
            logger.info("Circuit breaker cool-down ended, retrying primary (%s)", self.primary.name)
            self._failure_count = 0
        return True

    def _record_success(self):
        if self._failure_count > 0:
            logger.info("Primary (%s) recovered, resetting failure count", self.primary.name)
        self._failure_count = 0

    def _record_failure(self):
        self._failure_count += 1
        if self._failure_count >= FAILURE_THRESHOLD:
            self._circuit_open_until = time.time() + COOLDOWN_SECONDS
            logger.warning(
                "Primary (%s) failed %d times, circuit breaker open for %ds",
                self.primary.name, self._failure_count, COOLDOWN_SECONDS
            )

    # ── Prices (整体降级 + 熔断) ────────────────────

    def fetch_all_prices(self) -> Dict[str, dict]:
        """价格行情：主源失败则整体降级到后备源，连续失败触发熔断"""
        if self._should_try_primary():
            try:
                result = self.primary.fetch_all_prices()
                if result:
                    self._record_success()
                    logger.info("Prices from primary (%s): %d funds", self.primary.name, len(result))
                    return result
                logger.warning("Primary (%s) returned empty prices, falling back", self.primary.name)
                self._record_failure()
            except Exception as e:
                logger.warning("Primary (%s) prices failed: %s, falling back", self.primary.name, e)
                self._record_failure()
        else:
            logger.info("Circuit breaker open, skipping primary (%s) for prices", self.primary.name)

        if self.fallback:
            try:
                result = self.fallback.fetch_all_prices()
                logger.info("Prices from fallback (%s): %d funds", self.fallback.name, len(result))
                return result
            except Exception as e:
                logger.error("Fallback (%s) prices also failed: %s", self.fallback.name, e)

        return {}

    # ── NAV (逐基金降级 + 熔断) ──────────────────────

    def fetch_nav_batch(self, funds: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        NAV 批量获取：先调主源，对缺失 NAV 的基金逐只调用后备源补缺。
        """
        if not funds:
            return {}

        # Step 1: Primary (with circuit breaker)
        result = {}
        if self._should_try_primary():
            try:
                result = self.primary.fetch_nav_batch(funds)
                nav_ok = sum(1 for v in result.values() if v.get("nav") is not None)
                logger.info("NAV from primary (%s): %d/%d", self.primary.name, nav_ok, len(funds))
                if nav_ok > 0:
                    self._record_success()
                else:
                    self._record_failure()
            except Exception as e:
                logger.warning("Primary (%s) NAV batch failed: %s", self.primary.name, e)
                self._record_failure()

        # Step 2: Fallback for missing funds
        if self.fallback is not None:
            missing = [
                f for f in funds
                if f["code"] not in result or result[f["code"]].get("nav") is None
            ]
            if missing:
                logger.info("NAV fallback: %d funds missing, trying %s...",
                            len(missing), self.fallback.name)
                try:
                    fb_result = self.fallback.fetch_nav_batch(missing)
                    for code, data in fb_result.items():
                        if code not in result or result[code].get("nav") is None:
                            result[code] = data
                    nav_ok = sum(1 for v in result.values() if v.get("nav") is not None)
                    logger.info("NAV after fallback: %d/%d with NAV", nav_ok, len(funds))
                except Exception as e:
                    logger.warning("Fallback (%s) NAV also failed: %s", self.fallback.name, e)

        return result

    def fetch_single_nav(self, code: str) -> Dict[str, Any]:
        """单只基金 NAV：主源失败则用后备源"""
        if self._should_try_primary():
            try:
                result = self.primary.fetch_single_nav(code)
                if result.get("nav") is not None:
                    return result
            except Exception as e:
                logger.debug("Primary (%s) single NAV failed for %s: %s", self.primary.name, code, e)

        if self.fallback:
            try:
                return self.fallback.fetch_single_nav(code)
            except Exception as e:
                logger.debug("Fallback (%s) single NAV failed for %s: %s", self.fallback.name, code, e)

        return {"nav": None, "nav_date": None, "prev_nav": None, "is_formal_nav": False}

    # ── K-line History (整体降级 + 熔断) ─────────────

    def fetch_kline(self, code: str, start_date: str, end_date: str) -> Dict[str, dict]:
        """K线数据：主源失败则降级"""
        if self._should_try_primary():
            try:
                result = self.primary.fetch_kline(code, start_date, end_date)
                if result:
                    return result
            except Exception as e:
                logger.debug("Primary (%s) kline failed for %s: %s", self.primary.name, code, e)

        if self.fallback:
            try:
                return self.fallback.fetch_kline(code, start_date, end_date)
            except Exception as e:
                logger.debug("Fallback (%s) kline failed for %s: %s", self.fallback.name, code, e)

        return {}

    # ── NAV History (整体降级 + 熔断) ────────────────

    def fetch_nav_history(self, code: str, start_date: str, end_date: str) -> Dict[str, float]:
        """历史净值：主源失败则降级"""
        if self._should_try_primary():
            try:
                result = self.primary.fetch_nav_history(code, start_date, end_date)
                if result:
                    return result
            except Exception as e:
                logger.debug("Primary (%s) nav_history failed for %s: %s", self.primary.name, code, e)

        if self.fallback:
            try:
                return self.fallback.fetch_nav_history(code, start_date, end_date)
            except Exception as e:
                logger.debug("Fallback (%s) nav_history failed for %s: %s", self.fallback.name, code, e)

        return {}

    # ── Health ───────────────────────────────────────

    def health_check(self) -> Dict[str, Any]:
        return {
            "primary_ok": self.primary.health_check() if self.primary else False,
            "fallback_ok": self.fallback.health_check() if self.fallback else False,
            "circuit_breaker": {
                "failure_count": self._failure_count,
                "threshold": FAILURE_THRESHOLD,
                "open": self._failure_count >= FAILURE_THRESHOLD and time.time() < self._circuit_open_until,
                "cooldown_remaining": max(0, int(self._circuit_open_until - time.time())),
            },
        }


# ── Singleton ─────────────────────────────────────
_instance: Optional[DataSourceManager] = None


def get_datasource_manager() -> DataSourceManager:
    """获取全局数据源管理器单例（主=AkShare, 备=Legacy）"""
    global _instance
    if _instance is None:
        from datasource.ak_share import AkShareSource
        from datasource.legacy import LegacySource
        _instance = DataSourceManager(
            primary=AkShareSource(),
            fallback=LegacySource(),
        )
    return _instance
