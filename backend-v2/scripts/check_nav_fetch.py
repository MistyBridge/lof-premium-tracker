#!/usr/bin/env python3
"""手动跑一次 job_fetch_nav，验证：
  1. 并集代码集（含 QDII）能正常工作；
  2. nav:all 是**合并**写入（条数不会倒退）；
  3. 这次有没有真的取到更新的净值（nav_date 前进的基金）；
  4. 单次耗时（评估 12 次/天的压力）。
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP_DIR)
os.chdir(_APP_DIR)

import cache  # noqa: E402
import database  # noqa: E402
import scheduler as sch  # noqa: E402
from cache import cache_get  # noqa: E402
from config import settings  # noqa: E402


def dates(m):
    return {c: (v or {}).get("nav_date") for c, v in (m or {}).items()}


async def main() -> int:
    database.init_engine(settings)
    await cache.init_redis(settings.REDIS_URL, settings.REDIS_MAX_CONNECTIONS)
    await sch.init_scheduler_http()
    try:
        codes = await sch._nav_codes()
        collect_only = await sch._codes()
        qdii = await sch._qdii()
        print(f"采集名单 {len(collect_only)} 只，QDII {len(qdii)} 只 "
              f"→ 并集 {len(codes)} 只"
              f"（QDII 中不在名单内的 {len(set(qdii) - set(collect_only))} 只）")

        before = await cache_get("nav:all") or {}
        bd = dates(before)
        print(f"\nnav:all 现有 {len(before)} 条")

        t0 = time.monotonic()
        await sch.job_fetch_nav()
        dt = time.monotonic() - t0

        after = await cache_get("nav:all") or {}
        ad = dates(after)
        print(f"\n单次耗时 {dt:.1f}s")
        print(f"nav:all 现在 {len(after)} 条（合并写入，不应少于之前）")

        advanced = [(c, bd.get(c), ad.get(c)) for c in ad
                    if bd.get(c) and ad.get(c) and str(ad[c]) > str(bd[c])]
        print(f"\n本次取到更新净值的基金: {len(advanced)} 只")
        for c, o, n in sorted(advanced, key=lambda z: str(z[2]), reverse=True)[:10]:
            print(f"  {c}  {o} → {n}")

        lost = [c for c in bd if c not in ad]
        print(f"\n合并后丢失的代码: {len(lost)} 只" + (f" {lost[:5]}" if lost else ""))

        est = dt * 12
        print(f"\n按 12 次/天估算日累计耗时 {est:.0f}s；"
              f"每日请求数 ≈ {len(codes) * 12}")
        return 0
    finally:
        await sch.close_scheduler_http()
        await database.dispose_engine()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
