"""净值归位（processors/nav_sync.py）测试。

回归目标：`fund_daily` 最新交易日行的净值必须取自 "nav_date <= 该交易日 的
最新净值"，且**每次都要重新归位**。曾经的实现带 `AND fd.nav IS NULL`，
补过一次（哪怕补的是滞后净值）就再也不更新，导致跨境 ETF 的溢价率
把两个交易日的行情混算（159509 虚高 32.07%，实际 27.93%）。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from processors import nav_sync


class _FakeResult:
    def __init__(self, rowcount=0, rows=None):
        self.rowcount = rowcount
        self._rows = rows or []

    def fetchall(self):
        return self._rows

    def scalar(self):
        return self._rows[0][0] if self._rows else None


class _FakeSession:
    def __init__(self, rowcount=0, rows=None):
        self.executed = []
        self._result = _FakeResult(rowcount, rows)

    async def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params))
        return self._result


class TestSyncSqlInvariants:
    """把修复的关键语义钉在 SQL 上，防止回归。"""

    def test_picks_latest_nav_not_after_trade_date(self):
        sql = str(nav_sync.SYNC_SQL)
        assert "nav_date <= lc.td" in sql, "必须限定净值的日期不晚于该交易日"

    def test_orders_by_nav_date_desc(self):
        sql = str(nav_sync.SYNC_SQL)
        assert "ORDER BY nav_date DESC" in sql, "必须取最新的那一条净值"

    def test_no_one_shot_null_guard(self):
        """不得再用 `fd.nav IS NULL` 当作"只补一次"的闸门。"""
        sql = str(nav_sync.SYNC_SQL)
        assert "fd.nav IS NULL" not in sql
        assert "nav IS NULL" not in sql.split("UPDATE")[-1].split("FROM pick")[0], \
            "更新条件里不应再出现 nav IS NULL"

    def test_recomputes_premium_rate_from_new_nav(self):
        sql = str(nav_sync.SYNC_SQL)
        assert "premium_rate" in sql
        assert "round((fd.close - pick.nav) / pick.nav * 100, 4)" in sql

    def test_updates_latest_close_row_only(self):
        sql = str(nav_sync.SYNC_SQL)
        assert "close IS NOT NULL" in sql
        assert "MAX(trade_date)" in sql
        assert "fd.trade_date = pick.td" in sql


class TestSyncNavToLatestRow:
    @pytest.mark.asyncio
    async def test_empty_codes_short_circuits(self):
        session = _FakeSession()
        assert await nav_sync.sync_nav_to_latest_row(session, []) == 0
        assert session.executed == []

    @pytest.mark.asyncio
    async def test_filters_falsy_and_dedupes(self):
        session = _FakeSession(rowcount=2)
        changed = await nav_sync.sync_nav_to_latest_row(
            session, ["159509", "", None, "159509", "513100"])
        assert changed == 2
        _, params = session.executed[0]
        assert params["codes"] == ["159509", "513100"]

    @pytest.mark.asyncio
    async def test_returns_rowcount(self):
        session = _FakeSession(rowcount=7)
        assert await nav_sync.sync_nav_to_latest_row(session, ["510300"]) == 7

    @pytest.mark.asyncio
    async def test_rowcount_none_becomes_zero(self):
        class _NoRowcount:
            rowcount = None

            def fetchall(self):
                return []

        class _S:
            async def execute(self, stmt, params=None):
                return _NoRowcount()

        assert await nav_sync.sync_nav_to_latest_row(_S(), ["510300"]) == 0


class TestListMisaligned:
    @pytest.mark.asyncio
    async def test_maps_rows(self):
        from datetime import date

        rows = [("159509", "景顺长城纳斯达克科技ETF", date(2026, 9, 22),
                 3.049, 2.3833, date(2026, 9, 21), 1, 27.9316)]
        session = _FakeSession(rows=rows)
        out = await nav_sync.list_misaligned(session, limit=10)
        assert out == [{
            "code": "159509",
            "name": "景顺长城纳斯达克科技ETF",
            "trade_date": "2026-09-22",
            "close": 3.049,
            "nav": 2.3833,
            "nav_date": "2026-09-21",
            "lag_days": 1,
            "premium_rate": 27.9316,
        }]

    @pytest.mark.asyncio
    async def test_handles_nulls(self):
        from datetime import date

        rows = [("515293", None, date(2026, 9, 22), None, None, None, None, None)]
        session = _FakeSession(rows=rows)
        out = await nav_sync.list_misaligned(session)
        assert out[0]["name"] == ""
        assert out[0]["nav"] is None
        assert out[0]["lag_days"] is None

    def test_only_counts_rows_that_actually_have_a_nav(self):
        """完全没有净值不算"错位"（场内货币基金已按 PR#205 主动清空净值），
        否则 135 条报告里 80 多条是噪声，把真正要修的那几十条淹没了。"""
        sql = str(nav_sync.MISALIGNED_SQL)
        assert "fd.nav IS NOT NULL" in sql


class TestUpsertNavSqlInvariants:
    """净值写入必须让同一行里的 nav 与 premium_rate 口径一致。"""

    def test_nav_lands_on_its_own_date_row(self):
        sql = str(nav_sync.UPSERT_NAV_SQL)
        assert "trade_date" in sql
        # 净值自身日期既做 trade_date 又做 nav_date
        assert sql.count(":nav_date") >= 2

    def test_conflict_recomputes_premium_rate(self):
        sql = str(nav_sync.UPSERT_NAV_SQL)
        assert "ON CONFLICT (code, trade_date) DO UPDATE" in sql
        assert "round((fund_daily.close - EXCLUDED.nav) / EXCLUDED.nav * 100, 4)" in sql

    def test_keeps_old_premium_when_close_missing(self):
        """净值先于 K 线到货时不能凭空造溢价率。"""
        sql = str(nav_sync.UPSERT_NAV_SQL)
        assert "ELSE fund_daily.premium_rate" in sql

    def test_has_no_op_guard_for_meaningful_rowcount(self):
        sql = str(nav_sync.UPSERT_NAV_SQL)
        assert "WHERE fund_daily.nav IS DISTINCT FROM EXCLUDED.nav" in sql


class TestUpsertNavRows:
    @pytest.mark.asyncio
    async def test_empty_short_circuits(self):
        session = _FakeSession()
        assert await nav_sync.upsert_nav_rows(session, []) == 0
        assert session.executed == []

    @pytest.mark.asyncio
    async def test_filters_invalid_rows(self):
        session = _FakeSession(rowcount=1)
        await nav_sync.upsert_nav_rows(session, [
            {"code": "510300", "nav": 4.6179, "nav_date": "2026-09-22"},  # ok
            {"code": "", "nav": 1.0, "nav_date": "2026-09-22"},           # 无代码
            {"code": "510300", "nav": None, "nav_date": "2026-09-22"},    # 无净值
            {"code": "510300", "nav": 1.0, "nav_date": None},             # 无净值日
            {"code": "510300", "nav": 0, "nav_date": "2026-09-22"},       # 净值非正
            {"code": "510300", "nav": -1, "nav_date": "2026-09-22"},      # 净值非正
            {"code": "510300", "nav": "abc", "nav_date": "2026-09-22"},   # 非数字
            {"code": "510300", "nav": 1.0, "nav_date": "not-a-date"},     # 坏日期
        ])
        _, params = session.executed[0]
        assert len(params) == 1
        assert params[0]["code"] == "510300"
        assert params[0]["nav"] == 4.6179

    @pytest.mark.asyncio
    async def test_parses_iso_date_string(self):
        from datetime import date

        session = _FakeSession(rowcount=1)
        await nav_sync.upsert_nav_rows(
            session, [{"code": "159509", "nav": 2.3833, "nav_date": "2026-09-21"}])
        _, params = session.executed[0]
        assert params[0]["nav_date"] == date(2026, 9, 21)

    @pytest.mark.asyncio
    async def test_accepts_date_object(self):
        from datetime import date

        session = _FakeSession(rowcount=1)
        await nav_sync.upsert_nav_rows(
            session, [{"code": "159509", "nav": 2.3833, "nav_date": date(2026, 9, 21)}])
        _, params = session.executed[0]
        assert params[0]["nav_date"] == date(2026, 9, 21)

    @pytest.mark.asyncio
    async def test_returns_rowcount(self):
        session = _FakeSession(rowcount=5)
        assert await nav_sync.upsert_nav_rows(
            session, [{"code": "510300", "nav": 1.0, "nav_date": "2026-09-22"}]) == 5


class TestMergeNavMap:
    """nav:all 必须"合并且不倒退"，否则提高采集频率只会放大风险。"""

    def test_keeps_existing_codes_not_in_incoming(self):
        """一次部分失败不能把其它基金从缓存里抹掉（daily_save 依赖它）。"""
        prev = {"510300": {"nav": 1.0, "nav_date": "2026-09-22"},
                "159509": {"nav": 2.3833, "nav_date": "2026-09-21"}}
        incoming = {"510300": {"nav": 1.1, "nav_date": "2026-09-22"}}
        out = nav_sync.merge_nav_map(prev, incoming)
        assert set(out) == {"510300", "159509"}
        assert out["510300"]["nav"] == 1.1
        assert out["159509"]["nav"] == 2.3833

    def test_does_not_overwrite_newer_nav_with_older(self):
        """lsjz 偶尔返回滞后的行；整体替换会把刚拿到的新净值打回旧值。"""
        prev = {"159509": {"nav": 2.3833, "nav_date": "2026-09-21"}}
        incoming = {"159509": {"nav": 2.3086, "nav_date": "2026-09-18"}}
        out = nav_sync.merge_nav_map(prev, incoming)
        assert out["159509"]["nav"] == 2.3833
        assert out["159509"]["nav_date"] == "2026-09-21"

    def test_accepts_newer_nav(self):
        prev = {"159509": {"nav": 2.3086, "nav_date": "2026-09-18"}}
        incoming = {"159509": {"nav": 2.3833, "nav_date": "2026-09-21"}}
        assert nav_sync.merge_nav_map(prev, incoming)["159509"]["nav"] == 2.3833

    def test_same_date_correction_is_applied(self):
        """同日修订（净值更正）必须能覆盖。"""
        prev = {"510300": {"nav": 4.6179, "nav_date": "2026-09-22"}}
        incoming = {"510300": {"nav": 4.6180, "nav_date": "2026-09-22"}}
        assert nav_sync.merge_nav_map(prev, incoming)["510300"]["nav"] == 4.6180

    def test_handles_date_objects(self):
        from datetime import date

        prev = {"510300": {"nav": 1.0, "nav_date": date(2026, 9, 22)}}
        incoming = {"510300": {"nav": 2.0, "nav_date": date(2026, 9, 18)}}
        assert nav_sync.merge_nav_map(prev, incoming)["510300"]["nav"] == 1.0

    def test_ignores_junk(self):
        prev = {"510300": {"nav": 1.0, "nav_date": "2026-09-22"}}
        incoming = {"": {"nav": 9.9, "nav_date": "2026-09-23"},
                    "510300": "not-a-dict"}
        out = nav_sync.merge_nav_map(prev, incoming)
        assert set(out) == {"510300"}
        assert out["510300"]["nav"] == 1.0

    def test_handles_empty_inputs(self):
        assert nav_sync.merge_nav_map({}, {}) == {}
        assert nav_sync.merge_nav_map(None, None) == {}
        assert nav_sync.merge_nav_map(
            {}, {"510300": {"nav": 1.0, "nav_date": "2026-09-22"}}
        )["510300"]["nav"] == 1.0

    def test_missing_nav_date_sorts_lowest(self):
        """没有 nav_date 的条目视为最旧，不能覆盖有日期的。"""
        prev = {"510300": {"nav": 1.0, "nav_date": "2026-09-22"}}
        incoming = {"510300": {"nav": 9.9}}
        assert nav_sync.merge_nav_map(prev, incoming)["510300"]["nav"] == 1.0
