#!/usr/bin/env python3
"""
修正场内货币基金被当作 LOF/ETF 采集的问题

问题
----
有一批**场内货币基金**（`511xxx`/`159xxx`，`fund_info.fund_type` 为
`货币型-普通货币`）在 `fund_category` 里的类别是 `ETF`，于是被当成普通
场内基金采集，产生了荒谬数据：

    (收盘价 - 净值) / 净值 * 100

对货币基金根本不成立 ——
  * 行情"收盘价"是 **100 元面值**（每百份），不是可套利的交易价格；
  * 数据源 `lsjz` 给出的"净值"其实是**每份日收益**（0.19~0.68），
    与面值不在同一量纲。

实测产生的溢价率：

    511770  金鹰现金增益交易型货币市场基金  close=100.024  nav=0.1878
            → premium_rate = 53160.92%
    511800  易方达货币市场基金            close=100.007  nav=0.1894
            → premium_rate = 52702.01%

这些数字会直接冲到前端"溢价率降序"的榜首，严重误导用户。

本脚本做三件事
--------------
  1. 把这些基金的类别从 `ETF`/`LOF` 改为 `场内货币基金`
     —— 移出采集名单，避免继续拉取它们的"净值"；
  2. 清空已写入的错误 `nav` / `premium_rate`（连同估算净值），
     遵循"没有实时正确符合时间戳的数据就用空值"的原则；
  3. 刷新物化视图，让前端立刻不再显示这些荒谬值。

用法
----
    python3 scripts/fix_money_market_funds.py            # dry-run
    python3 scripts/fix_money_market_funds.py --apply

退出码
------
    0  成功（含 dry-run）
    1  执行出错
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP_DIR)
os.chdir(_APP_DIR)

import database  # noqa: E402

from config import settings  # noqa: E402
from sqlalchemy import text  # noqa: E402

log = logging.getLogger("fix_money_market")

MM_CATEGORY = "场内货币基金"

# 待修正的基金：类别是 LOF/ETF，但确实是货币基金。
#
# 条件只用 fund_type 与"货币"两个可靠信号。**不要用 name LIKE '%现金%'** ——
# "招商中证800自由现金流交易型开放式指数证券投资基金" 这类**股票型 ETF**
# 会被误判成货币基金，从而被错踢出采集名单（本脚本首次 dry-run 就踩到了：
# 63 条里有 37 条是"自由现金流"ETF）。
MM_CATEGORY = "场内货币基金"

TARGET_SQL = """
    SELECT fc.code, fc.category,
           COALESCE(fi.name, '') AS name,
           COALESCE(fi.fund_type, '') AS fund_type
    FROM fund_category fc
    LEFT JOIN fund_info fi ON fi.code = fc.code
    WHERE fc.category = ANY(ARRAY['LOF', 'ETF'])
      AND (fi.fund_type LIKE '货币%'
           OR fi.name LIKE '%货币%')
    ORDER BY fc.code
"""


async def _fetch(session):
    rows = (await session.execute(text(TARGET_SQL))).fetchall()
    return [dict(r._mapping) for r in rows]


async def run(apply: bool) -> int:
    database.init_engine(settings)
    try:
        async with database.async_session_factory() as session:
            targets = await _fetch(session)
            print(f"类别为 LOF/ETF 但实为货币基金的条目: {len(targets)} 条")
            for t in targets[:40]:
                print(f"    {t['code']}  [{t['category']}]  "
                      f"{t['name'][:34]:<36} type={t['fund_type']}")
            if len(targets) > 40:
                print(f"    ... 其余 {len(targets) - 40} 条省略")
            if not targets:
                print("\n无需修正。")
                return 0

            codes = sorted({t["code"] for t in targets})

            # 现状取证：这些基金当前被写入了什么
            bad = (await session.execute(text(
                "SELECT count(*) FILTER (WHERE nav IS NOT NULL) AS has_nav, "
                "count(*) FILTER (WHERE premium_rate IS NOT NULL) AS has_prem, "
                "count(*) FILTER (WHERE abs(premium_rate) > 100) AS absurd "
                "FROM fund_daily WHERE code = ANY(:codes)"
            ), {"codes": codes})).fetchone()
            print(f"\n现状: 有 nav 的 {bad[0]} 行, 有 premium_rate 的 {bad[1]} 行, "
                  f"其中 |premium|>100% 的 {bad[2]} 行")

            if not apply:
                print("\nDRY-RUN：加 --apply 才会执行下列修改：")
                print(f"  1) {len(targets)} 条类别 LOF/ETF -> {MM_CATEGORY}")
                print(f"  2) 清空这 {len(codes)} 只基金的 nav / premium_rate"
                      f" / 估算净值")
                print("  3) 刷新物化视图 fund_snapshot")
                return 0

            # ── 1. 改类别 ──
            await session.execute(text(
                "INSERT INTO fund_category (code, category) "
                "VALUES (:code, :cat) ON CONFLICT (code, category) DO NOTHING"
            ), [{"code": c, "cat": MM_CATEGORY} for c in codes])
            res = await session.execute(text(
                "DELETE FROM fund_category "
                "WHERE code = ANY(:codes) AND category = ANY(ARRAY['LOF','ETF'])"
            ), {"codes": codes})
            print(f"\n1) 类别修正: 新增 {MM_CATEGORY} {len(codes)} 条，"
                  f"删除 LOF/ETF {res.rowcount} 条")

            # ── 2. 清空错误数据 ──
            res = await session.execute(text(
                "UPDATE fund_daily SET nav = NULL, nav_date = NULL, "
                "nav_type = NULL, nav_source = NULL, premium_rate = NULL "
                "WHERE code = ANY(:codes) AND (nav IS NOT NULL "
                "     OR premium_rate IS NOT NULL)"
            ), {"codes": codes})
            print(f"2) fund_daily 清空错误净值/溢价率: {res.rowcount} 行")

            try:
                res = await session.execute(text(
                    "DELETE FROM fund_est_nav WHERE code = ANY(:codes)"
                ), {"codes": codes})
                print(f"   清理估算净值 fund_est_nav: {res.rowcount} 行")
            except Exception as exc:  # noqa: BLE001
                print(f"   fund_est_nav 清理跳过: {type(exc).__name__}")

            await session.commit()

        # ── 3. 刷新物化视图 ──
        from processors.saver import refresh_materialized_view
        await refresh_materialized_view(database.async_session_factory)
        print("3) 物化视图 fund_snapshot 已刷新")

        async with database.async_session_factory() as session:
            left = await _fetch(session)
            print(f"\n复查：仍被当作 LOF/ETF 的货币基金 {len(left)} 条")
            bad = (await session.execute(text(
                "SELECT count(*) FILTER (WHERE abs(premium_rate) > 100) "
                "FROM fund_daily WHERE code = ANY(:codes)"
            ), {"codes": codes})).fetchone()
            print(f"      |premium|>100% 的行数: {bad[0]}")
        return 0
    finally:
        await database.dispose_engine()


def cli() -> int:
    parser = argparse.ArgumentParser(
        description="把场内货币基金移出 LOF/ETF 采集名单并清空其错误溢价率")
    parser.add_argument("--apply", action="store_true",
                        help="真正写入（默认仅 dry-run）")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    return asyncio.run(run(apply=args.apply))


if __name__ == "__main__":
    raise SystemExit(cli())
