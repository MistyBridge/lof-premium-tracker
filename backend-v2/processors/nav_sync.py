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


# 体检用：列出当前仍处于"净值日期 ≠ 交易日"的最新行（只读）
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
WHERE fd.nav_date IS DISTINCT FROM fd.trade_date
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
