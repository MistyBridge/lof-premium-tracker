"""
预计收益计算服务 — 溢价套利 / 折价套利收益率 + 收益额
"""
import logging
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import text

from cache import cache_get
from constants import (
    PROFIT_COMMISSION_MIN,
    PROFIT_COMMISSION_RATE,
    PROFIT_DEFAULT_REDEMPTION_FEE,
    PROFIT_MAX_CAPITAL,
)
from exceptions import NotFoundException

logger = logging.getLogger("app")


async def get_fund_profit(
    session_factory,
    code: str,
    commission_rate: float = PROFIT_COMMISSION_RATE,
    commission_min: float = PROFIT_COMMISSION_MIN,
    max_capital: float = PROFIT_MAX_CAPITAL,
) -> dict[str, Any]:
    """
    查询单只基金预计收益（含 DB 查询 + 实时数据合并）。
    Hub 层调用入口。
    """
    code = code.zfill(6)

    async with session_factory() as session:
        # 基础数据（从物化视图）
        row = await session.execute(
            text("SELECT * FROM fund_snapshot WHERE code = :code"),
            {"code": code},
        )
        fund_row = row.first()
        if not fund_row:
            raise NotFoundException(f"基金 {code} 不存在")
        fund = dict(fund_row._mapping)

        # 费率 + 申购状态
        fee_row = await session.execute(
            text(
                "SELECT purchase_fee_rate, redemption_fee_rate, "
                "purchase_limit, purchase_status "
                "FROM fund_fee WHERE code = :code"
            ),
            {"code": code},
        )
        fee = fee_row.first()
        if fee:
            fee_dict = dict(fee._mapping)
            fund["purchase_fee_rate"] = fee_dict.get("purchase_fee_rate")
            fund["redemption_fee_rate"] = fee_dict.get("redemption_fee_rate")
            fund["purchase_limit"] = fee_dict.get("purchase_limit")
            fund["can_purchase"] = fee_dict.get("purchase_status") != "暂停申购"

    # 合并实时溢价率（如有）
    rt_data = await cache_get("rt:all")
    if rt_data and code in rt_data:
        rt = rt_data[code]
        if rt.get("realtime_premium") is not None:
            fund["premium_rate"] = rt["realtime_premium"]

    result = calc_profit(
        fund,
        commission_rate=commission_rate,
        commission_min=commission_min,
        max_capital=max_capital,
    )
    result["code"] = code
    result["name"] = fund.get("name")
    return result


def calc_profit(
    fund: dict,
    commission_rate: float = PROFIT_COMMISSION_RATE,
    commission_min: float = PROFIT_COMMISSION_MIN,
    max_capital: float = PROFIT_MAX_CAPITAL,
) -> dict[str, Any]:
    """
    单只基金预计收益计算。

    Args:
        fund: 基金数据字段，需含:
            premium_rate, nav, close,
            purchase_fee_rate, redemption_fee_rate,
            purchase_limit, can_purchase
        commission_rate: 佣金费率(万分之几)，默认 1.5（万1.5）
        commission_min: 最低佣金(元)，默认 5
        max_capital: 最大投入金额(元)，默认 1000

    Returns:
        预计收益明细字典
    """
    # 统一 Decimal → float（PostgreSQL NUMERIC 返回 Decimal）
    fund = {k: float(v) if isinstance(v, Decimal) else v for k, v in fund.items()}

    premium = fund.get("premium_rate")
    if premium is None:
        return _no_profit("数据不足", max_capital)

    nav = fund.get("nav")
    close = fund.get("close")
    if not nav or not close:
        return _no_profit("数据不足", max_capital)

    # 实际投入资金 = min(max_capital, 申购限额)
    can_purchase = fund.get("can_purchase")
    purchase_limit = fund.get("purchase_limit")
    if can_purchase is False:
        return _no_profit("暂停申购", max_capital, purchase_limit=0)
    effective_limit = purchase_limit if purchase_limit and purchase_limit > 0 else None
    capital = min(max_capital, effective_limit) if effective_limit else max_capital
    if capital <= 0:
        return _no_profit("暂停申购", max_capital, purchase_limit=0)

    # 佣金计算
    commission_rate_pct = commission_rate / 10000
    raw_commission = capital * commission_rate_pct
    actual_commission = max(raw_commission, commission_min)
    actual_commission_rate = (actual_commission / capital) * 100
    is_min_commission = raw_commission < commission_min

    if premium > 0:
        return _calc_premium_arbitrage(
            premium=premium,
            capital=capital,
            purchase_fee_rate=fund.get("purchase_fee_rate"),
            commission_rate_pct=commission_rate_pct,
            raw_commission=raw_commission,
            actual_commission=actual_commission,
            actual_commission_rate=actual_commission_rate,
            is_min_commission=is_min_commission,
            purchase_limit=effective_limit,
            max_capital=max_capital,
        )
    else:
        return _calc_discount_arbitrage(
            premium=premium,
            capital=capital,
            redemption_fee_rate=fund.get("redemption_fee_rate"),
            commission_rate_pct=commission_rate_pct,
            raw_commission=raw_commission,
            actual_commission=actual_commission,
            actual_commission_rate=actual_commission_rate,
            is_min_commission=is_min_commission,
            purchase_limit=effective_limit,
            max_capital=max_capital,
        )


# ── 溢价套利 ────────────────────────────────────────────────


def _calc_premium_arbitrage(
    premium: float,
    capital: float,
    purchase_fee_rate: Optional[float],
    commission_rate_pct: float,
    raw_commission: float,
    actual_commission: float,
    actual_commission_rate: float,
    is_min_commission: bool,
    purchase_limit: Optional[float],
    max_capital: float,
) -> dict[str, Any]:
    """
    溢价套利: 申购 → T+2 卖出
    收益率 = 溢价率 − 申购费率 − 卖出佣金率
    """
    purchase_fee = purchase_fee_rate if purchase_fee_rate is not None else 0.0
    purchase_fee_amount = capital * purchase_fee / 100
    sell_commission_rate = actual_commission_rate
    sell_commission_amount = actual_commission

    profit_rate = premium - purchase_fee - sell_commission_rate
    profit_amount = capital * profit_rate / 100

    if profit_amount <= 0:
        return _no_profit("交易成本高于溢价收益", max_capital, purchase_limit=purchase_limit)

    return {
        "rate": round(profit_rate, 4),
        "amount": round(profit_amount, 2),
        "capital": capital,
        "direction": "溢价套利",
        "breakdown": {
            "premium_rate": round(premium, 4),
            "purchase_fee_rate": round(purchase_fee, 4),
            "purchase_fee_amount": round(purchase_fee_amount, 2),
            "sell_commission_rate": round(sell_commission_rate, 4),
            "sell_commission_amount": round(sell_commission_amount, 2),
            "commission_rate_pct": round(commission_rate_pct * 10000, 2),
            "raw_commission": round(raw_commission, 2),
            "actual_commission": round(actual_commission, 2),
            "is_min_commission": is_min_commission,
            "purchase_limit": purchase_limit,
            "max_capital": max_capital,
        },
    }


# ── 折价套利 ────────────────────────────────────────────────


def _calc_discount_arbitrage(
    premium: float,
    capital: float,
    redemption_fee_rate: Optional[float],
    commission_rate_pct: float,
    raw_commission: float,
    actual_commission: float,
    actual_commission_rate: float,
    is_min_commission: bool,
    purchase_limit: Optional[float],
    max_capital: float,
) -> dict[str, Any]:
    """
    折价套利: 买入 → T+1 赎回
    收益率 = |溢价率| − 买入佣金率 − 赎回费率
    """
    redeem_fee = redemption_fee_rate if redemption_fee_rate is not None else PROFIT_DEFAULT_REDEMPTION_FEE
    redeem_fee_amount = capital * redeem_fee / 100
    buy_commission_rate = actual_commission_rate
    buy_commission_amount = actual_commission

    discount_rate = abs(premium)
    profit_rate = discount_rate - buy_commission_rate - redeem_fee
    profit_amount = capital * profit_rate / 100

    if profit_amount <= 0:
        return _no_profit("交易成本高于折价收益", max_capital, purchase_limit=purchase_limit)

    return {
        "rate": round(profit_rate, 4),
        "amount": round(profit_amount, 2),
        "capital": capital,
        "direction": "折价套利",
        "breakdown": {
            "discount_rate": round(discount_rate, 4),
            "buy_commission_rate": round(buy_commission_rate, 4),
            "buy_commission_amount": round(buy_commission_amount, 2),
            "redemption_fee_rate": round(redeem_fee, 4),
            "redemption_fee_amount": round(redeem_fee_amount, 2),
            "commission_rate_pct": round(commission_rate_pct * 10000, 2),
            "raw_commission": round(raw_commission, 2),
            "actual_commission": round(actual_commission, 2),
            "is_min_commission": is_min_commission,
            "purchase_limit": purchase_limit,
            "max_capital": max_capital,
        },
    }


# ── 无收益兜底 ──────────────────────────────────────────────


def _no_profit(
    reason: str,
    max_capital: float,
    purchase_limit: Optional[float] = None,
) -> dict[str, Any]:
    """无收益/不建议交易的统一返回"""
    direction = "暂停申购" if "暂停" in reason else "不建议交易"
    return {
        "rate": 0,
        "amount": 0,
        "capital": 0,
        "direction": direction,
        "reason": reason,
        "breakdown": {
            "purchase_limit": purchase_limit,
            "max_capital": max_capital,
        },
    }
