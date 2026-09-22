#!/usr/bin/env python3
"""
修正"净值错位"——最新交易日行的净值停留在更旧的日期

问题
----
`fund_daily` 的净值有两套写入通路，其中"归位"通路（把已知最新净值补到最新
交易日行）原实现带 `AND fd.nav IS NULL`，只在行为空时补**一次**，此后再也
不更新。跨境/QDII 基金的净值天生滞后 1~2 个交易日，于是：

    09-22 早上归位时"最新净值"还是 09-18 的  → 09-22 行被写死成 09-18 的净值
    09-21 的净值随后到货                    → 只落到 09-21 行，09-22 行不再更新

结果 `premium_rate = (09-22 收盘价 − 09-18 净值) / 09-18 净值`，
两个交易日的行情被混算，溢价率系统性虚高。实测：

    159509 景顺长城纳斯达克科技ETF
        错误 32.07%   ← 09-18 净值 2.3086（当时库里最新）
        正确 27.93%   → 09-21 净值 2.3833（实际最新）

2026-09-22 当天共 146 行错位（ETF 73 / LOF 43 / 场内货币 30），
其中 37 只是溢价率最高的跨境 ETF。

本脚本做两件事
--------------
  1. 对每只基金的最新交易日行重新归位净值为 `nav_date <= 交易日` 的**最新**
     净值（可重复执行，幂等），并同步重算 premium_rate；
  2. 刷新物化视图，让前端立刻看到修正后的值。

不动历史行：历史溢价率由直写通路在净值到货时按 `nav_date == trade_date`
自然对齐，本脚本只负责"最新交易日行"这一处。

用法
----
    python3 scripts/repair_nav_alignment.py             # dry-run，先看差多少
    python3 scripts/repair_nav_alignment.py --apply

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

log = logging.getLogger("repair_nav_alignment")


# 所有"有收盘价"的基金 —— 也就是会被归位逻辑触及的集合
CANDIDATE_SQL = text(
    "SELECT DISTINCT code FROM fund_daily WHERE close IS NOT NULL ORDER BY code"
)

# 未来日期的净值：不该存在，出现即为上游数据异常（顺带体检）
FUTURE_SQL = text("""
    SELECT count(*) FROM fund_daily
    WHERE nav_date IS NOT NULL AND nav_date > CURRENT_DATE
""")


async def run(apply: bool, limit: int) -> int:
    from processors.nav_sync import list_misaligned, sync_nav_to_latest_row

    database.init_engine(settings)
    try:
        async with database.async_session_factory() as session:
            codes = [r[0] for r in (await session.execute(CANDIDATE_SQL)).fetchall()]
            future = (await session.execute(FUTURE_SQL)).scalar() or 0

            before = await list_misaligned(session, limit=limit)
            print(f"候选基金 {len(codes)} 只；未来日期的 nav_date {future} 行")
            print(f"\n修正前：净值日期与交易日不一致的最新行 {len(before)} 条"
                  + (f"（最多显示 {limit}）" if len(before) >= limit else ""))
            for r in before[:40]:
                print(f"  {r['code']} {r['name'][:30]:<32} "
                      f"交易日={r['trade_date']} 净值日={r['nav_date']} "
                      f"滞后{r['lag_days']}天 溢价={r['premium_rate']}")
            if len(before) > 40:
                print(f"  ... 其余 {len(before) - 40} 条省略")

            if not apply:
                print("\nDRY-RUN：加 --apply 才会执行：")
                print(f"  1) 对 {len(codes)} 只基金的最新交易日行重新归位净值"
                      "（取 nav_date <= 交易日 的最新净值）并重算 premium_rate")
                print("  2) 刷新物化视图 fund_snapshot")
                return 0

            changed = await sync_nav_to_latest_row(session, codes)
            await session.commit()
            print(f"\n1) 净值归位: 更新 {changed} 行")

        # ── 2. 刷新物化视图 ──
        from processors.saver import refresh_materialized_view
        await refresh_materialized_view(database.async_session_factory)
        print("2) 物化视图 fund_snapshot 已刷新")

        async with database.async_session_factory() as session:
            after = await list_misaligned(session, limit=limit)
            print(f"\n复查：仍不一致的最新行 {len(after)} 条")
            for r in after[:20]:
                print(f"  {r['code']} {r['name'][:30]:<32} "
                      f"交易日={r['trade_date']} 净值日={r['nav_date']} "
                      f"滞后{r['lag_days']}天 溢价={r['premium_rate']}")
        return 0
    finally:
        await database.dispose_engine()


def cli() -> int:
    parser = argparse.ArgumentParser(
        description="修正最新交易日行净值错位（跨境/QDII 净值滞后导致的虚高溢价率）")
    parser.add_argument("--apply", action="store_true",
                        help="真正写入（默认仅 dry-run）")
    parser.add_argument("--limit", type=int, default=200,
                        help="体检列表最多显示多少条（默认 200）")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    return asyncio.run(run(apply=args.apply, limit=args.limit))


if __name__ == "__main__":
    raise SystemExit(cli())
