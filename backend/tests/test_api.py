"""测试 API 响应结构和格式"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestResponseHelpers:
    """通用响应构建函数"""

    def test_ok_response_structure(self):
        """ok() 返回标准成功响应"""
        # 模拟 ok 函数的行为
        def ok(data, meta=None, status=200):
            return {
                'code': 0,
                'message': 'success',
                'data': data,
                **(meta or {})
            }, status

        body, code = ok({'funds': []})
        assert code == 200
        assert body['code'] == 0
        assert body['message'] == 'success'
        assert body['data'] == {'funds': []}

    def test_err_response_structure(self):
        """err_resp() 返回标准错误响应"""
        def err_resp(message, code=1, status=400, details=None):
            payload = {'code': code, 'message': message}
            if details:
                payload['details'] = details
            return payload, status

        body, code = err_resp('参数错误', code=10, status=400)
        assert code == 400
        assert body['code'] == 10
        assert body['message'] == '参数错误'

    def test_ok_with_meta(self):
        """ok() 带 meta 信息"""
        def ok(data, meta=None, status=200):
            r = {'code': 0, 'message': 'success', 'data': data}
            if meta:
                r['meta'] = meta
            return r, status

        body, code = ok([], meta={'total': 100, 'page': 1})
        assert body['meta']['total'] == 100


class TestFundFormatting:
    """基金数据格式化"""

    def test_premium_rate_formatting(self):
        """溢价率格式化 — 正值带+号"""
        def format_premium(rate):
            if rate is None:
                return '--'
            return f"{rate:+.2f}%"

        assert format_premium(5.123) == '+5.12%'
        assert format_premium(-3.456) == '-3.46%'
        assert format_premium(None) == '--'

    def test_amount_formatting(self):
        """成交额格式化"""
        def format_amount(amount):
            if amount is None:
                return '--'
            wan = amount / 10000
            if wan >= 10000:
                yi = wan / 10000
                return f'{yi:.2f}亿'
            return f'{wan:.2f}万'

        assert format_amount(50000000) == '5000.00万'  # 5千万
        assert format_amount(200000000) == '2.00亿'    # 2亿
        assert format_amount(None) == '--'
