#!/usr/bin/env python3
"""
缺失基金基础信息补采

背景
----
`fetchers.info.fetch_info` 用进度文件按 `FUNDINFO_BATCH_SIZE`(300) 分批轮采，
`job_fetch_info` 每个工作日只跑一批，因此 2000+ 只基金需要约 7 个工作日才能轮完
一圈。新补进采集名单的基金按代码排序排在队尾，在轮到自己之前不会进入
`fund_info` —— 而前端物化视图 `fund_snapshot` 正是基于 `fund_info`，结果就是
"名单已补全、实时行情也采到了，但用户在网站上搜不到这只基金"。

本脚本精准补采「在采集名单中、但 fund_info 里还没有」的基金，补采完成后立刻
刷新物化视图，无需等待轮询。

用法
----
    python3 scripts/backfill_fund_info.py                  # 只列出缺失，不采集
    python3 scripts/backfill_fund_info.py --apply          # 补采全部缺失并刷新 MV
    python3 scripts/backfill_fund_info.py --apply --limit 50

退出码
------
    0  成功（含 dry-run）
    1  采集失败或数据库错误
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
from services.universe_service import COLLECT_CATEGORIES  # noqa: E402
from sqlalchemy import text  # noqa: E402

log = logging.getLogger("backfill_info")

MISSING_SQL = """
    SELECT fc.code
    FROM fund_category fc
    LEFT JOIN fund_info fi ON fi.code = fc.code
    WHERE fc.category = ANY(:cats) AND fi.code IS NULL
    ORDER BY fc.code
"""


async def find_missing(session_factory) -> list[str]:
    """采集名单中、fund_info 里尚不存在的代码。"""
    async with session_factory() as session:
        result = await session.execute(
            text(MISSING_SQL), {"cats": list(COLLECT_CATEGORIES)})
        return [row[0] for row in result.fetchall()]


async def run(apply: bool, limit: int | None) -> int:
    database.init_engine(settings)
    try:
        missing = await find_missing(database.async_session_factory)
        print(f"采集名单中缺失 fund_info 的基金: {len(missing)} 只")
        for code in missing[:20]:
            print(f"    {code}")
        if len(missing) > 20:
            print(f"    ... 其余 {len(missing) - 20} 只省略")

        if not apply:
            print("\nDRY-RUN：加 --apply 才会执行补采。")
            return 0
        if not missing:
            print("\n无缺失，无需补采。")
            return 0

        targets = missing[:limit] if limit else missing
        print(f"\n开始补采 {len(targets)} 只基础信息（含费率/持仓），"
              f"每只约 2-3 秒 …")

        import httpx
        from fetchers.info import fetch_info

        async with httpx.AsyncClient(timeout=30) as client:
            results = await fetch_info(client, targets, force=True)
        print(f"抓取成功: {len(results)}/{len(targets)}")

        if not results:
            print("抓取结果为空，终止写入。")
            return 1

        from processors.pipeline import process_info
        await process_info({"data": results}, "backfill-fund-info",
                           database.async_session_factory)
        print("已写入 fund_info / fund_fee / fund_holdings")

        from processors.saver import refresh_materialized_view
        await refresh_materialized_view(database.async_session_factory)
        print("已刷新物化视图 fund_snapshot —— 新基金现在可在前端检索到")

        remaining = await find_missing(database.async_session_factory)
        print(f"补采后仍缺失: {len(remaining)} 只")
        return 0
    finally:
        await database.dispose_engine()


def main() -> int:
    parser = argparse.ArgumentParser(description="补采缺失基金的基础信息")
    parser.add_argument("--apply", action="store_true",
                        help="真正执行补采（默认只列出缺失）")
    parser.add_argument("--limit", type=int, default=None,
                        help="最多补采多少只（默认全部）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    return asyncio.run(run(apply=args.apply, limit=args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
