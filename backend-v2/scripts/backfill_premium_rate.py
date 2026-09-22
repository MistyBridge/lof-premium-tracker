#!/usr/bin/env python3
"""
回填历史溢价率 premium_rate

问题
----
`premium_rate` 一直由 `daily_save` 计算，而 `daily_save` 历史上遍历的是一份
**冻结的** 673 条 `fund_code_list`，里面只有 `16xxxx`/`50xxxx` 的 LOF ——
一只 ETF 都没有。于是 ETF 的历史溢价率**整列为空**：

    ETF   95239 行，有 premium_rate 的只有 1651 行（全部来自 2026-09-22）
    LOF  113655 行，有 premium_rate 的 89543 行

后果是 ETF 详情页的走势图没有溢价率曲线，只剩最近一天 —— 板块上线前必须补上。
（采集端的根因已由 #195 修掉：采集名单改为从 `fund_category` 读取。
本脚本负责把**修复之前**已经落库的行补回来。）

判定口径
--------
只在 **净值日期 == 交易日** 时才计算：

    premium_rate = round((close - nav) / nav * 100, 4)

跨境/QDII 的净值天生滞后 1~2 个交易日，用错位净值算出来的是"两个交易日行情
混算"的假溢价率（即 PR#208 修掉的那个问题）。宁可留空档，也不写这种值 ——
符合"没有实时正确符合时间戳的数据就用空值，避免误导用户"的原则。

只补 `premium_rate IS NULL` 的行，已算过的绝不覆盖，因此可重复执行。

用法
----
    python3 scripts/backfill_premium_rate.py                  # dry-run，全历史
    python3 scripts/backfill_premium_rate.py --apply
    python3 scripts/backfill_premium_rate.py --days 30 --apply  # 只补最近 30 天

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

log = logging.getLogger("backfill_premium_rate")


# 回填条件：收盘价、净值都在，且**净值日期与交易日对齐**。
# 与 processors/calculator.py 的 calc_premium_rate 公式保持一致。
BACKFILL_SQL = text("""
UPDATE fund_daily fd SET
    premium_rate = round((fd.close - fd.nav) / fd.nav * 100, 4)
WHERE fd.premium_rate IS NULL
  AND fd.close IS NOT NULL AND fd.close > 0
  AND fd.nav IS NOT NULL AND fd.nav > 0
  AND fd.nav_date = fd.trade_date
  AND fd.trade_date >= :since
""")

COUNT_SQL = text("""
SELECT COALESCE(fc.category, '(无类别)') AS cat,
       count(*) AS backfillable
FROM fund_daily fd
LEFT JOIN fund_category fc ON fc.code = fd.code
WHERE fd.premium_rate IS NULL
  AND fd.close IS NOT NULL AND fd.close > 0
  AND fd.nav IS NOT NULL AND fd.nav > 0
  AND fd.nav_date = fd.trade_date
  AND fd.trade_date >= :since
GROUP BY 1 ORDER BY 2 DESC
""")

# 空档报告：有收盘价与净值、但日期不对齐 → 回填后会留空（不伪造）
GAP_SQL = text("""
SELECT count(*) FROM fund_daily fd
WHERE fd.premium_rate IS NULL
  AND fd.close IS NOT NULL AND fd.close > 0
  AND fd.nav IS NOT NULL AND fd.nav > 0
  AND fd.nav_date IS DISTINCT FROM fd.trade_date
  AND fd.trade_date >= :since
""")


async def run(apply: bool, days: int | None) -> int:
    from datetime import date, timedelta

    since = date(1900, 1, 1) if not days else (date.today() - timedelta(days=days))

    database.init_engine(settings)
    try:
        async with database.async_session_factory() as session:
            rows = (await session.execute(
                COUNT_SQL, {"since": since})).fetchall()
            gap = (await session.execute(
                GAP_SQL, {"since": since})).scalar() or 0

            total = sum(r[1] for r in rows)
            print(f"回填范围: trade_date >= {since}")
            print(f"可回填 premium_rate 的行: {total}")
            for cat, n in rows:
                print(f"    {cat:<16} {n}")
            print(f"日期不对齐、按口径**留空**的行: {gap}"
                  "（跨境/QDII 净值滞后，算出来会是假溢价率）")

            if total == 0:
                print("\n无需回填。")
                return 0

            if not apply:
                print("\nDRY-RUN：加 --apply 才会执行回填并刷新物化视图")
                return 0

            result = await session.execute(BACKFILL_SQL, {"since": since})
            await session.commit()
            print(f"\n1) premium_rate 回填: {result.rowcount} 行")

        # ── 刷新物化视图 ──
        from processors.saver import refresh_materialized_view
        await refresh_materialized_view(database.async_session_factory)
        print("2) 物化视图 fund_snapshot 已刷新")

        async with database.async_session_factory() as session:
            left = (await session.execute(
                COUNT_SQL, {"since": since})).fetchall()
            print(f"\n复查：仍可回填 {sum(r[1] for r in left)} 行")
        return 0
    finally:
        await database.dispose_engine()


def cli() -> int:
    parser = argparse.ArgumentParser(
        description="回填历史溢价率 premium_rate（仅净值日期与交易日对齐的行）")
    parser.add_argument("--apply", action="store_true",
                        help="真正写入（默认仅 dry-run）")
    parser.add_argument("--days", type=int, default=None,
                        help="只回填最近 N 天（默认全历史）")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    return asyncio.run(run(apply=args.apply, days=args.days))


if __name__ == "__main__":
    raise SystemExit(cli())
