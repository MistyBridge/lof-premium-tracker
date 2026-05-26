"""测试真实 app.py 辅助函数（需要 mock 外部依赖）"""

import sys
import os
from datetime import datetime, time
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestMarketHours:
    """_is_market_hours() 真实函数测试"""

    def test_weekday_trading_morning(self):
        """工作日盘中 → True"""
        import app
        mock_now = datetime(2026, 5, 26, 10, 0, 0)  # 周二 10:00
        with patch.object(app, 'datetime') as mock_dt:
            mock_dt.now.return_value = mock_now
            # weekday check passes inline since datetime.now returns our mock
            assert app._is_market_hours() is True

    def test_weekday_trading_afternoon(self):
        """工作日下午盘中 → True"""
        import app
        mock_now = datetime(2026, 5, 26, 14, 0, 0)  # 周二 14:00
        with patch.object(app, 'datetime') as mock_dt:
            mock_dt.now.return_value = mock_now
            assert app._is_market_hours() is True

    def test_weekday_before_open(self):
        """工作日盘前 → False"""
        import app
        mock_now = datetime(2026, 5, 26, 9, 0, 0)
        with patch.object(app, 'datetime') as mock_dt:
            mock_dt.now.return_value = mock_now
            assert app._is_market_hours() is False

    def test_weekday_lunch_break(self):
        """工作日午休 → False"""
        import app
        mock_now = datetime(2026, 5, 26, 12, 0, 0)
        with patch.object(app, 'datetime') as mock_dt:
            mock_dt.now.return_value = mock_now
            assert app._is_market_hours() is False

    def test_weekday_after_close(self):
        """工作日盘后 → False"""
        import app
        mock_now = datetime(2026, 5, 26, 16, 0, 0)
        with patch.object(app, 'datetime') as mock_dt:
            mock_dt.now.return_value = mock_now
            assert app._is_market_hours() is False

    def test_saturday(self):
        """周六 → False"""
        import app
        mock_now = datetime(2026, 5, 23, 10, 0, 0)  # 周六
        with patch.object(app, 'datetime') as mock_dt:
            mock_dt.now.return_value = mock_now
            assert app._is_market_hours() is False

    def test_sunday(self):
        """周日 → False"""
        import app
        mock_now = datetime(2026, 5, 24, 10, 0, 0)  # 周日
        with patch.object(app, 'datetime') as mock_dt:
            mock_dt.now.return_value = mock_now
            assert app._is_market_hours() is False


class TestSuspensionLogic:
    """_is_suspended() 真实函数测试"""

    def test_has_volume_not_suspended(self):
        """成交量>0 → 绝对不停牌"""
        from app import _is_suspended
        assert _is_suspended({'code': 'test', 'volume': 100, 'amount': 0}) is False

    def test_has_amount_not_suspended(self):
        """成交额>0 → 绝对不停牌"""
        from app import _is_suspended
        assert _is_suspended({'code': 'test', 'volume': 0, 'amount': 5000}) is False

    def test_both_not_zero(self):
        """成交量和成交额都>0 → 绝对不停牌"""
        from app import _is_suspended
        assert _is_suspended({'code': 'test', 'volume': 50, 'amount': 2000}) is False

    def test_market_hours_zero_volume_suspended(self):
        """交易时段 volume=0 → 停牌"""
        import app
        from app import _is_suspended
        mock_now = datetime(2026, 5, 26, 10, 0, 0)
        with patch.object(app, 'datetime') as mock_dt:
            mock_dt.now.return_value = mock_now
            with patch('app._load_suspension_cache', return_value={}):
                result = _is_suspended({'code': 'test', 'volume': 0, 'amount': None})
                assert result is True

    def test_outside_market_uses_cache(self):
        """非交易时段 → 沿用缓存状态"""
        import app
        from app import _is_suspended
        mock_now = datetime(2026, 5, 26, 20, 0, 0)  # 盘后
        with patch.object(app, 'datetime') as mock_dt:
            mock_dt.now.return_value = mock_now
            # Previously suspended
            with patch('app._load_suspension_cache', return_value={'test': True}):
                assert _is_suspended({'code': 'test', 'volume': 0, 'amount': 0}) is True
            # Previously not suspended
            with patch('app._load_suspension_cache', return_value={'test': False}):
                assert _is_suspended({'code': 'test', 'volume': 0, 'amount': 0}) is False

    def test_none_volume_amount_no_cache(self):
        """vol/amt 均为 None，非交易时段 → 沿用缓存"""
        import app
        from app import _is_suspended
        mock_now = datetime(2026, 5, 26, 20, 0, 0)
        with patch.object(app, 'datetime') as mock_dt:
            mock_dt.now.return_value = mock_now
            with patch('app._load_suspension_cache', return_value={}):
                assert _is_suspended({'code': 'test', 'volume': None, 'amount': None}) is False


class TestResponseHelpers:
    """ok() / err_resp() 真实函数测试"""

    def test_ok_basic(self):
        import app as app_module
        from app import ok
        with app_module.app.test_request_context():
            resp, code = ok({'items': [1, 2, 3]})
            assert code == 200
            assert resp.json['code'] == 0
            assert resp.json['data'] == {'items': [1, 2, 3]}

    def test_ok_with_meta(self):
        import app as app_module
        from app import ok
        with app_module.app.test_request_context():
            resp, code = ok([], meta={'total': 42, 'page': 1})
            assert resp.json['meta']['total'] == 42

    def test_err_basic(self):
        import app as app_module
        from app import err_resp
        with app_module.app.test_request_context():
            resp, code = err_resp('参数缺失', code=10, status=400)
            assert code == 400
            assert resp.json['code'] == 10
            assert '参数缺失' in resp.json['message']


class TestFundFormatting:
    """_fmt() 真实函数测试"""

    def test_basic_formatting(self):
        from app import _fmt
        fund = {
            'code': '160323', 'name': '华夏磐泰LOF',
            'premium_rate': 5.12, 'nav': 1.234, 'price': 1.300,
            'change_pct': 0.56, 'amount': 50000000, 'volume': 100000,
            'is_suspended': False, 'can_purchase': True,
            'purchase_limit': None, 'nav_date': '2026-05-23',
            'is_formal_nav': True, 'premium_status': '溢价',
            'avg_premium_3d': 3.5, 'data_date': '2026-05-23',
            'purchase_fee_rate': 0.15, 'redemption_fee_rate': 1.5,
        }
        result = _fmt(fund)
        assert result['code'] == '160323'
        assert result['premium_rate'] == 5.12
        assert result['nav'] == 1.234
        assert result['name'] == '华夏磐泰LOF'

    def test_suspended_fund_market_hours(self):
        """交易时段内 vol=0 & amt=0 → 停牌"""
        import app as app_module
        from app import _fmt
        fund = {'code': '000001', 'name': 'Test',
                'premium_rate': 0, 'nav': 1.0, 'price': 1.0,
                'change_pct': 0, 'amount': 0, 'volume': 0,
                'is_formal_nav': True, 'premium_status': '停牌'}
        mock_now = datetime(2026, 5, 26, 10, 0, 0)  # 周二盘中
        with patch.object(app_module, 'datetime') as mock_dt:
            mock_dt.now.return_value = mock_now
            with patch('app._load_suspension_cache', return_value={}):
                result = _fmt(fund)
                assert result['is_suspended'] is True


class TestMarketBoundary:
    """交易时段边界值测试"""

    def test_market_open_boundary(self):
        """9:30 开盘边界 → True"""
        import app
        mock_now = datetime(2026, 5, 26, 9, 30, 0)
        with patch.object(app, 'datetime') as mock_dt:
            mock_dt.now.return_value = mock_now
            assert app._is_market_hours() is True

    def test_market_close_boundary(self):
        """15:00 收盘边界 → True"""
        import app
        mock_now = datetime(2026, 5, 26, 15, 0, 0)
        with patch.object(app, 'datetime') as mock_dt:
            mock_dt.now.return_value = mock_now
            assert app._is_market_hours() is True
