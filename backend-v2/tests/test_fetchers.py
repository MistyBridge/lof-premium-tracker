"""
M3 采集层测试 — 8项测试
"""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch

from fetchers import clean_code, safe_float, safe_int


class TestUtilityFunctions:
    """工具函数测试"""

    def test_clean_code_zfill(self):
        """测试1: 代码补零到6位"""
        assert clean_code("160644") == "160644"
        assert clean_code("1606") == "001606"
        assert clean_code("1") == "000001"
        assert clean_code("") == "000000"

    def test_clean_code_fullwidth(self):
        """测试2: 全角转半角"""
        assert clean_code("１６０６４４") == "160644"

    def test_clean_code_strip(self):
        """测试3: 去空格"""
        assert clean_code(" 160644 ") == "160644"

    def test_safe_float_normal(self):
        """测试4: 正常浮点转换"""
        assert safe_float("1.5") == 1.5
        assert safe_float(2.0) == 2.0
        assert safe_float(100) == 100.0

    def test_safe_float_invalid(self):
        """测试5: 无效值返回默认值"""
        assert safe_float(None) is None
        assert safe_float("") is None
        assert safe_float("-") is None
        assert safe_float("None") is None
        assert safe_float("abc") is None

    def test_safe_float_nan(self):
        """测试6: NaN返回默认值"""
        assert safe_float(float('nan')) is None

    def test_safe_int(self):
        """测试7: 安全整数转换"""
        assert safe_int("100") == 100
        assert safe_int("1.5") == 1
        assert safe_int(None) is None

    def test_safe_int_invalid(self):
        """测试8: 无效整数返回默认值"""
        assert safe_int("abc") is None
        assert safe_int("") is None


# 以下测试需要 mock httpx，仅供参考
# @pytest.mark.asyncio
# async def test_fetch_realtime_success():
#     """实时行情采集成功"""
#     pass
