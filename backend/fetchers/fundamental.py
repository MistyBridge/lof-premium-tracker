# -*- coding: utf-8 -*-
"""
净值+申赎采集 - lsjz API（Semaphore并发）
"""
import asyncio
import logging
import time
from typing import List, Dict, Optional, Any

import httpx

from . import normalize_code, safe_float, retry_fetch, publish_event, record_fetch

logger = logging.getLogger(__name__)

# lsjz API 配置
LSJZ_URL = "https://api.fund.eastmoney.com/f10/lsjz"
LSJZ_PARAMS_TEMPLATE = {
    "pageIndex": 1,
    "pageSize": 20,
    "startDate": "",
    "endDate": "",
}

# 并发配置
SEMAPHORE_SIZE = 5
REQUEST_INTERVAL = 0.3  # 秒


async def fetch_fundamental(
    client: httpx.AsyncClient,
    codes: List[str]
) -> List[Dict[str, Any]]:
    """
    批量获取基金净值和申赎状态
    
    Args:
        client: httpx.AsyncClient 实例
        codes: 基金代码列表
        
    Returns:
        净值数据列表
    """
    if not codes:
        return []
    
    start_time = time.time()
    semaphore = asyncio.Semaphore(SEMAPHORE_SIZE)
    
    # 批量并发获取
    tasks = [
        _fetch_single_fund(client, code, semaphore, idx)
        for idx, code in enumerate(codes)
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 收集成功的结果
    success_data = []
    failed_codes = []
    
    for code, result in zip(codes, results):
        if isinstance(result, Exception):
            logger.warning(f"[FUNDAMENTAL] {code} exception: {result}")
            failed_codes.append(code)
        elif result is not None:
            success_data.append(result)
        else:
            failed_codes.append(code)
    
    # 重试失败的基金
    if failed_codes:
        logger.info(f"[FUNDAMENTAL] Retrying {len(failed_codes)} failed funds...")
        retry_tasks = [
            _fetch_single_fund(client, code, semaphore, idx)
            for idx, code in enumerate(failed_codes)
        ]
        retry_results = await asyncio.gather(*retry_tasks, return_exceptions=True)
        
        for code, result in zip(failed_codes, retry_results):
            if isinstance(result, Exception):
                logger.error(f"[FUNDAMENTAL] {code} retry failed: {result}")
            elif result is not None:
                success_data.append(result)
    
    elapsed = time.time() - start_time
    logger.info(
        f"[FUNDAMENTAL] Completed: {len(success_data)}/{len(codes)} success in {elapsed:.2f}s"
    )
    
    # 发布事件
    await publish_event("nav", {
        "data": success_data,
        "fetch_source": "lsjz",
        "count": len(success_data),
        "timestamp": time.time(),
    })
    
    await record_fetch("fundamental", success=len(success_data) > 0, count=len(success_data))
    
    return success_data


async def _fetch_single_fund(
    client: httpx.AsyncClient,
    code: str,
    semaphore: asyncio.Semaphore,
    idx: int
) -> Optional[Dict[str, Any]]:
    """获取单只基金的净值数据"""
    async with semaphore:
        # 请求间隔
        if idx > 0 and idx % SEMAPHORE_SIZE == 0:
            await asyncio.sleep(REQUEST_INTERVAL)
        
        return await retry_fetch(
            _do_fetch_single,
            client,
            code,
            max_retries=2,
            backoff_base=1.0
        )


async def _do_fetch_single(
    client: httpx.AsyncClient,
    code: str
) -> Optional[Dict[str, Any]]:
    """执行单只基金的净值请求"""
    code = normalize_code(code)
    
    params = LSJZ_PARAMS_TEMPLATE.copy()
    params["fundCode"] = code
    
    try:
        response = await client.get(LSJZ_URL, params=params, timeout=15)
        response.raise_for_status()
        
        result = response.json()
        
        # 检查业务错误码
        err_code = result.get("ErrCode", -1)
        if err_code != 0:
            logger.warning(f"[FUNDAMENTAL] {code} business error: ErrCode={err_code}")
            return None
        
        data = result.get("Data", {})
        lsjz_list = data.get("LSJZList", [])
        
        if not lsjz_list:
            logger.debug(f"[FUNDAMENTAL] {code} no nav data")
            return None
        
        # 取最新一条
        latest = lsjz_list[0]
        
        # 解析净值
        nav = safe_float(latest.get("DWJZ"))
        if nav is None or nav <= 0:
            logger.debug(f"[FUNDAMENTAL] {code} invalid nav: {nav}")
            return None
        
        # 解析净值日期
        nav_date = latest.get("FSRQ", "")
        if not nav_date:
            logger.debug(f"[FUNDAMENTAL] {code} empty nav_date")
            return None
        
        # 解析申购状态
        sgzt_raw = latest.get("SGZT", "")
        sgzt = _parse_purchase_status(sgzt_raw)
        
        # 解析赎回状态
        shzt_raw = latest.get("SHZT", "")
        shzt = _parse_redeem_status(shzt_raw)
        
        # 解析日增长率
        rzzl = safe_float(latest.get("RZZL"))
        
        return {
            "code": code,
            "nav": nav,
            "nav_date": nav_date,
            "purchase_status": sgzt,
            "redeem_status": shzt,
            "daily_return": rzzl,
            "fetch_source": "lsjz",
        }
        
    except Exception as e:
        logger.error(f"[FUNDAMENTAL] {code} request error: {e}")
        raise


def _parse_purchase_status(status: str) -> str:
    """
    解析申购状态
    
    - 包含"开放" → "open"
    - 包含"暂停" → "suspended"
    - 包含"限制大额" → "restricted"
    - 其他 → "unknown"
    """
    if not status:
        return "unknown"
    
    if "开放" in status:
        return "open"
    elif "暂停" in status:
        return "suspended"
    elif "限制大额" in status:
        return "restricted"
    else:
        return "unknown"


def _parse_redeem_status(status: str) -> str:
    """
    解析赎回状态
    
    - 包含"开放" → "open"
    - 包含"暂停" → "suspended"
    - 其他 → "unknown"
    """
    if not status:
        return "unknown"
    
    if "开放" in status:
        return "open"
    elif "暂停" in status:
        return "suspended"
    else:
        return "unknown"
