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
