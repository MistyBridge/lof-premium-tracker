"""
监控指标 + 告警（12 个指标 + webhook 推送 + 1 小时冷却）
"""
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger("app")


@dataclass
class Metrics:
    """全局监控指标单例"""

    # 采集状态: {source: {success, fail, business_error, last_ok, last_fail, duration_ms}}
    fetch_status: dict = field(default_factory=dict)
    api_requests: int = 0
    db_query_durations: list = field(default_factory=list)  # 近 100 次
    cache_hits: int = 0
    cache_misses: int = 0

    def record_fetch(self, source: str, success: bool, duration_ms: float,
                     business_error: bool = False) -> None:
        """记录采集结果"""
        if source not in self.fetch_status:
            self.fetch_status[source] = {
                "success": 0, "fail": 0, "business_error": 0,
                "last_ok": None, "last_fail": None, "duration_ms": 0,
            }
        s = self.fetch_status[source]
        now = datetime.now(timezone.utc).isoformat()
        if success:
            s["success"] += 1
            s["last_ok"] = now
        else:
            s["fail"] += 1
            s["last_fail"] = now
        if business_error:
            s["business_error"] += 1
        s["duration_ms"] = duration_ms

    def record_api_request(self) -> None:
        self.api_requests += 1

    def record_db_query(self, duration_ms: float) -> None:
        self.db_query_durations.append(duration_ms)
        if len(self.db_query_durations) > 100:
            self.db_query_durations = self.db_query_durations[-100:]

    def record_cache_hit(self) -> None:
        self.cache_hits += 1

    def record_cache_miss(self) -> None:
        self.cache_misses += 1

    def get_metrics(self) -> dict:
        """导出所有指标"""
        avg_db = (
            sum(self.db_query_durations) / len(self.db_query_durations)
            if self.db_query_durations else 0
        )
        total_cache = self.cache_hits + self.cache_misses
        cache_rate = self.cache_hits / total_cache * 100 if total_cache > 0 else 0
        return {
            "fetch_status": self.fetch_status,
            "api_requests": self.api_requests,
            "db_query_avg_ms": round(avg_db, 2),
            "cache_hit_rate": round(cache_rate, 1),
        }


# 全局单例
metrics = Metrics()


# ── 告警 ────────────────────────────────────────────────────

_alert_cooldown: dict[str, datetime] = {}


async def alert(title: str, message: str, level: str = "P1",
                webhook_url: Optional[str] = None) -> None:
    """
    发送告警到企业微信 webhook。
    同一 title+level 一小时内不重复发送。
    """
    if not webhook_url:
        return

    cooldown_key = f"{title}:{level}"
    now = datetime.now(timezone.utc)
    if cooldown_key in _alert_cooldown:
        if (now - _alert_cooldown[cooldown_key]).total_seconds() < 3600:
            return

    _alert_cooldown[cooldown_key] = now

    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                webhook_url,
                json={
                    "msgtype": "markdown",
                    "markdown": {
                        "content": (
                            f"## [{level}] {title}\n"
                            f"{message}\n"
                            f"时间: {now.strftime('%Y-%m-%d %H:%M:%S')}"
                        ),
                    },
                },
                timeout=10,
            )
    except Exception:
        logger.error("告警发送失败: %s", title)


# ── 自愈检查工具 ─────────────────────────────────────────────


def get_disk_usage_pct(path: str = "/") -> float:
    """获取磁盘使用率百分比"""
    try:
        usage = shutil.disk_usage(path)
        return usage.used / usage.total * 100
    except Exception:
        return 0.0
