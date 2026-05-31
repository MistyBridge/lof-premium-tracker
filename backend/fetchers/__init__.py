# -*- coding: utf-8 -*-
"""
数据采集层 - 统一导出 + 通用工具
"""
import re
import asyncio
import logging
from typing import Optional, Any, Callable, TypeVar
from functools import wraps

logger = logging.getLogger(__name__)

# ============================================================
# 通用工具函数
# ============================================================

def normalize_code(code: str) -> str:
    """
    标准化基金代码：补零到6位，去空格，全角转半角
    
    Args:
        code: 原始代码字符串
        
    Returns:
        标准化后的6位代码
    """
    if not code:
        return ""
    # 全角转半角
    code = code.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
    # 去空格
    code = code.strip()
    # 补零到6位
    return code.zfill(6)


def safe_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    """
    安全浮点转换
    
    Args:
        val: 待转换的值
        default: 转换失败时的默认值
        
    Returns:
        转换后的浮点数或默认值
    """
    if val is None or val == '' or val == '-' or val == 'None':
        return default
    try:
        result = float(val)
        # 检查NaN
        if result != result:  # NaN != NaN
            return default
        return result
    except (ValueError, TypeError):
        return default


def safe_int(val: Any, default: Optional[int] = None) -> Optional[int]:
    """
    安全整数转换
    """
    if val is None or val == '' or val == '-' or val == 'None':
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


T = TypeVar('T')

async def retry_fetch(
    func: Callable[..., T],
    *args,
    max_retries: int = 3,
    backoff_base: float = 1.0,
    **kwargs
) -> Optional[T]:
    """
    通用重试装饰器（指数退避）
    
    Args:
        func: 要重试的异步函数
        max_retries: 最大重试次数
        backoff_base: 退避基数（秒）
        
    Returns:
        函数结果或None（全部失败）
    """
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except asyncio.TimeoutError as e:
            last_exception = e
            if attempt < max_retries:
                wait_time = backoff_base * (2 ** attempt)
                logger.warning(
                    f"[RETRY] Timeout on attempt {attempt + 1}/{max_retries + 1}, "
                    f"retrying in {wait_time}s..."
                )
                await asyncio.sleep(wait_time)
        except ConnectionError as e:
            last_exception = e
            if attempt < max_retries:
                wait_time = backoff_base * (2 ** attempt)
                logger.warning(
                    f"[RETRY] Connection error on attempt {attempt + 1}/{max_retries + 1}, "
                    f"retrying in {wait_time}s..."
                )
                await asyncio.sleep(wait_time)
        except Exception as e:
            # 业务错误不重试
            logger.error(f"[FETCH] Non-retryable error: {e}")
            return None
    
    logger.error(f"[FETCH] All {max_retries + 1} attempts failed: {last_exception}")
    return None


# ============================================================
# 兼容导入（如果柯1的模块还没写）
# ============================================================

try:
    from backend.mq import publish_event
except ImportError:
    logger.warning("[FETCHERS] mq module not available, events won't be published")
    async def publish_event(event_type: str, payload: dict) -> bool:
        """降级：不发布事件"""
        return False

try:
    from backend.metrics import record_fetch
except ImportError:
    logger.warning("[FETCHERS] metrics module not available, metrics won't be recorded")
    async def record_fetch(source: str, success: bool, count: int = 0, business_error: bool = False) -> None:
        """降级：不记录metrics"""
        pass

try:
    from backend.trade_calendar import is_trading_day
except ImportError:
    logger.warning("[FETCHERS] trade_calendar module not available")
    from datetime import datetime
    def is_trading_day(date=None) -> bool:
        """降级：假设工作日都是交易日"""
        if date is None:
            date = datetime.now()
        return date.weekday() < 5


# ============================================================
# 统一导出
# ============================================================

from .realtime import fetch_realtime
from .fundamental import fetch_fundamental
from .historical import fetch_historical
from .info import fetch_info

__all__ = [
    "normalize_code",
    "safe_float",
    "safe_int",
    "retry_fetch",
    "publish_event",
    "record_fetch",
    "is_trading_day",
    "fetch_realtime",
    "fetch_fundamental",
    "fetch_historical",
    "fetch_info",
]
