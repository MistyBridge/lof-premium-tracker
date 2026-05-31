"""
M1 基础设施层 — 14 项冒烟测试
pytest tests/test_m1_smoke.py -v
"""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── T1: Settings 必填项缺失 → ValidationError ───────────────

class TestT01Settings:

    def test_missing_database_url(self):
        from pydantic import ValidationError
        from config import Settings
        with pytest.raises(ValidationError):
            Settings(SUPABASE_JWT_SECRET="x", _env_file=None)

    def test_missing_jwt_secret(self):
        from pydantic import ValidationError
        from config import Settings
        with pytest.raises(ValidationError):
            Settings(DATABASE_URL="postgresql+asyncpg://x:x@h/d", _env_file=None)

    def test_valid_settings(self):
        from config import Settings
        s = Settings(
            DATABASE_URL="postgresql+asyncpg://x:x@h/d",
            SUPABASE_JWT_SECRET="s", _env_file=None,
        )
        assert s.PORT == 8000


# ── T2: migration SQL 完整性 ────────────────────────────────

class TestT02Migration:

    def test_16_tables_sql(self):
        from migration import TABLES_SQL, EXPECTED_TABLES
        assert len(TABLES_SQL) == 16
        assert len(EXPECTED_TABLES) == 16

    def test_asset_daily_is_partitioned(self):
        from migration import TABLES_SQL
        p = [s for s in TABLES_SQL if "PARTITION BY" in s]
        assert len(p) == 1 and "asset_daily" in p[0]


# ── T3: trade_calendar 已知交易日 → True ────────────────────

class TestT03TradeCalendar:

    def _inject(self, cal: dict, loaded: bool):
        import trade_calendar as tc
        self._old_cal, self._old_loaded = tc._calendar.copy(), tc._calendar_loaded
        tc._calendar, tc._calendar_loaded = cal, loaded

    def _restore(self):
        import trade_calendar as tc
        tc._calendar, tc._calendar_loaded = self._old_cal, self._old_loaded

    def test_trading_day_true(self):
        import trade_calendar as tc
        self._inject({date(2026, 5, 29): True}, True)
        assert tc.is_trading_day(date(2026, 5, 29)) is True
        self._restore()

    def test_non_trading_day_false(self):
        import trade_calendar as tc
        self._inject({date(2026, 5, 30): False}, True)
        assert tc.is_trading_day(date(2026, 5, 30)) is False
        self._restore()

    def test_no_calendar_false(self):
        import trade_calendar as tc
        self._inject({}, False)
        assert tc.is_trading_day(date(2026, 5, 29)) is False
        self._restore()


# ── T4: cache 读写 + 降级 ──────────────────────────────────

class TestT04Cache:

    @pytest.mark.asyncio
    async def test_set_get_roundtrip(self):
        import cache as cm
        old = cm._pool
        mock = AsyncMock()
        data = {"code": "160644"}
        mock.get = AsyncMock(return_value=json.dumps(data))
        mock.set = AsyncMock()
        cm._pool = mock
        await cm.cache_set("k", data, 60)
        assert await cm.cache_get("k") == data
        cm._pool = old

    @pytest.mark.asyncio
    async def test_redis_down_returns_none(self):
        import cache as cm
        old = cm._pool
        mock = AsyncMock()
        mock.get = AsyncMock(side_effect=ConnectionError)
        cm._pool = mock
        assert await cm.cache_get("k") is None
        cm._pool = old

    @pytest.mark.asyncio
    async def test_safe_set_realtime_rejects_partial(self):
        import cache as cm
        old = cm._pool
        mock = AsyncMock()
        old_data = {str(i): i for i in range(100)}
        mock.get = AsyncMock(return_value=json.dumps(old_data))
        mock.set = AsyncMock()
        cm._pool = mock
        new_data = {str(i): i for i in range(50)}
        assert await cm.safe_set_realtime(new_data) is False
        mock.set.assert_not_called()
        cm._pool = old


# ── T5: mq publish → consume → ack ─────────────────────────

class TestT05MQ:

    @pytest.mark.asyncio
    async def test_publish_consume_ack(self):
        import cache as cm
        import mq
        old = cm._pool
        mock = AsyncMock()
        mock.xadd = AsyncMock(return_value="1-0")
        mock.xreadgroup = AsyncMock(return_value=[
            ("stream:events", [("1-0", {
                "type": "realtime",
                "data": json.dumps({"count": 1500}),
                "ts": "2026-05-30T12:00:00Z",
            })]),
        ])
        mock.xack = AsyncMock()
        cm._pool = mock
        mq._pool = mock

        msg_id = await mq.publish_event("realtime", {"count": 1500})
        assert msg_id == "1-0"
        events = await mq.consume_events(count=1, block_ms=100)
        assert len(events) == 1
        assert events[0]["type"] == "realtime"
        await mq.ack_event("1-0")
        mock.xack.assert_called_once()
        cm._pool = old


# ── T6: metrics record_fetch ───────────────────────────────

class TestT06Metrics:

    def test_record_fetch_success_and_fail(self):
        from metrics import Metrics
        m = Metrics()
        m.record_fetch("push2", True, 150.5)
        m.record_fetch("push2", False, 0, business_error=True)
        assert m.fetch_status["push2"]["success"] == 1
        assert m.fetch_status["push2"]["fail"] == 1
        assert m.fetch_status["push2"]["business_error"] == 1

    def test_get_metrics_summary(self):
        from metrics import Metrics
        m = Metrics()
        m.record_fetch("src", True, 100)
        m.record_api_request()
        m.record_db_query(5.0)
        m.record_cache_hit()
        m.record_cache_miss()
        r = m.get_metrics()
        assert r["api_requests"] == 1
        assert r["cache_hit_rate"] == 50.0


# ── T7: ensure_partition ────────────────────────────────────

class TestT07Partition:

    @pytest.mark.asyncio
    async def test_creates_new_partition(self):
        from migration import ensure_partition
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=False)
        conn.execute = AsyncMock()
        await ensure_partition(conn, date(2026, 7, 15))
        sql = conn.execute.call_args[0][0]
        assert "asset_daily_202607" in sql

    @pytest.mark.asyncio
    async def test_skips_existing(self):
        from migration import ensure_partition
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        conn.execute = AsyncMock()
        await ensure_partition(conn, date(2026, 7, 15))
        conn.execute.assert_not_called()


# ── T8: get_latest_trading_date ─────────────────────────────

class TestT08LatestDate:

    def test_returns_recent_trading_day(self):
        import trade_calendar as tc
        old_cal, old_loaded = tc._calendar.copy(), tc._calendar_loaded
        today = date.today()
        tc._calendar_loaded = True
        tc._calendar = {
            today: False,
            today - timedelta(days=1): False,
            today - timedelta(days=2): True,
        }
        assert tc.get_latest_trading_date() == today - timedelta(days=2)
        tc._calendar, tc._calendar_loaded = old_cal, old_loaded


# ── T9: json_serializer ────────────────────────────────────

class TestT09JsonSerializer:

    def test_datetime(self):
        from database import json_serializer
        dt = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
        assert "2026-05-30" in json_serializer(dt)

    def test_decimal(self):
        from database import json_serializer
        assert json_serializer(Decimal("3.14")) == pytest.approx(3.14)

    def test_unsupported_raises(self):
        from database import json_serializer
        with pytest.raises(TypeError):
            json_serializer(set())


# ── T10: models 16 张表 ────────────────────────────────────

class TestT10Models:

    def test_16_orm_classes(self):
        import models
        classes = [
            getattr(models, n) for n in dir(models)
            if hasattr(getattr(models, n), "__tablename__")
        ]
        assert len(classes) == 16

    def test_tablenames_in_expected(self):
        import models
        from migration import EXPECTED_TABLES
        for n in dir(models):
            cls = getattr(models, n)
            if hasattr(cls, "__tablename__"):
                assert cls.__tablename__ in EXPECTED_TABLES


# ── T11: constants 关键常量 ─────────────────────────────────

class TestT11Constants:

    def test_critical_constants(self):
        from constants import (
            PREMIUM_RATE_WARN, PARTIAL_DATA_THRESHOLD,
            STREAM_KEY, PAGE_SIZE_MAX,
        )
        assert PREMIUM_RATE_WARN == 50
        assert PARTIAL_DATA_THRESHOLD == 80
        assert STREAM_KEY == "stream:events"


# ── T12: exceptions 层级 + 错误码 ──────────────────────────

class TestT12Exceptions:

    def test_hierarchy(self):
        from exceptions import (
            AppException, BadRequestException,
            UnauthorizedException, ForbiddenException,
            NotFoundException, ConflictException,
        )
        assert issubclass(BadRequestException, AppException)
        assert issubclass(UnauthorizedException, AppException)
        assert issubclass(ConflictException, AppException)

    def test_error_codes(self):
        from exceptions import (
            BadRequestException, TokenInvalidException,
            AdminRequiredException, NotFoundException,
        )
        assert BadRequestException().code == 40001
        assert TokenInvalidException().code == 40101
        assert AdminRequiredException().code == 40301
        assert NotFoundException().code == 40400


# ── T13: cache lock ────────────────────────────────────────

class TestT13CacheLock:

    @pytest.mark.asyncio
    async def test_acquire_release(self):
        import cache as cm
        old = cm._pool
        mock = AsyncMock()
        mock.set = AsyncMock(return_value=True)
        mock.delete = AsyncMock()
        cm._pool = mock
        assert await cm.acquire_lock("lock:x") is True
        await cm.release_lock("lock:x")
        cm._pool = old


# ── T14: disk usage ─────────────────────────────────────────

class TestT14DiskUsage:

    def test_returns_valid_pct(self):
        from metrics import get_disk_usage_pct
        pct = get_disk_usage_pct()
        assert isinstance(pct, float)
        assert 0 <= pct <= 100
