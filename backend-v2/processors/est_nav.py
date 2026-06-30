"""
估算净值计算引擎

公式:
  估算净值 = 昨日净值 × (1 + 十大持仓贡献 + 其余仓位贡献)
  十大持仓贡献 = Σ(权重_i × 涨跌幅_i / 100)
  其余仓位贡献 = (1 - 十大总权重) × 指数涨跌幅 / 100

输入:
  - fund_daily.nav (昨日净值)
  - fund_asset_map (持仓权重)
  - fund_info.index_code (跟踪指数)
  - asset_quote (实时涨跌幅)

输出:
  - {fund_code: {est_nav, est_change_pct, holdings_contrib, index_contrib, coverage}}
"""
import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from index_mapping import get_index_quote_code

logger = logging.getLogger("app")


@dataclass
class FundEstResult:
    """单只基金的估算结果"""
    fund_code: str
    est_nav: float | None = None          # 估算净值
    est_change_pct: float | None = None   # 估算涨跌幅 (%)
    holdings_contrib: float = 0.0         # 十大持仓贡献 (%)
    index_contrib: float = 0.0            # 指数贡献 (%)
    coverage: float = 0.0                 # 十大持仓覆盖率 (%)
    holding_details: list = None          # 每只持仓贡献明细
    index_detail: dict = None             # 指数贡献明细
    nav: float | None = None              # 昨日净值
    error: str | None = None


async def load_fund_meta(session: AsyncSession) -> dict[str, dict]:
    """
    加载所有基金的元数据: 昨日净值 + 跟踪指数。
    返回 {fund_code: {nav, index_name, index_tcode}}
    """
    r = await session.execute(text('''
        SELECT fd.code, fd.nav, fi.index_code
        FROM fund_daily fd
        JOIN fund_info fi ON fi.code = fd.code
        WHERE fd.nav IS NOT NULL
        AND fd.nav_date = (
            SELECT MAX(nav_date) FROM fund_daily WHERE code = fd.code
        )
    '''))
    meta = {}
    for code, nav, idx_name in r.fetchall():
        idx_tcode = get_index_quote_code(idx_name) if idx_name else None
        meta[code] = {
            'nav': float(nav),
            'index_name': idx_name,
            'index_tcode': idx_tcode,
        }
    return meta


async def load_holdings(session: AsyncSession) -> dict[str, list[dict]]:
    """
    加载所有基金的持仓权重。
    返回 {fund_code: [{asset_code, weight}, ...]}
    """
    r = await session.execute(text('''
        SELECT fund_code, asset_code, weight
        FROM fund_asset_map
        WHERE weight > 0
        ORDER BY fund_code, weight DESC
    '''))
    holdings: dict[str, list[dict]] = {}
    for fc, ac, wt in r.fetchall():
        if fc not in holdings:
            holdings[fc] = []
        holdings[fc].append({'asset_code': ac, 'weight': float(wt)})
    return holdings


def calc_est_nav(
    nav: float,
    holdings: list[dict],
    quotes: dict[str, float],
    index_tcode: str | None,
) -> FundEstResult:
    """
    计算单只基金的估算净值。

    Args:
        nav: 昨日净值
        holdings: 持仓列表 [{asset_code, weight}]
        quotes: {asset_code: change_pct}
        index_tcode: 跟踪指数的腾讯代码 (如 sh000300)

    Returns:
        FundEstResult
    """
    # 计算十大持仓贡献
    holdings_contrib = 0.0
    total_weight = 0.0
    holding_details = []

    for h in holdings:
        acode = h['asset_code']
        weight = h['weight']
        total_weight += weight

        pct = quotes.get(acode)
        contrib = weight * pct / 100 if pct is not None else 0.0
        if pct is not None:
            holdings_contrib += contrib
        holding_details.append({
            'code': acode,
            'weight': round(weight, 2),
            'change_pct': round(pct, 2) if pct is not None else None,
            'contrib': round(contrib, 4),
        })

    # 权重上限100%（防止杠杆基金异常）
    coverage = min(total_weight, 100.0)

    # 其余仓位：有跟踪指数则用指数涨跌，否则默认不涨不跌（0%）
    index_contrib = 0.0
    index_detail = None
    if index_tcode and total_weight < 100:
        idx_pct = quotes.get(index_tcode)
        remaining = max(0, 100 - total_weight)
        if idx_pct is not None:
            index_contrib = remaining * idx_pct / 100
            index_detail = {
                'code': index_tcode,
                'weight': round(remaining, 2),
                'change_pct': round(idx_pct, 2),
                'contrib': round(index_contrib, 4),
            }

    # 估算涨跌幅 = 十大持仓贡献 + 其余仓位贡献
    est_change_pct = holdings_contrib + index_contrib

    # 估算净值
    est_nav = round(nav * (1 + est_change_pct / 100), 4)

    return FundEstResult(
        fund_code='',
        est_nav=est_nav,
        est_change_pct=round(est_change_pct, 2),
        holdings_contrib=round(holdings_contrib, 2),
        index_contrib=round(index_contrib, 2),
        coverage=round(coverage, 2),
        holding_details=holding_details,
        index_detail=index_detail,
        nav=nav,
    )


async def calc_all_est_navs(
    session: AsyncSession,
    quotes: dict[str, float],
) -> dict[str, FundEstResult]:
    """
    批量计算所有基金的估算净值。

    Args:
        session: 数据库session
        quotes: {asset_code: change_pct} (来自 asset_quote 模块)

    Returns:
        {fund_code: FundEstResult}
    """
    meta = await load_fund_meta(session)
    holdings = await load_holdings(session)

    results = {}
    for fc, m in meta.items():
        fund_holdings = holdings.get(fc, [])
        if not fund_holdings:
            continue

        result = calc_est_nav(
            nav=m['nav'],
            holdings=fund_holdings,
            quotes=quotes,
            index_tcode=m['index_tcode'],
        )
        result.fund_code = fc
        results[fc] = result

    logger.info("[EST_NAV] 计算完成: %d 只基金", len(results))
    return results
