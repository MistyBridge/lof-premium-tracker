"""
数据采集模块 — M3 采集层

依赖: mq, cache, constants, httpx
被依赖: scheduler（定时触发）
对外接口:
  - fetch_realtime(): 实时行情采集 → 发布 realtime 事件
  - fetch_fundamental(): 净值+申赎采集 → 发布 nav 事件
  - fetch_historical(): 日线K线采集 → 发布 kline 事件
  - fetch_info(): 持仓+基础信息采集 → 发布 info 事件
"""
import re
import logging
from typing import Optional, Any

logger = logging.getLogger("app")


# ── 通用工具函数 ─────────────────────────────────────────────

def clean_code(code: Any) -> str:
    """
    标准化基金代码: 去空格, 全角转半角, 补零到6位
    """
    if code is None:
        return ""
    # 全角转半角
    code = str(code).translate(str.maketrans('０１２３４５６７８９', '0123456789'))
    code = code.strip()
    # 提取数字部分
    match = re.search(r'\d+', code)
    if match:
        return match.group().zfill(6)
    return code.zfill(6)


def safe_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    """
    安全浮点转换, 处理 None/""/"-"/"None"/NaN
    """
    if val is None or val == '' or val == '-' or val == 'None':
        return default
    try:
        result = float(val)
        # NaN 检测
        if result != result:
            return default
        # Infinity 检测
        if result == float('inf') or result == float('-inf'):
            return default
        return result
    except (ValueError, TypeError):
        return default


def safe_int(val: Any, default: Optional[int] = None) -> Optional[int]:
    """安全整数转换"""
    if val is None or val == '' or val == '-' or val == 'None':
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


# ── 统一导出 ─────────────────────────────────────────────────

from .realtime import fetch_realtime
from .fundamental import fetch_fundamental
from .historical import fetch_historical
from .info import fetch_info

__all__ = [
    "clean_code",
    "safe_float",
    "safe_int",
    "fetch_realtime",
    "fetch_fundamental",
    "fetch_historical",
    "fetch_info",
]