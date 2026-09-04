"""
资产涨跌幅采集 — 腾讯 qt.gtimg.cn 批量查询

输入: asset_master 表中的资产列表
输出: {asset_code: change_pct} 字典

腾讯API字段:
  field[1]  = 名称
  field[3]  = 当前价
  field[4]  = 昨收价
  field[32] = 涨跌幅(%)
"""
import asyncio
import logging
import time

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger("app")

# 腾讯 API 单次最大查询数
BATCH_SIZE = 50

# 超时配置
REQUEST_TIMEOUT = 10

# 美股非标准代码 → 腾讯API代码映射
_US_CODE_MAP = {
    'TTEFP': 'TOT',    # 道达尔集团 Total SE
    'RIGD': 'RIG',     # Transocean Ltd
    'ENBCN': 'ENB',    # Enbridge Inc
    'CNQCN': 'CNQ',    # Canadian Natural Resources
    'EQNRNO': 'EQNR',  # Equinor ASA
}


def _code_to_tencent(code: str, market: str) -> str:
    """
    asset_master.code + market → 腾讯API代码
    如: code='600519', market='SH' → 'sh600519'
        code='000300', market='' (index) → 'sh000300'
    """
    # 指数代码本身已经是腾讯格式 (sh000300, sz399006, hkHSI)
    if code.startswith(('sh', 'sz', 'hk', 'us', 'bj')):
        return code
    # 美股非标准代码映射
    if market and market.upper() == 'US' and code in _US_CODE_MAP:
        return f'us{_US_CODE_MAP[code]}'
    # 股票代码需要加市场前缀
    prefix = market.lower() if market else ''
    return f'{prefix}{code}'


def _parse_change_pct(raw: str) -> float | None:
    """解析涨跌幅字符串为float，失败返回None"""
    try:
        val = float(raw)
        if val == 0.0:
            return 0.0
        return val
    except (ValueError, TypeError):
        return None


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=2),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    reraise=True,
)
async def _fetch_batch(
    client: httpx.AsyncClient,
    tencent_codes: list[str],
) -> dict[str, float]:
    """
    批量查询一组资产的涨跌幅。

    Args:
        client: httpx.AsyncClient
        tencent_codes: 腾讯API代码列表，如 ['sh600519', 'sz300750']

    Returns:
        {tencent_code: change_pct} 字典
    """
    url = 'https://qt.gtimg.cn/q=' + ','.join(tencent_codes)
    resp = await client.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

    # 腾讯返回 GBK 编码
    text = resp.content.decode('gbk', errors='replace')
    results = {}

    for line in text.strip().split(';'):
        line = line.strip()
        if not line or '=' not in line:
            continue

        # v_sh600519="1~贵州茅台~600519~..."
        var_part, _, val_part = line.partition('=')
        tcode = var_part.replace('v_', '').strip()
        val = val_part.strip('"')

        fields = val.split('~')
        if len(fields) < 33:
            continue

        change_pct = _parse_change_pct(fields[32])
        if change_pct is not None:
            results[tcode] = change_pct

    return results


async def fetch_asset_quotes(
    client: httpx.AsyncClient,
    assets: list[dict],
) -> dict[str, float]:
    """
    批量获取资产涨跌幅。

    Args:
        client: httpx.AsyncClient
        assets: 资产列表，每项含 {code, market, asset_type}
                可从 asset_master 查询获得

    Returns:
        {asset_code: change_pct} 字典
        如 {'600519': 1.23, 'sh000300': -0.56, '00700': 2.34}
    """
    if not assets:
        return {}

    start = time.monotonic()

    # 构建 tencent_code → asset_code 映射
    tcode_to_acode = {}
    tcode_list = []
    for a in assets:
        tcode = _code_to_tencent(a['code'], a.get('market', ''))
        tcode_to_acode[tcode] = a['code']
        tcode_list.append(tcode)

    # 分批查询
    all_results: dict[str, float] = {}
    failed_batches = 0

    for i in range(0, len(tcode_list), BATCH_SIZE):
        batch = tcode_list[i:i + BATCH_SIZE]
        try:
            batch_result = await _fetch_batch(client, batch)
            for tcode, pct in batch_result.items():
                acode = tcode_to_acode.get(tcode, tcode)
                all_results[acode] = pct
        except Exception as e:
            failed_batches += 1
            logger.warning("[ASSET_QUOTE] 批次 %d 失败: %s", i // BATCH_SIZE, e)

    elapsed = (time.monotonic() - start) * 1000
    logger.info(
        "[ASSET_QUOTE] 完成: %d/%d 资产, %d 批失败, %.0fms",
        len(all_results), len(assets), failed_batches, elapsed,
    )

    return all_results
