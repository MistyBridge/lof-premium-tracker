# -*- coding: utf-8 -*-
"""
实时行情采集 - push2主 + 腾讯备
"""
import asyncio
import logging
import time
from typing import List, Dict, Optional, Any

import httpx

from . import normalize_code, safe_float, safe_int, retry_fetch, publish_event, record_fetch

logger = logging.getLogger(__name__)

# push2 API 配置
PUSH2_URL = "https://push2.eastmoney.com/api/qt/clist/get"
PUSH2_FIELDS = "f2,f3,f5,f6,f8,f10,f12,f13,f14,f15,f16,f18,f20,f21,f37,f38,f204"
PUSH2_PARAMS = {
    "pn": 1,
    "pz": 2000,
    "po": 1,
    "np": 1,
    "fltt": 2,
    "invt": 2,
    "fid": "f3",
    "fs": "b:MK0021,b:MK0022,b:MK0023,b:MK0024",  # 沪深LOF+ETF
    "fields": PUSH2_FIELDS,
}

# 腾讯 qt 备源配置
TENCENT_QT_URL = "https://qt.gtimg.cn/q="
TENCENT_BATCH_SIZE = 50

# 字段码抽查配置
SPOT_CHECK_COUNT = 5
SPOT_CHECK_THRESHOLD = 0.2  # 偏差20%
SPOT_CHECK_MIN_PASS = 3     # 至少3只通过

# 部分数据防护阈值
DATA_INTEGRITY_THRESHOLD = 0.8  # 80%

# 全局变量：记录上次采集的数据量
_last_fetch_count = 0


async def fetch_realtime(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    """
    获取实时行情数据
    
    主源：push2 clist（单次获取全部）
    备源：腾讯 qt（仅深市）
    
    Args:
        client: httpx.AsyncClient 实例
        
    Returns:
        原始数据列表（保留push2原始字段名）
    """
    global _last_fetch_count
    
    start_time = time.time()
    
    # 尝试主源
    data = await _fetch_from_push2(client)
    
    if data:
        # 字段码抽查
        if not _spot_check_field_codes(data[:SPOT_CHECK_COUNT]):
            logger.error("[REALTIME] push2 field code check failed, possible field mapping change!")
            await record_fetch("realtime", success=False, business_error=True)
            return []
        
        # 部分数据防护
        if _last_fetch_count > 0 and len(data) < _last_fetch_count * DATA_INTEGRITY_THRESHOLD:
            logger.warning(
                f"[REALTIME] Data integrity issue: got {len(data)} < 80% of last fetch {_last_fetch_count}. "
                f"Keeping previous data."
            )
            await record_fetch("realtime", success=False, business_error=True)
            return []
        
        _last_fetch_count = len(data)
        
        # 发布事件
        await publish_event("realtime", {
            "data": data,
            "fetch_source": "push2",
            "count": len(data),
            "timestamp": time.time(),
        })
        
        elapsed = time.time() - start_time
        logger.info(f"[REALTIME] push2 success: {len(data)} items in {elapsed:.2f}s")
        await record_fetch("realtime", success=True, count=len(data))
        
        return data
    
    # 主源失败，尝试备源
    logger.warning("[REALTIME] push2 failed, falling back to tencent qt...")
    data = await _fetch_from_tencent(client)
    
    if data:
        _last_fetch_count = len(data)
        
        await publish_event("realtime", {
            "data": data,
            "fetch_source": "tencent",
            "count": len(data),
            "timestamp": time.time(),
        })
        
        elapsed = time.time() - start_time
        logger.info(f"[REALTIME] tencent fallback success: {len(data)} items in {elapsed:.2f}s")
        await record_fetch("realtime", success=True, count=len(data))
        
        return data
    
    # 全部失败
    logger.error("[REALTIME] All sources failed")
    await record_fetch("realtime", success=False)
    return []


async def _fetch_from_push2(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    """从push2获取数据"""
    try:
        response = await client.get(PUSH2_URL, params=PUSH2_PARAMS, timeout=15)
        response.raise_for_status()
        
        result = response.json()
        
        # 检查业务响应码
        if result.get("rc") != 0:
            logger.warning(f"[REALTIME] push2 business error: rc={result.get('rc')}")
            return []
        
        data = result.get("data", {})
        diff = data.get("diff", [])
        
        if not diff:
            logger.warning("[REALTIME] push2 returned empty data")
            return []
        
        # 添加fetch_source和标准化代码
        processed = []
        for item in diff:
            if isinstance(item, dict):
                item["fetch_source"] = "push2"
                item["code"] = normalize_code(str(item.get("f12", "")))
                processed.append(item)
        
        return processed
        
    except Exception as e:
        logger.error(f"[REALTIME] push2 error: {e}")
        return []


async def _fetch_from_tencent(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    """从腾讯qt获取数据（仅深市）"""
    # 这里需要已知的深市LOF代码列表
    # 实际实现中，应该从数据库或配置文件获取
    # 简化实现：假设有一个全局的代码列表
    from backend.config import Config
    
    # 获取深市代码列表（简化实现）
    sz_codes = _get_sz_lof_codes()
    
    if not sz_codes:
        logger.warning("[REALTIME] No SZ codes available for tencent fallback")
        return []
    
    all_data = []
    batches = [sz_codes[i:i+TENCENT_BATCH_SIZE] for i in range(0, len(sz_codes), TENCENT_BATCH_SIZE)]
    
    for batch_idx, batch in enumerate(batches):
        codes_str = ",".join([f"sz{code}" for code in batch])
        url = f"{TENCENT_QT_URL}{codes_str}"
        
        try:
            response = await client.get(url, timeout=10)
            response.raise_for_status()
            
            # 解析腾讯qt响应（文本格式）
            items = _parse_tencent_response(response.text)
            all_data.extend(items)
            
            # 请求间隔
            if batch_idx < len(batches) - 1:
                await asyncio.sleep(0.1)
                
        except Exception as e:
            logger.warning(f"[REALTIME] tencent batch {batch_idx} error: {e}")
            continue
    
    return all_data


def _parse_tencent_response(text: str) -> List[Dict[str, Any]]:
    """解析腾讯qt响应（文本格式）"""
    items = []
    
    for line in text.strip().split("\n"):
        if not line or "=" not in line:
            continue
        
        try:
            # 格式：v_sz160644="1~xxx~160644~..."
            var_part, value_part = line.split("=", 1)
            code = var_part.split("_")[-1][2:]  # 提取代码
            
            fields = value_part.strip('"').split("~")
            if len(fields) < 10:
                continue
            
            items.append({
                "code": normalize_code(code),
                "f12": normalize_code(code),  # 代码
                "f14": fields[1],             # 名称
                "f2": safe_float(fields[3]),  # 最新价
                "f3": safe_float(fields[32]), # 涨跌幅
                "f5": safe_float(fields[6]),  # 成交量
                "f6": safe_float(fields[37]), # 成交额
                "f13": 0,                     # 市场（深市=0）
                "fetch_source": "tencent",
            })
        except Exception as e:
            logger.debug(f"[REALTIME] Failed to parse tencent line: {e}")
            continue
    
    return items


def _spot_check_field_codes(data: List[Dict[str, Any]]) -> bool:
    """
    字段码抽查
    
    检查前N只基金的f2（最新价）是否合理
    """
    if len(data) < SPOT_CHECK_COUNT:
        return True
    
    pass_count = 0
    sample = data[:SPOT_CHECK_COUNT]
    
    for item in sample:
        price = safe_float(item.get("f2"))
        prev_close = safe_float(item.get("f18"))
        
        if price is None or prev_close is None:
            continue
        
        if price <= 0 or prev_close <= 0:
            continue
        
        # 偏差检查
        deviation = abs(price - prev_close) / prev_close
        if deviation < SPOT_CHECK_THRESHOLD:
            pass_count += 1
    
    return pass_count >= SPOT_CHECK_MIN_PASS


def _get_sz_lof_codes() -> List[str]:
    """获取深市LOF代码列表（简化实现）"""
    # 实际实现中，应该从数据库或配置文件获取
    # 这里返回一个示例列表
    try:
        import json
        with open("backend/sz_lof_codes.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("codes", [])
    except:
        return []
