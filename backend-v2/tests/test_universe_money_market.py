"""名单同步的货币基金拦截测试。

回归目标：场内货币基金**不能**进入 LOF/ETF 采集名单。

它们的"收盘价"是 100 元面值、数据源给的"净值"是每份日收益，量纲不同，
套 `(close-nav)/nav` 会算出几万 % 的溢价率并冲上榜首（#205 修过一轮）。

难点在于**名称规则拦不住**：腾讯给的行情名是"招商快线ETF""华宝添益ETF"
"银华日利ETF"，里面没有"货币"二字，只有 `fund_info.fund_type`
（"货币型-普通货币"）才认得出来。
"""
import pytest

from services import universe_service as u


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, engine):
        self._engine = engine

    async def execute(self, *args, **kwargs):
        if self._engine.exc:
            raise self._engine.exc
        return _FakeResult(self._engine.rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeEngine:
    def __init__(self, rows=None, exc=None):
        self.rows = rows or []
        self.exc = exc

    def connect(self):
        return _FakeConn(self)

    async def dispose(self):
        pass


class TestNameRuleIsInsufficient:
    """把"为什么必须再查一遍 fund_type"钉在测试里。"""

    @pytest.mark.parametrize("name", [
        "招商快线ETF", "快钱ETF汇添富", "华安日日鑫ETF", "华泰天天金ETF",
        "鹏华添利ETF", "招商财富宝ETF", "银华日利ETF", "华宝添益ETF",
    ])
    def test_tencent_names_do_not_look_like_money_market(self, name):
        assert u.is_money_market(name) is False

    def test_names_with_keyword_are_caught(self):
        assert u.is_money_market("华宝现金添益交易型货币市场基金") is True
        assert u.is_money_market("易方达保证金收益货币市场基金") is True

    def test_stock_etf_with_cashflow_is_not_money_market(self):
        """"自由现金流"ETF 是股票型，不能因为含关键词被误杀。"""
        assert u.is_money_market("招商中证800自由现金流ETF") is False


class TestIsExchangeListed:
    @pytest.mark.parametrize("code", ["510300", "159915", "501050", "180101"])
    def test_exchange_codes(self, code):
        assert u.is_exchange_listed(code) is True

    @pytest.mark.parametrize("code", [
        "023226",  # 场外 ETF-FOF
        "005613",  # 场外
        "000673",
        "019567",
    ])
    def test_otc_codes(self, code):
        assert u.is_exchange_listed(code) is False


class TestLoadMoneyMarketCodes:
    @pytest.mark.asyncio
    async def test_returns_codes(self, monkeypatch):
        rows = [("511990",), ("511880",), ("159003",)]
        monkeypatch.setattr(u, "create_async_engine",
                            lambda *a, **k: _FakeEngine(rows=rows))
        assert await u.load_money_market_codes() == {"511990", "511880", "159003"}

    @pytest.mark.asyncio
    async def test_fails_open_on_db_error(self, monkeypatch):
        """库读不到时返回空集合，宁可少拦一道，也不能让同步整体失败。"""
        monkeypatch.setattr(
            u, "create_async_engine",
            lambda *a, **k: _FakeEngine(exc=RuntimeError("db down")))
        assert await u.load_money_market_codes() == set()
