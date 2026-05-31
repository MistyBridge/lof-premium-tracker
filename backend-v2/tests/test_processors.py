"""
M4 处理层 — 单元测试（不依赖 DB/Redis）
pytest tests/test_processors.py -v
"""
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── normalize 测试 ──────────────────────────────────────────

class TestNormalize:

    def test_to_optional_float_zero(self):
        """0 不是空值"""
        from processors.normalize import to_optional_float
        assert to_optional_float("0") == 0.0
        assert to_optional_float(0) == 0.0

    def test_to_optional_float_none_variants(self):
        """空值变体返回 None"""
        from processors.normalize import to_optional_float
        for v in ("", "-", "--", "暂无", "N/A", "nan", "NaN", None):
            assert to_optional_float(v) is None, f"expected None for {v!r}"

    def test_to_optional_float_decimal(self):
        """Decimal 转 float"""
        from processors.normalize import to_optional_float
        assert to_optional_float(Decimal("3.14")) == pytest.approx(3.14)

    def test_clean_code_normal(self):
        from processors.normalize import clean_code
        assert clean_code("160644") == "160644"

    def test_clean_code_with_spaces_and_commas(self):
        from processors.normalize import clean_code
        assert clean_code(" 160,644 ") == "160644"

    def test_clean_code_zfill(self):
        from processors.normalize import clean_code
        assert clean_code("1234") == "001234"

    def test_clean_code_invalid(self):
        from processors.normalize import clean_code
        assert clean_code("abc") is None
        assert clean_code(None) is None

    def test_normalize_realtime_push2(self):
        """push2 字段正确映射"""
        from processors.normalize import normalize_realtime
        raw = {
            "f12": "160644", "f14": "测试基金",
            "f2": 1.5, "f3": 2.5, "f5": 10000,
            "f6": 1500000, "f13": "0",
        }
        result = normalize_realtime(raw, source="push2")
        assert result["code"] == "160644"
        assert result["name"] == "测试基金"
        assert result["realtime_price"] == 1.5
        assert result["fetch_source"] == "push2"

    def test_normalize_realtime_tencent_missing_fields(self):
        """腾讯数据缺失字段为 None，不报错"""
        from processors.normalize import normalize_realtime
        raw = {"code": "160644", "price": 1.5}
        result = normalize_realtime(raw, source="tencent")
        assert result["code"] == "160644"
        assert result["realtime_nav"] is None
        assert result["fetch_source"] == "tencent"


# ── validator 测试 ──────────────────────────────────────────

class TestValidator:

    def test_validate_realtime_price_zero_kept(self):
        """price <= 0 标记异常但保留"""
        from processors.validator import validate_realtime
        r = {"code": "160644", "realtime_price": 0}
        result = validate_realtime(r)
        assert result.get("risk_warning") == "price_zero"
        assert result["realtime_price"] == 0

    def test_validate_realtime_invalid_code_discarded(self):
        """code 无效 → 返回空 dict"""
        from processors.validator import validate_realtime
        assert validate_realtime({"code": "abc"}) == {}
        assert validate_realtime({"code": None}) == {}

    def test_validate_nav_negative_discarded(self):
        """nav <= 0 丢弃"""
        from processors.validator import validate_nav
        assert validate_nav({"code": "160644", "nav": -1, "nav_date": "2026-05-30"}) is None
        assert validate_nav({"code": "160644", "nav": 0, "nav_date": "2026-05-30"}) is None

    def test_validate_nav_valid(self):
        from processors.validator import validate_nav
        r = {"code": "160644", "nav": 1.5, "nav_date": "2026-05-30"}
        assert validate_nav(r) == r

    def test_validate_kline_close_zero_discarded(self):
        from processors.validator import validate_kline
        assert validate_kline({"code": "160644", "close": 0, "trade_date": "2026-05-30"}) is None

    def test_mark_limit_status(self):
        from processors.validator import mark_limit_status
        r = {"realtime_price": 1.5, "limit_up": 1.5, "limit_down": 1.0}
        result = mark_limit_status(r)
        assert result.get("risk_warning") == "涨停标的"

    def test_deduplicate(self):
        from processors.validator import deduplicate
        records = [
            {"code": "160644", "v": 1},
            {"code": "160644", "v": 2},
            {"code": "510300", "v": 3},
        ]
        result = deduplicate(records, key="code")
        assert len(result) == 2
        codes = {r["code"] for r in result}
        assert codes == {"160644", "510300"}


# ── calculator 测试 ─────────────────────────────────────────

class TestCalculator:

    def test_calc_premium_rate(self):
        from processors.calculator import calc_premium_rate
        # (2.0 - 1.8) / 1.8 * 100 = 11.1111
        assert calc_premium_rate(2.0, 1.8) == pytest.approx(11.1111, abs=0.001)

    def test_calc_premium_rate_nav_zero(self):
        from processors.calculator import calc_premium_rate
        assert calc_premium_rate(2.0, 0) is None
        assert calc_premium_rate(2.0, None) is None

    def test_calc_turnover_rate(self):
        from processors.calculator import calc_turnover_rate
        # volume=10000手, float_share=100万份
        # = 10000*100 / (100*10000) * 100 = 1.0
        assert calc_turnover_rate(10000, 100) == pytest.approx(1.0)

    def test_calc_turnover_rate_zero_share(self):
        from processors.calculator import calc_turnover_rate
        assert calc_turnover_rate(10000, 0) is None
        assert calc_turnover_rate(None, 100) is None

    def test_calc_change_pct(self):
        from processors.calculator import calc_change_pct
        # (2.0 - 1.8) / 1.8 * 100
        assert calc_change_pct(2.0, 1.8) == pytest.approx(11.1111, abs=0.001)

    def test_calc_change_pct_prev_zero(self):
        from processors.calculator import calc_change_pct
        assert calc_change_pct(2.0, 0) is None

    def test_calc_est_return_no_redeem_fee(self):
        """赎回费率 None → 返回 None"""
        from processors.calculator import calc_est_return
        assert calc_est_return(5.0, 0.5, None) is None

    def test_calc_est_return_premium(self):
        """溢价套利"""
        from processors.calculator import calc_est_return
        result = calc_est_return(5.0, 0.15, 0.5, commission=0.0001, fee_discount=0.1)
        # net = 5/100 - 0.15*0.1/100 - 0.5/100 - 0.0001*2
        assert isinstance(result, float)

    def test_calc_premium_3d(self):
        from processors.calculator import calc_premium_3d
        recent = [
            {"premium_rate": 10.0},
            {"premium_rate": 12.0},
            {"premium_rate": 8.0},
        ]
        assert calc_premium_3d(recent) == pytest.approx(10.0)

    def test_calc_premium_3d_empty(self):
        from processors.calculator import calc_premium_3d
        assert calc_premium_3d([]) is None


# ── saver batch_upsert 测试 ─────────────────────────────────

class TestSaver:

    @pytest.mark.asyncio
    async def test_batch_upsert_success(self):
        """1500 条分 15 批全部成功"""
        from unittest.mock import AsyncMock, MagicMock
        from processors.saver import batch_upsert

        mock_model = MagicMock()
        mock_col = MagicMock()
        mock_col.name = "code"
        mock_model.__table__.columns = [mock_col]

        mock_session = AsyncMock()
        mock_session.begin = AsyncMock(return_value=AsyncMock(__aenter__=AsyncMock(), __aexit__=AsyncMock()))
        mock_session.execute = AsyncMock()

        factory = MagicMock(return_value=mock_session)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        records = [{"code": str(i).zfill(6)} for i in range(1500)]
        result = await batch_upsert(factory, mock_model, records, ["code"], batch_size=100)

        assert result["total"] == 1500
        assert result["success"] == 1500
        assert len(result["failed_batches"]) == 0

    @pytest.mark.asyncio
    async def test_batch_upsert_partial_failure(self):
        """部分批次失败，已提交的不回滚"""
        from unittest.mock import AsyncMock, MagicMock
        from processors.saver import batch_upsert

        mock_model = MagicMock()
        mock_col = MagicMock()
        mock_col.name = "code"
        mock_model.__table__.columns = [mock_col]

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                raise Exception("DB error batch 3")

        mock_session = AsyncMock()
        mock_session.begin = AsyncMock(return_value=AsyncMock(__aenter__=AsyncMock(), __aexit__=AsyncMock()))
        mock_session.execute = mock_execute

        factory = MagicMock(return_value=mock_session)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        records = [{"code": str(i).zfill(6)} for i in range(300)]
        result = await batch_upsert(factory, mock_model, records, ["code"], batch_size=100)

        assert result["total"] == 300
        assert result["success"] == 200  # 前 2 批成功
        assert len(result["failed_batches"]) == 1
