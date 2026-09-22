#!/usr/bin/env python3
"""
清理 fund_category 里的"非场内代码"（0 开头的场外基金）

问题
----
`fund_category` 是采集名单的唯一真源，也是前端 `filter_mode=lof/etf` 的过滤依据。
库里混进了一批 **0 开头的场外基金**：

    ETF          44 条   全是 "…基金中基金(ETF-FOF)"，名称里带 "ETF" 被名称规则误判
    REITs         4 条
    封闭式基金     5 条
    场内货币基金   3 条   场外份额

场内基金代码只可能是沪市 `5` 开头或深市 `1` 开头（见
`services/universe_service.is_exchange_listed`），0 开头的一律是场外，
任何行情源都查不到它们。后果：

  * 白占采集名额 —— `fetch_realtime`/`fetch_kline` 对它们永远拿不到数据；
  * 在 `fund_snapshot` 里留下没有任何行情的空行；
  * **前端 ETF 板块里混进 44 只根本不是 ETF 的场外 FOF**。本次 ETF 板块上线
    必须清掉，否则用户会在"ETF基金"列表里看到一堆申赎在柜台、根本买不到的
    场外基金，且它们的净值/溢价率永远是空的。

判定规则是**代码本身的语法事实**（0 开头 → 不可能是场内），不是启发式，
所以删除安全、可复现，与 `universe_service` 里已有的同一判定完全一致。
`sync_fund_universe.py` 发现这些条目后只报告不删（它的 `non_exchange` 桶
设计为"供人工确认"），本脚本就是它在提示里指向的那个清理入口。

只动 `fund_category`（采集名单 + 前端过滤依据）。`fund_info` 里的残留行
不影响 ETF 板块（列表按 `fund_category` 过滤），本脚本只统计并提示。

用法
----
    python3 scripts/purge_non_exchange.py                # dry-run
    python3 scripts/purge_non_exchange.py --apply

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

log = logging.getLogger("purge_non_exchange")

# 场内代码只可能是沪市 5 开头 / 深市 1 开头；其余一律是场外。
TARGET_SQL = text("""
SELECT fc.code, fc.category,
       COALESCE(fi.name, '')      AS name,
       COALESCE(fi.fund_type, '') AS fund_type
FROM fund_category fc
LEFT JOIN fund_info fi ON fi.code = fc.code
WHERE left(fc.code, 1) NOT IN ('1', '5')
ORDER BY fc.category, fc.code
""")

DELETE_SQL = text("DELETE FROM fund_category WHERE code = ANY(:codes)")

# fund_info 里的残留（不影响 ETF 板块过滤，仅提示）
INFO_LEFT_SQL = text("""
SELECT count(*) FROM fund_info fi
WHERE left(fi.code, 1) NOT IN ('1', '5')
  AND NOT EXISTS (SELECT 1 FROM fund_category fc WHERE fc.code = fi.code)
""")


async def run(apply: bool) -> int:
    database.init_engine(settings)
    try:
        async with database.async_session_factory() as session:
            rows = (await session.execute(TARGET_SQL)).fetchall()
            targets = [dict(r._mapping) for r in rows]

            by_cat: dict[str, list[dict]] = {}
            for t in targets:
                by_cat.setdefault(t["category"], []).append(t)

            print(f"fund_category 中的非场内代码（0 开头）: {len(targets)} 条")
            for cat in sorted(by_cat):
                items = by_cat[cat]
                print(f"  [{cat}] {len(items)} 条")
                for t in items[:6]:
                    label = t["name"] or t["fund_type"] or "(无 fund_info)"
                    print(f"      {t['code']}  {label[:46]}")
                if len(items) > 6:
                    print(f"      ... 其余 {len(items) - 6} 条省略")

            if not targets:
                print("\n无需清理。")
                return 0

            codes = sorted({t["code"] for t in targets})

            if not apply:
                print("\nDRY-RUN：加 --apply 才会执行：")
                print(f"  1) 从 fund_category 删除这 {len(codes)} 个代码的全部类别记录"
                      f"（{len(targets)} 条）")
                print("  2) 刷新物化视图 fund_snapshot")
                return 0

            result = await session.execute(DELETE_SQL, {"codes": codes})
            await session.commit()
            print(f"\n1) fund_category 删除: {result.rowcount} 条")

        # ── 刷新物化视图 ──
        from processors.saver import refresh_materialized_view
        await refresh_materialized_view(database.async_session_factory)
        print("2) 物化视图 fund_snapshot 已刷新")

        async with database.async_session_factory() as session:
            left = (await session.execute(TARGET_SQL)).fetchall()
            info_left = (await session.execute(INFO_LEFT_SQL)).scalar() or 0
            print(f"\n复查：fund_category 中剩余非场内代码 {len(left)} 条")
            print(f"      fund_info 中已不在任何类别的场外残留 {info_left} 行"
                  "（不影响 ETF 板块列表，列表按 fund_category 过滤）")
        return 0
    finally:
        await database.dispose_engine()


def cli() -> int:
    parser = argparse.ArgumentParser(
        description="从 fund_category 删除 0 开头的场外基金（非场内代码）")
    parser.add_argument("--apply", action="store_true",
                        help="真正写入（默认仅 dry-run）")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    return asyncio.run(run(apply=args.apply))


if __name__ == "__main__":
    raise SystemExit(cli())
