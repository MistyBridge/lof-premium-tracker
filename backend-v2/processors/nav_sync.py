"""
最新交易日行的净值归位。

背景（2026-09-23 修复）
────────────────────────────────────────────────────────────────
`fund_daily` 的净值有两条写入通路：

  1. **直写**  `INSERT (code, trade_date = nav_date, ...)`
     净值落在它自己的日期行上，天然对齐、可重复执行。

  2. **归位**  把"已知最新净值"补到该代码**最新交易日行**上，
     供物化视图 `fund_snapshot` 与列表页取用。

第 2 条的原实现（`scheduler.job_fetch_nav` 内联 SQL）带 `AND fd.nav IS NULL`：
只在行为空时补一次，**此后再也不会更新**。而跨境/QDII 基金的净值天生滞后
1~2 个交易日（海外市场收盘与净值披露时点决定），于是：

    09-22 08:00  归位时"最新净值"还是 09-18 的 → 09-22 行被写死成 09-18 的净值
    09-23 之后   09-21 的净值到货，09-22 行因 `nav IS NULL` 已不成立而永远不更新

结果是 `premium_rate = (09-22 收盘价 − 09-18 净值) / 09-18 净值`，
把两个交易日的行情混算，系统性虚高。实测 159509：

    错误值  32.07%   ← 用 09-18 净值 2.3086（当时库里最新）
    正确值  27.93%   ← 用 09-21 净值 2.3833（实际最新）

全市场 2026-09-22 当天共 146 行错位（ETF 73 / LOF 43 / 场内货币 30），
其中 37 只是溢价率最高的跨境 ETF —— 恰好是最受关注、最不该错的那批。

修复语义
────────────────────────────────────────────────────────────────
* 每次拉到净值都**重新归位**，不再依赖"只补一次"。
* 取 `nav_date <= 该交易日` 的最新净值：这正是该交易日"当时可知的最新净值"，
  也是 `DATA_DICTIONARY` 里 `nav_date <= trade_date` 的本意。
* `nav_date` 如实记录真实的净值日期，**不做日期伪装**；
  对齐的净值到货后由直写通路自动覆盖该行（trade_date == nav_date），
  因此错位的行会自愈。
* 归位改了净值就**同步重算 premium_rate**，否则旧溢价率会继续挂在页面上。
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional, Sequence

from sqlalchemy import text

logger = logging.getLogger("app")


# 每个 code 的"最新交易日行"（收盘价非空的那一行），取该行日期之前的最新净值。
# 用 CROSS JOIN LATERAL + LIMIT 1，命中索引 idx_daily_code_navdate (code, nav_date)。
SYNC_SQL = text("""
WITH latest_close AS (
    SELECT code, MAX(trade_date) AS td
    FROM fund_daily
    WHERE code = ANY(:codes)
      AND close IS NOT NULL
    GROUP BY code
),
pick AS (
    SELECT lc.code, lc.td, n.nav, n.nav_date, n.nav_type, n.nav_source
    FROM latest_close lc
    CROSS JOIN LATERAL (
        SELECT nav, nav_date, nav_type, nav_source
        FROM fund_daily
        WHERE code = lc.code
          AND nav IS NOT NULL
          AND nav_date <= lc.td
        ORDER BY nav_date DESC
        LIMIT 1
    ) n
)
UPDATE fund_daily fd SET
    nav          = pick.nav,
    nav_date     = pick.nav_date,
    nav_type     = pick.nav_type,
    nav_source   = pick.nav_source,
    premium_rate = CASE
        WHEN fd.close IS NOT NULL AND fd.close > 0 AND pick.nav > 0
        THEN round((fd.close - pick.nav) / pick.nav * 100, 4)
        ELSE fd.premium_rate
    END
FROM pick
WHERE fd.code = pick.code
  AND fd.trade_date = pick.td
  AND (
        fd.nav IS DISTINCT FROM pick.nav
     OR fd.nav_date IS DISTINCT FROM pick.nav_date
     OR fd.nav_type IS DISTINCT FROM pick.nav_type
     OR fd.nav_source IS DISTINCT FROM pick.nav_source
     OR (fd.close IS NOT NULL AND fd.close > 0 AND pick.nav > 0
         AND fd.premium_rate IS DISTINCT FROM
             round((fd.close - pick.nav) / pick.nav * 100, 4))
  )
""")


# 净值写入：净值落在**它自己的日期行**上（trade_date = nav_date），天然对齐。
#
# 关键在于 ON CONFLICT 时顺手把这一行的 premium_rate 也重算一遍：
# 该行此前可能挂着"用滞后净值算出来的"溢价率（daily_save 在当日净值还没发布时
# 会退回用最近历史净值），净值一旦对齐，溢价率必须跟着对齐，否则同一行里
# `nav` 是 T 日的、`premium_rate` 却是拿 T-1 日净值算的，自相矛盾。
# close 尚未到货时（净值早于 K 线）保持原值，不凭空造。
#
# WHERE 子句保证"没有实质变化就不写"，让 rowcount 仍然表示真正改动的行数。
UPSERT_NAV_SQL = text("""
INSERT INTO fund_daily
    (code, trade_date, nav, nav_date, nav_type, nav_source, premium_rate)
VALUES
    (:code, :nav_date, :nav, :nav_date, 'confirmed', 'lsjz', NULL)
ON CONFLICT (code, trade_date) DO UPDATE SET
    nav        = EXCLUDED.nav,
    nav_date   = EXCLUDED.nav_date,
    nav_type   = 'confirmed',
    nav_source = 'lsjz',
    premium_rate = CASE
        WHEN fund_daily.close IS NOT NULL AND fund_daily.close > 0
             AND EXCLUDED.nav > 0
        THEN round((fund_daily.close - EXCLUDED.nav) / EXCLUDED.nav * 100, 4)
        ELSE fund_daily.premium_rate
    END
WHERE fund_daily.nav IS DISTINCT FROM EXCLUDED.nav
   OR fund_daily.nav_date IS DISTINCT FROM EXCLUDED.nav_date
   OR fund_daily.nav_type IS DISTINCT FROM 'confirmed'
   OR fund_daily.nav_source IS DISTINCT FROM 'lsjz'
   OR (fund_daily.close IS NOT NULL AND fund_daily.close > 0
       AND EXCLUDED.nav > 0
       AND fund_daily.premium_rate IS DISTINCT FROM
           round((fund_daily.close - EXCLUDED.nav) / EXCLUDED.nav * 100, 4))
""")


async def upsert_nav_rows(session, items: Iterable[dict]) -> int:
    """把净值写入 `fund_daily`（按净值自身的日期成行），并保持同行溢价率自洽。

    Args:
        session: 已开启的 AsyncSession（调用方负责 commit）。
        items: [{code, nav, nav_date(date 或 'YYYY-MM-DD'), ...}, ...]

    Returns:
        真正发生变化的行数。
    """
    from datetime import date as _date

    params = []
    for item in items:
        code = item.get("code")
        nav = item.get("nav")
        nav_date = item.get("nav_date")
        if not code or not nav or not nav_date:
            continue
        if isinstance(nav_date, str):
            try:
                nav_date = _date.fromisoformat(nav_date)
            except (ValueError, TypeError):
                continue
        try:
            nav_val = float(nav)
        except (TypeError, ValueError):
            continue
        if nav_val <= 0:
            continue
        params.append({"code": code, "nav": nav_val, "nav_date": nav_date})

    if not params:
        return 0

    result = await session.execute(UPSERT_NAV_SQL, params)
    return result.rowcount or 0


# 体检用：列出"有净值、但净值日期 ≠ 交易日"的最新行（只读）
#
# 必须带 `fd.nav IS NOT NULL`：完全没有净值是另一种情况（例如场内货币基金
# 已按 PR#205 主动清空净值，那不适用溢价率公式），不该混进"错位"里，
# 否则报告的 135 条里会有 80 多条是噪声，真正要修的那 51 条反而被淹没。
MISALIGNED_SQL = text("""
WITH latest_close AS (
    SELECT code, MAX(trade_date) AS td
    FROM fund_daily
    WHERE close IS NOT NULL
    GROUP BY code
)
SELECT fd.code,
       COALESCE(fi.name, '')        AS name,
       fd.trade_date,
       fd.close,
       fd.nav,
       fd.nav_date,
       (fd.trade_date - fd.nav_date) AS lag_days,
       fd.premium_rate
FROM latest_close lc
JOIN fund_daily fd ON fd.code = lc.code AND fd.trade_date = lc.td
LEFT JOIN fund_info fi ON fi.code = fd.code
WHERE fd.nav IS NOT NULL
  AND fd.nav_date IS DISTINCT FROM fd.trade_date
ORDER BY lag_days DESC, fd.premium_rate DESC NULLS LAST
LIMIT :limit
""")


async def sync_nav_to_latest_row(
    session,
    codes: Iterable[str],
) -> int:
    """把每个 code 最新交易日行的净值归位到"该日可知的最新净值"。

    只改最新交易日行（收盘价非空的那一行），不影响历史行；历史溢价率由
    直写通路在净值到货时按 `nav_date == trade_date` 自然对齐。

    Args:
        session: 已开启的 AsyncSession（调用方负责 commit）。
        codes: 需要归位的基金代码。

    Returns:
        实际被更新的行数。
    """
    uniq: list[str] = [c for c in dict.fromkeys(codes) if c]
    if not uniq:
        return 0

    result = await session.execute(SYNC_SQL, {"codes": uniq})
    changed = result.rowcount or 0
    if changed:
        logger.info("[NAV_SYNC] 净值归位: %d 行（%d 只候选）", changed, len(uniq))
    return changed


def _nav_date_key(item: dict) -> str:
    """取 nav_date 的可比较形式。ISO 字符串按字典序排序即等价于按日期排序。"""
    nd = (item or {}).get("nav_date")
    if nd is None:
        return ""
    return nd if isinstance(nd, str) else str(nd)


def merge_nav_map(prev: dict, incoming: dict) -> dict:
    """把新拉到的净值并入既有缓存，返回合并结果。

    两条规则，都是为了"采集频率提高之后不把好数据弄坏"：

    1. **单调性**：不用 `nav_date` 更旧的条目覆盖更新的那条。
       采集一天跑十几次，只要有一次 lsjz 返回滞后的行（跨境/QDII 常见），
       整体替换就会把当天刚拿到的新净值打回旧值 —— 正是 #208 修的那类问题。

    2. **合并不替换**：一次部分失败不会让 `nav:all` 丢掉其它基金。
       `daily_save` 依赖这个键算溢价率，整个键被部分数据覆盖过一次，
       当日溢价率就会大面积缺失。原实现是直接 `cache_set`，有这个风险。
    """
    merged = dict(prev or {})
    for code, item in (incoming or {}).items():
        if not code or not isinstance(item, dict):
            continue
        old = merged.get(code)
        if old and _nav_date_key(old) > _nav_date_key(item):
            continue
        merged[code] = item
    return merged


async def list_misaligned(session, limit: int = 200) -> list[dict]:
    """只读体检：列出净值日期与交易日不一致的最新行。"""
    result = await session.execute(MISALIGNED_SQL, {"limit": int(limit)})
    return [
        {
            "code": r[0],
            "name": r[1] or "",
            "trade_date": str(r[2]) if r[2] else None,
            "close": float(r[3]) if r[3] is not None else None,
            "nav": float(r[4]) if r[4] is not None else None,
            "nav_date": str(r[5]) if r[5] else None,
            "lag_days": int(r[6]) if r[6] is not None else None,
            "premium_rate": float(r[7]) if r[7] is not None else None,
        }
        for r in result.fetchall()
    ]
