#!/usr/bin/env python3
"""
手动全量更新

按正确顺序补跑一遍日常采集链路，用于补数据或人工核对：

    1. fetch_nav                    拉最新净值（含 QDII，写 Redis nav:all + fund_daily）
    2. 净值到位校验                  目标交易日净值覆盖不足则拒绝 daily_save
    3. fetch_kline                  拉全部代码最近 N 天 K 线（含新入名单的基金）
    4. daily_save                   算 close/nav/premium_rate 并刷新物化视图

为什么第 2 步的校验不可省
------------------------
`process_daily_save` 在当日净值缺失时会**回退用上一日的旧净值**
（`nav_val = nav.get("nav") or fallback.get("nav")`），于是 premium_rate 变成
"(当日收盘价 − 上一日净值) / 上一日净值" —— 一个时间戳对不上的错误数字。
它违反"没有实时正确符合时间戳的数据就用空值，避免误导用户"的原则。
所以本脚本在净值到位率不足时直接**拒绝**执行 daily_save 并说明原因，
而不是产出一批看着有值、实则错位的溢价率。

净值什么时候到位
----------------
A 股基金当日净值一般在当日 20:00-24:00 发布，QDII 更晚。
生产环境把链路排成：08:00 fetch_nav → 08:30 daily_save，
就是为了确保算溢价率时用的是当日净值。
因此在北京时间凌晨手动跑，通常会因净值未发布而被闸门拦下 —— 这是**预期行为**，
不是故障。此时只完成第 1、3 步（净值能拉到多少拉多少、K 线补齐），
等 08:30 的定时任务自然补齐日终字段即可。

用法
----
    python3 scripts/run_full_update.py                 # dry-run，只打印计划
    python3 scripts/run_full_update.py --apply         # 真正执行
    python3 scripts/run_full_update.py --apply --date 2026-09-22
    python3 scripts/run_full_update.py --apply --force # 跳过净值闸门（慎用）

退出码
------
    0  正常完成（含被闸门拦下）
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

from datetime import date, timedelta  # noqa: E402

log = logging.getLogger("full_update")

# 净值到位率低于此比例就不允许算溢价率
NAV_COVERAGE_MIN = 0.80
# 等待消费者处理 daily_save 事件的最长时间（秒）
DAILY_SAVE_WAIT = 600


def emit(title: str) -> None:
    print()
    print("=" * 76)
    print(title)
    print("=" * 76)


def _target_date(arg: str | None) -> date:
    if arg:
        return date.fromisoformat(arg)
    from utils import beijing_now
    return beijing_now().date() - timedelta(days=1)


async def _nav_coverage(target: date) -> tuple[int, int]:
    """返回 fund_daily 里 target 日的 (nav_date 同日行数, 总行数)。"""
    from sqlalchemy import text
    import database

    async with database.async_session_factory() as session:
        row = (await session.execute(text(
            "SELECT count(*) FILTER (WHERE nav_date = :d) AS same_day, "
            "count(*) AS total FROM fund_daily WHERE trade_date = :d"
        ), {"d": target})).fetchone()
        return int(row[0]), int(row[1])


async def _premium_coverage(target: date) -> tuple[int, int]:
    from sqlalchemy import text
    import database

    async with database.async_session_factory() as session:
        row = (await session.execute(text(
            "SELECT count(premium_rate), count(*) FROM fund_daily "
            "WHERE trade_date = :d"
        ), {"d": target})).fetchone()
        return int(row[0]), int(row[1])


async def main(apply: bool, target: date, force: bool) -> int:
    from config import settings
    import cache
    import database
    import scheduler as sch
    from trade_calendar import is_trading_day, load_calendar

    emit(f"手动全量更新  目标交易日 = {target}  "
         f"({'执行' if apply else 'DRY-RUN'})")

    if not apply:
        print("  计划：")
        print("    1) fetch_nav  拉最新净值（含 QDII）")
        print("    2) 校验目标日净值到位率（阈值 "
              f"{int(NAV_COVERAGE_MIN * 100)}%），不足则跳过 daily_save")
        print("    3) fetch_kline                 拉全部代码 K 线")
        print("    4) daily_save                  算 close/nav/premium_rate")
        print("\n  加 --apply 才会执行。")
        return 0

    database.init_engine(settings)
    # is_trading_day 在日历未加载时一律返回 False，必须先加载，
    # 否则下面的交易日判断会把正常交易日误判成非交易日而直接退出。
    async with database.async_session_factory() as session:
        await load_calendar(session)
    if not is_trading_day(target):
        print(f"  ! {target} 不是交易日，无需更新。")
        return 0

    await cache.init_redis(settings.REDIS_URL, settings.REDIS_MAX_CONNECTIONS)
    await sch.init_scheduler_http()

    try:
        # ── 1. 净值 ──
        emit("【1】拉取最新净值")
        # fetch_nav 的代码集已并集了 QDII（见 scheduler._nav_codes），
        # 原先紧跟的 job_fetch_nav_qdii() 是同一批请求的第二遍，已去掉。
        await sch.job_fetch_nav()
        same_day, total = await _nav_coverage(target)
        print(f"  fund_daily[{target}] 行数 {total}，其中 nav_date 同日 {same_day}")

        # ── 2. 闸门 ──
        emit("【2】净值到位校验")
        ratio = (same_day / total) if total else 0.0
        print(f"  同日净值到位率 = {same_day}/{total} = {ratio * 100:.1f}%"
              f"（阈值 {int(NAV_COVERAGE_MIN * 100)}%）")
        gate_ok = ratio >= NAV_COVERAGE_MIN
        if gate_ok:
            print("  ✓ 通过，可以计算溢价率")
        else:
            print("  ✗ 未通过 —— 当日净值尚未发布或抓取不全。")
            print("    此时若执行 daily_save，会回退用上一日净值，产出")
            print("    \"(当日收盘 − 上一日净值)\" 这种时间戳错位的溢价率，")
            print("    违反\"没有实时正确数据就用空值\"的原则，因此跳过。")
            print("    生产链路会在 08:00 fetch_nav / 08:30 daily_save 自动补齐。")
            if not force:
                print("\n  （--force 可强制跳过本闸门，仅在你确认净值确实已到位时使用）")

        # ── 3. K 线 ──
        emit("【3】拉取 K 线（覆盖全部采集代码，含新入名单的基金）")
        await sch.job_fetch_kline()
        _, total_after = await _nav_coverage(target)
        print(f"  fund_daily[{target}] 行数 {total_after}")

        # ── 4. 日终入库 ──
        emit("【4】日终入库 daily_save")
        if not (gate_ok or force):
            print("  已按闸门跳过。")
            return 0
        from mq import publish_event
        mid = await publish_event("daily_save", {"date": target.isoformat()})
        if not mid:
            print("  事件发布失败！")
            return 1
        print(f"  已发布事件 id={mid}，等待消费者处理 …")

        loop = asyncio.get_event_loop()
        deadline = loop.time() + DAILY_SAVE_WAIT
        last = -1
        while loop.time() < deadline:
            await asyncio.sleep(10)
            filled, tot = await _premium_coverage(target)
            if filled == last and filled > 0:
                break
            last = filled
            print(f"    premium_rate 已填充 {filled}/{tot} …")
        filled, tot = await _premium_coverage(target)
        pct = (filled * 100 // tot) if tot else 0
        print(f"\n  完成：premium_rate {filled}/{tot}（{pct}%）")
        if filled == 0:
            print("  ! 仍为 0，请检查消费者日志："
                  "journalctl -u jinkuaicha -n 100")
            return 1
        return 0
    finally:
        await sch.close_scheduler_http()
        await cache.close_redis()
        await database.dispose_engine()


def cli() -> int:
    parser = argparse.ArgumentParser(description="手动全量更新（带净值到位闸门）")
    parser.add_argument("--apply", action="store_true",
                        help="真正执行（默认只打印计划）")
    parser.add_argument("--date", type=str, default=None,
                        help="目标交易日 YYYY-MM-DD（默认北京时间昨天）")
    parser.add_argument("--force", action="store_true",
                        help="跳过净值到位闸门（慎用）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    return asyncio.run(main(apply=args.apply,
                            target=_target_date(args.date),
                            force=args.force))


if __name__ == "__main__":
    raise SystemExit(cli())
