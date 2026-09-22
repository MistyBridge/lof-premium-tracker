#!/usr/bin/env python3
"""
基金名单同步 CLI

从权威源拉取沪深场内基金名单，与 fund_category 做差集并（可选）写入。

核心逻辑在 services/universe_service.py，本脚本只负责命令行入口与人类可读报告。
调度器每周会通过 job_scan_codes 自动执行同样的同步。

用法
----
    python3 scripts/sync_fund_universe.py                 # dry-run，只报告差异
    python3 scripts/sync_fund_universe.py --apply         # 把缺失条目写入数据库
    python3 scripts/sync_fund_universe.py --apply --prune # 额外移除官方已无的条目

退出码
------
    0  成功（含 dry-run）
    1  数据源全部失败或数据库错误
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

from services.universe_service import sync_universe  # noqa: E402


def _emit(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


async def run(apply: bool, prune: bool) -> int:
    _emit("【1】拉取权威名单")
    try:
        result = await sync_universe(apply=apply, prune=prune)
    except RuntimeError as exc:
        logging.error("%s", exc)
        return 1

    _emit("【2】差异分析")
    print(f"  权威名单(我们管理的类别): {result.authoritative} 只"
          f"  [深交所 {result.szse_count} + 沪市在线 {result.sse_count}"
          f" + 补充名单 {result.supplement_count}]")
    print(f"  腾讯扫描               : 在交易 {result.tencent_count}"
          f" / 无成交 {result.tencent_idle}"
          f" / 已删除 {result.tencent_gone}"
          f" / 有记录合计 {result.tencent_exists}")
    if not result.szse_complete:
        print("    ! 深交所抓取不完整 —— 本轮不判定深市退市")
    if not result.sse_complete:
        print("    ! 沪市抓取不完整 —— 本轮不判定沪市退市")
    print(f"  库内现有               : {result.db_total} 只")
    if result.money_market_filtered:
        by_name = result.money_market_filtered - result.money_market_by_type
        print(f"  货币基金已拦截         : {result.money_market_filtered} 只"
              f"（名称规则 {by_name} + fund_type 口径 {result.money_market_by_type}）")
        if result.money_market_by_type:
            print("     场内货币基金的行情名不含\"货币\"（如\"华宝添益ETF\"），")
            print("     只能靠 fund_info.fund_type=\"货币型-普通货币\" 识别；")
            print("     漏掉它们会让几万 % 的假溢价率重新冲上 ETF 榜首。")
    print(f"  待新增                 : {len(result.to_add)} 只")
    print(f"  类别不一致(仅报告)     : {len(result.conflicts)} 只")
    print(f"  官方已无(疑似退市)     : {len(result.to_remove)} 只")
    print(f"  有记录但当天无成交     : {len(result.stale)} 条")
    print(f"  非场内代码(疑似脏数据) : {len(result.non_exchange)} 条")
    print(f"  无法判定(源未覆盖)     : {len(result.uncovered)} 只")

    if result.to_add:
        print("\n  ── 待新增明细 ──")
        by_cat: dict[str, list[str]] = {}
        for code, category in result.to_add:
            by_cat.setdefault(category, []).append(code)
        for category in sorted(by_cat):
            codes = by_cat[category]
            print(f"    [{category}] {len(codes)} 只")
            for code in codes:
                print(f"        {code}  {result.names.get(code, '')}")

    if result.conflicts:
        print("\n  ── 类别不一致（需人工确认，本脚本不自动改）──")
        for code, official, mine in result.conflicts:
            print(f"    {code}  官方={official}  库内={mine}  "
                  f"{result.names.get(code, '')}")

    if result.to_remove:
        print("\n  ── 官方已无（疑似退市/终止上市）──")
        for code, category in result.to_remove:
            print(f"    {code}  [{category}]  {result.names.get(code, '')}")

    if result.stale:
        print(f"\n  ── 腾讯有记录但当天无成交（保留，共 {len(result.stale)} 条）──")
        print("     这些代码腾讯仍返回行情，只是当天零成交/长期停牌，")
        print("     不足以判定退市，因此不自动删除。")
        for code, category in result.stale[:10]:
            print(f"    {code}  [{category}]  {result.names.get(code, '')}")
        if len(result.stale) > 10:
            print(f"    ... 其余 {len(result.stale) - 10} 条省略")

    if result.non_exchange:
        print(f"\n  ── 非场内代码（脏数据，共 {len(result.non_exchange)} 条）──")
        print("     场内基金代码只可能是沪市 5 开头或深市 1 开头。以下条目是")
        print("     0 开头的场外基金（多为 ETF-FOF、场内货币基金场外份额），")
        print("     任何行情源都查不到，占用采集名额并在快照里留下空行。")
        print("     本脚本只报告，清理请用 scripts/purge_non_exchange.py。")
        for code, category in result.non_exchange[:20]:
            print(f"    {code}  [{category}]  {result.names.get(code, '')}")
        if len(result.non_exchange) > 20:
            print(f"    ... 其余 {len(result.non_exchange) - 20} 条省略")

    if result.uncovered:
        print(f"\n  ── 源未覆盖、无法判定（保留不删，共 {len(result.uncovered)} 条）──")
        for code, category in result.uncovered[:6]:
            print(f"    {code}  [{category}]")
        if len(result.uncovered) > 6:
            print(f"    ... 其余 {len(result.uncovered) - 6} 条省略")

    if not apply:
        _emit("【3】DRY-RUN（未写入）")
        print("  加 --apply 才会写入数据库；加 --apply --prune 会同时删除疑似退市条目。")
        return 0

    _emit("【3】写入数据库")
    print(f"  新增 fund_category 记录: {result.inserted} 条")
    if prune:
        print(f"  删除 fund_category 记录: {result.deleted} 条")
    else:
        print(f"  跳过删除（未指定 --prune），疑似退市 {len(result.to_remove)} 条保持不变")
    print("\n  提示: 名单变更将在下一次 fetch_realtime（每 5 分钟）自动生效；")
    print("        日终字段（close/premium_rate）由 daily_save 次日 08:30 补齐。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="从权威源同步沪深场内基金名单到 fund_category 表")
    parser.add_argument("--apply", action="store_true",
                        help="真正写入数据库（默认仅 dry-run）")
    parser.add_argument("--prune", action="store_true",
                        help="同时删除官方已无的条目（需配合 --apply）")
    parser.add_argument("--verbose", action="store_true", help="输出调试日志")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    return asyncio.run(run(apply=args.apply, prune=args.prune))


if __name__ == "__main__":
    raise SystemExit(main())
