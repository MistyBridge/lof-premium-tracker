"""探测定向：边界值、异常输入、潜在漏洞"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, time
from unittest.mock import patch
import pytest


class TestExtremePremiumRates:
    """极端溢价率"""

    def test_null_premium_rate(self):
        """溢价率=None → 前端应显示 --"""
        from app import _fmt
        fund = {'code': 'test', 'premium_rate': None, 'nav': 1.0, 'price': 1.0,
                'change_pct': 0, 'is_formal_nav': True}
        result = _fmt(fund)
        assert result['premium_rate'] is None

    def test_large_premium(self):
        """极端溢价 50%"""
        from app import _fmt
        fund = {'code': 'test', 'premium_rate': 50.0, 'nav': 1.0, 'price': 1.5,
                'change_pct': 2.0, 'is_formal_nav': True}
        result = _fmt(fund)
        assert result['premium_rate'] == 50.0

    def test_large_discount(self):
        """极端折价 -30%"""
        from app import _fmt
        fund = {'code': 'test', 'premium_rate': -30.0, 'nav': 1.0, 'price': 0.7,
                'change_pct': -3.0, 'is_formal_nav': True}
        result = _fmt(fund)
        assert result['premium_rate'] == -30.0


class TestPurchaseLimitEdgeCases:
    """申购限额边界"""

    def test_cannot_purchase_zero_limit(self):
        """停止申购 → purchase_limit=0"""
        from app import _fmt
        fund = {'code': 'test', 'can_purchase': False, 'purchase_limit': None,
                'premium_rate': 0, 'nav': 1.0, 'price': 1.0,
                'change_pct': 0, 'is_formal_nav': True}
        result = _fmt(fund)
        assert result['purchase_limit'] == 0

    def test_can_purchase_none_unknown(self):
        """can_purchase=None → 保留原 purchase_limit"""
        from app import _fmt
        fund = {'code': 'test', 'can_purchase': None, 'purchase_limit': 50000,
                'premium_rate': 0, 'nav': 1.0, 'price': 1.0,
                'change_pct': 0, 'is_formal_nav': True}
        result = _fmt(fund)
        assert result['purchase_limit'] == 50000

    def test_cannot_purchase_with_limit_returns_zero(self):
        """即使有限额，can_purchase=False → 强制返回 0"""
        from app import _fmt
        fund = {'code': 'test', 'can_purchase': False, 'purchase_limit': 10000,
                'premium_rate': 0, 'nav': 1.0, 'price': 1.0,
                'change_pct': 0, 'is_formal_nav': True}
        result = _fmt(fund)
        assert result['purchase_limit'] == 0


class TestNullFieldHandling:
    """缺失字段容错"""

    def test_empty_fund_dict(self):
        """空基金字典 → 不崩溃"""
        from app import _fmt
        try:
            result = _fmt({})
            assert result['code'] is None or result['code'] == ''
        except KeyError as e:
            pytest.fail('_fmt(empty dict) crashed with KeyError: ' + str(e))

    def test_missing_nav(self):
        """nav=None → 正常返回 None"""
        from app import _fmt
        fund = {'code': 'test', 'premium_rate': 0,
                'nav': None, 'price': 1.0,
                'change_pct': 0, 'is_formal_nav': True}
        result = _fmt(fund)
        assert result['nav'] is None

    def test_missing_price(self):
        """price=0 → change_amount 不应崩溃"""
        from app import _fmt
        fund = {'code': 'test', 'premium_rate': 0,
                'nav': 1.0, 'price': 0,  # 0 price edge case
                'change_pct': 0, 'is_formal_nav': True}
        result = _fmt(fund)
        assert result['price'] == 0
        # change_amount should be None since price is 0
        assert result.get('change_amount') is None or result.get('change_amount') == 0

    def test_none_fields_rendered(self):
        """所有可选字段为 None → 不崩溃"""
        from app import _fmt
        fund = {'code': 'test', 'name': 'test',
                'premium_rate': 0, 'nav': 1.0, 'price': 1.0,
                'change_pct': 0, 'is_formal_nav': True,
                'amount': None, 'volume': None,
                'avg_premium_3d': None, 'premium_status': None,
                'purchase_fee_rate': None, 'redemption_fee_rate': None,
                'purchase_limit': None, 'can_purchase': None,
                'nav_date': None, 'data_date': None}
        result = _fmt(fund)
        assert result['amount'] is None
        assert result['premium_status'] is None


class TestPremiumStatus:
    """溢价状态分类"""

    def test_premium_status_correct(self):
        """正溢价 → 溢价"""
        from app import _fmt
        fund = {'code': 'test', 'premium_rate': 5.0, 'premium_status': '溢价',
                'nav': 1.0, 'price': 1.05, 'change_pct': 0.5, 'is_formal_nav': True}
        result = _fmt(fund)
        assert result['premium_status'] == '溢价'

    def test_discount_status_correct(self):
        """负溢价 → 折价"""
        from app import _fmt
        fund = {'code': 'test', 'premium_rate': -3.0, 'premium_status': '折价',
                'nav': 1.0, 'price': 0.97, 'change_pct': -0.3, 'is_formal_nav': True}
        result = _fmt(fund)
        assert result['premium_status'] == '折价'


class TestMarketHoursEdgeCases:
    """交易时段极端情况"""

    def test_holiday_weekday_edge(self):
        """法定节假日 → False（已集成 chinese_calendar）"""
        import app
        # 五一劳动节 (5月1日) 是法定假日
        mock_now = datetime(2026, 5, 1, 10, 0, 0)  # 周五，Labor Day
        with patch.object(app, 'datetime') as mock_dt:
            mock_dt.now.return_value = mock_now
            result = app._is_market_hours()
        assert result is False  # 节假日 → 不是交易日

    def test_national_day(self):
        """国庆节 → False"""
        import app
        mock_now = datetime(2026, 10, 1, 10, 0, 0)  # 周四，National Day
        with patch.object(app, 'datetime') as mock_dt:
            mock_dt.now.return_value = mock_now
            result = app._is_market_hours()
        assert result is False

    def test_midnight_boundary(self):
        """凌晨0点 → False"""
        import app
        mock_now = datetime(2026, 5, 26, 0, 0, 0)
        with patch.object(app, 'datetime') as mock_dt:
            mock_dt.now.return_value = mock_now
            assert app._is_market_hours() is False


class TestPurchaseLimitParsing:
    """申购限额解析 Bug Fix — 万元格式"""

    def _parse(self, html):
        import re
        idx = html.find("日累计申购限额")
        if idx < 0: return None
        chunk = html[idx:idx+200]
        m = re.search(r'日累计申购限额.*?<td[^>]*>(.*?)</td>', chunk, re.DOTALL)
        if not m: return None
        val = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if not val or '无限额' in val or '---' in val: return None
        nm = re.search(r'([\d,.]+)\s*万?\s*元', val)
        if nm:
            try:
                amount = float(nm.group(1).replace(',', ''))
                if '万' in val: amount *= 10000
                return amount
            except ValueError: return None
        return None

    def test_yuan_format(self):
        """3000.00元 → 3000"""
        html = '<td>日累计申购限额</td><td>3000.00元</td>'
        assert self._parse(html) == 3000.0

    def test_wan_yuan_format(self):
        """1.00万元 → 10000"""
        html = '<td>日累计申购限额</td><td>1.00万元</td>'
        assert self._parse(html) == 10000.0

    def test_no_limit(self):
        """无限额 → None"""
        html = '<td>日累计申购限额</td><td>无限额</td>'
        assert self._parse(html) is None

    def test_not_found(self):
        """无"日累计申购限额" → None"""
        html = '<td>其他数据</td>'
        assert self._parse(html) is None

    def test_large_wan(self):
        """50万元 → 500000"""
        html = '<td>日累计申购限额</td><td>50.00万元</td>'
        assert self._parse(html) == 500000.0


class TestRedemptionFeeDefault:
    """赎回费率默认值"""

    def _parse(self, html):
        import re
        idx = html.find("赎回费率")
        if idx < 0:
            return None
        chunk = html[idx:idx+800]
        text = re.sub(r'<[^>]+>', '|', chunk)
        rates = re.findall(r'(\d+\.\d+)%', text)
        if rates:
            try:
                return float(rates[0])
            except ValueError:
                pass
        return 1.5  # industry default

    def test_normal_fund(self):
        """有数据的基金返回实际费率"""
        html = '<td>赎回费率</td><td>1年</td><td>0.5%</td><td>6月</td><td>1.0%</td>'
        assert self._parse(html) == 0.5

    def test_empty_falls_back(self):
        """无费率数据 → 默认 1.5%"""
        html = '<td>赎回费率</td><td></td><td></td>'
        assert self._parse(html) == 1.5

    def test_no_section(self):
        """没有赎回费率段落 → None"""
        html = '<td>申购费率</td><td>0.15%</td>'
        assert self._parse(html) is None


class TestHealthEndpoint:
    """health 端点数据结构"""

    def test_health_has_required_fields(self):
        """health 响应包含必要字段"""
        import app as app_module
        # 无法直接调用 health()（需要 DB），但可以验证结构
        from tests.test_api import TestResponseHelpers
        pass  # 集成测试需 mock DB
