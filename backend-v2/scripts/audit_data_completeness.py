#!/usr/bin/env python3
"""
数据完整性审计（只读）

回答"我们的 LOF/ETF 名单与数据到底缺什么"，用于在补全操作前后做对照，
以及日常巡检。不写任何数据。

检查项
------
  1. fund_category 类别分布
  2. 采集名单（LOF/ETF）里 fund_info 缺失的基金
  3. 非场内代码（0 开头的场外基金/ETF-FOF，属脏数据）
  4. 孤儿：fund_info 里但不在受管类别（会经物化视图出现在前端）
  5. 近日 fund_daily 的 close / nav / premium_rate 覆盖率

关于第 5 项的重要说明
---------------------
`premium_rate` 由 `daily_save` 在**次日 08:30** 计算，因为它要等当日
净值（`fetch_nav` 08:01）到位。因此**最新交易日 premium_rate 为空是正常
的**，不要误判为故障；若强行提前跑 daily_save，会用上一日净值算出错误的
溢价率（违反"没有实时正确数据就用空值"的原则）。本脚本会把"净值是否已
到位"一并打印，便于区分"还没到时候"和"真的漏了"。

用法
----
    python3 scripts/audit_data_completeness.py
    python3 scripts/audit_data_completeness.py --days 5
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP_DIR)
os.chdir(_APP_DIR)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from config import settings  # noqa: E402
from services.universe_service import (  # noqa: E402
    COLLECT_CATEGORIES,
    MANAGED_CATEGORIES,
    is_exchange_listed,
)


def emit(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


async def main(days: int) -> int:
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as conn:
            async def rows(sql: str, **params):
                return (await conn.execute(text(sql), params)).fetchall()

            emit("【1】fund_category 类别分布")
            for cat, n in await rows(
                    "SELECT category, count(*) FROM fund_category "
                    "GROUP BY category ORDER BY 2 DESC"):
                mark = "" if cat in MANAGED_CATEGORIES else "   (非受管)"
                print(f"    {cat:<14} {n}{mark}")

            emit(f"【2】采集名单 {COLLECT_CATEGORIES} 里 fund_info 缺失")
            miss = await rows(
                "SELECT fc.code, fc.category FROM fund_category fc "
                "LEFT JOIN fund_info fi ON fi.code = fc.code "
                "WHERE fc.category = ANY(:cats) AND fi.code IS NULL "
                "ORDER BY fc.code", cats=list(COLLECT_CATEGORIES))
            print(f"    缺失 {len(miss)} 只")
            for code, cat in miss[:30]:
                print(f"        {code}  [{cat}]")
            if len(miss) > 30:
                print(f"        ... 其余 {len(miss) - 30} 只省略")
            if miss:
                print("    修复: python3 scripts/backfill_fund_info.py --apply")

            emit("【3】非场内代码（脏数据：0 开头的场外基金）")
            allcat = await rows(
                "SELECT code, category FROM fund_category ORDER BY code")
            bad = [(c, cat) for c, cat in allcat if not is_exchange_listed(c)]
            print(f"    共 {len(bad)} 条")
            for code, cat in bad[:20]:
                print(f"        {code}  [{cat}]")
            if len(bad) > 20:
                print(f"        ... 其余 {len(bad) - 20} 条省略")
            print("    说明: 场内代码只能是沪市 5 开头或深市 1 开头。"
                  "这些代码在任何行情源上都查不到，")
            print("          却占用采集名额、在快照里留下只有净值的空行。")

            emit("【4】孤儿：fund_info 里但不在受管类别")
            tot = (await rows("SELECT count(*) FROM fund_info"))[0][0]
            print(f"    fund_info 总行数: {tot}")
            orph = await rows(
                "SELECT fi.code, fi.name FROM fund_info fi "
                "WHERE NOT EXISTS (SELECT 1 FROM fund_category fc "
                "                  WHERE fc.code = fi.code "
                "                  AND fc.category = ANY(:cats)) "
                "ORDER BY fi.code", cats=list(MANAGED_CATEGORIES))
            print(f"    不在受管类别 {MANAGED_CATEGORIES} 里: {len(orph)} 只")
            for code, name in orph[:40]:
                print(f"        {code}  {name}")
            if orph:
                print("    说明: 物化视图 fund_snapshot 基于 fund_info，"
                      "这些基金仍会出现在前端列表里。")

            emit(f"【5】近日 fund_daily 覆盖率（最近 {days} 个交易日）")
            print(f"    {'日期':<12}{'行数':>7}{'close':>8}{'nav':>8}"
                  f"{'premium':>9}{'premium%':>10}")
            for d, n, c, v, p in await rows(
                    "SELECT trade_date, count(*), count(close), count(nav), "
                    "count(premium_rate) FROM fund_daily "
                    "GROUP BY trade_date ORDER BY trade_date DESC "
                    "LIMIT :n", n=days):
                pct = (p * 100 // n) if n else 0
                print(f"    {str(d):<12}{n:>7}{c:>8}{v:>8}{p:>9}{pct:>9}%")

            print("\n    —— 判断依据：净值是否已到位 ——")
            latest = (await rows(
                "SELECT max(trade_date) FROM fund_daily"))[0][0]
            if latest:
                nd = await rows(
                    "SELECT nav_date, count(*) FROM fund_daily "
                    "WHERE trade_date = :d GROUP BY nav_date "
                    "ORDER BY 2 DESC LIMIT 3", d=latest)
                print(f"    最新交易日 {latest} 的 nav_date 分布:")
                for d2, n2 in nd:
                    print(f"        nav_date={d2}  {n2} 行")
                same = next((n2 for d2, n2 in nd if d2 == latest), 0)
                total = (await rows(
                    "SELECT count(*) FROM fund_daily WHERE trade_date = :d",
                    d=latest))[0][0]
                if same == 0:
                    print(f"    → 当日净值尚未到位（0/{total}），"
                          f"premium_rate 为空属正常，等 daily_save 次日 08:30。")
                elif same < total * 0.8:
                    print(f"    → 当日净值仅到位 {same}/{total}，"
                          f"premium_rate 覆盖不足，建议检查 fetch_nav。")
                else:
                    print(f"    → 净值已到位 {same}/{total}。"
                          f"若 premium_rate 仍为空说明 daily_save 有问题。")
    finally:
        await engine.dispose()
    return 0


def cli() -> int:
    parser = argparse.ArgumentParser(description="数据完整性审计（只读）")
    parser.add_argument("--days", type=int, default=5,
                        help="查看最近多少个交易日的覆盖率（默认 5）")
    args = parser.parse_args()
    return asyncio.run(main(days=args.days))


if __name__ == "__main__":
    raise SystemExit(cli())
