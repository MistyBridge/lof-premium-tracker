"""
公共工具函数 — 北京时间统一入口
所有日期/时间计算统一使用北京时间（UTC+8），避免 UTC 与本地时间不一致导致的缓存 key 错误。
日志/metrics/时间戳仍使用 UTC，不在本模块范围内。
"""
from datetime import datetime, timezone, timedelta

BEIJING_TZ = timezone(timedelta(hours=8))


def beijing_now() -> datetime:
    """获取当前北京时间（带时区信息）"""
    return datetime.now(BEIJING_TZ)


def beijing_today_str(fmt: str = "%Y%m%d") -> str:
    """获取北京时间的今天日期字符串，默认格式 YYYYMMDD"""
    return beijing_now().strftime(fmt)


def beijing_today_date():
    """获取北京时间的今天 date 对象"""
    return beijing_now().date()
