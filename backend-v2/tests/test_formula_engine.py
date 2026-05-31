# -*- coding: utf-8 -*-
"""
公式引擎测试
"""
import pytest
from exceptions import (
    FORMULA_SYNTAX_ERROR,
    FORMULA_INVALID_FIELD,
    FORMULA_COMPLEXITY_EXCEEDED,
)
from formula_engine.fields import ALLOWED_FIELDS, ALLOWED_FIELD_IDS, export_fields_json
from formula_engine.parser import parse, validate, complexity, analyze_dependencies, validate_and_compile
from formula_engine.evaluator import compile_formula, evaluate, batch_evaluate


class TestFields:
    """字段白名单测试"""
    
    def test_allowed_fields_count(self):
        """测试字段数量为25"""
        assert len(ALLOWED_FIELDS) == 25
    
    def test_allowed_field_ids(self):
        """测试字段ID集合"""
        assert "close" in ALLOWED_FIELD_IDS
        assert "nav" in ALLOWED_FIELD_IDS
        assert "premium_rate" in ALLOWED_FIELD_IDS
        assert "invalid_field" not in ALLOWED_FIELD_IDS
    
    def test_export_json(self):
        """测试JSON导出"""
        json_str = export_fields_json()
        assert "close" in json_str
        assert "nav" in json_str
        assert "fields" in json_str


class TestParser:
    """解析器测试"""
    
    def test_parse_simple_expression(self):
        """测试简单表达式解析"""
        tree = parse("close / nav - 1")
        assert tree is not None
    
    def test_parse_syntax_error(self):
        """测试语法错误"""
        with pytest.raises(Exception) as exc_info:
            parse("close +")
        assert exc_info.value.code == FORMULA_SYNTAX_ERROR
    
    def test_validate_valid_expression(self):
        """测试有效表达式校验"""
        tree = parse("close / nav")
        validate(tree)  # 不应抛出异常
    
    def test_validate_invalid_field(self):
        """测试无效字段"""
        tree = parse("price_avg * 2")
        with pytest.raises(Exception) as exc_info:
            validate(tree)
        assert exc_info.value.code == FORMULA_INVALID_FIELD
    
    def test_validate_invalid_function(self):
        """测试无效函数"""
        tree = parse("print(close)")
        with pytest.raises(Exception) as exc_info:
            validate(tree)
        assert exc_info.value.code == FORMULA_INVALID_FIELD
    
    def test_validate_attribute_access(self):
        """测试非法属性访问"""
        tree = parse("close.__class__")
        with pytest.raises(Exception) as exc_info:
            validate(tree)
        assert exc_info.value.code == FORMULA_INVALID_FIELD
    
    def test_complexity_normal(self):
        """测试正常复杂度"""
        tree = parse("close + nav * 2")
        node_count = complexity(tree)
        assert node_count < 100
    
    def test_complexity_exceeded(self):
        """测试复杂度超限"""
        # 构造一个超过100节点的表达式
        expr = " + ".join(["close"] * 101)
        tree = parse(expr)
        with pytest.raises(Exception) as exc_info:
            complexity(tree)
        assert exc_info.value.code == FORMULA_COMPLEXITY_EXCEEDED
    
    def test_ternary_expression(self):
        """测试三元表达式"""
        tree = parse("premium_rate > 5 ? premium_rate : 0")
        validate(tree)  # 不应抛出异常
    
    def test_function_calls(self):
        """测试函数调用"""
        tree = parse("abs(premium_rate)")
        validate(tree)
        
        tree = parse("max(close, nav)")
        validate(tree)
        
        tree = parse("min(close, nav)")
        validate(tree)
        
        tree = parse("round(close, 2)")
        validate(tree)
        
        tree = parse("ifnone(redeem_fee, 1.5)")
        validate(tree)
    
    def test_analyze_dependencies_no_cycle(self):
        """测试无环依赖分析"""
        formulas = [
            {"name": "formula_a", "expression": "close / nav - 1"},
            {"name": "formula_b", "expression": "formula_a * 2"},
        ]
        order = analyze_dependencies(formulas)
        assert len(order) == 2
        assert order.index("formula_a") < order.index("formula_b")
    
    def test_analyze_dependencies_with_cycle(self):
        """测试有环依赖"""
        formulas = [
            {"name": "a", "expression": "b + 1"},
            {"name": "b", "expression": "c + 1"},
            {"name": "c", "expression": "a + 1"},
        ]
        with pytest.raises(Exception) as exc_info:
            analyze_dependencies(formulas)
        assert exc_info.value.code == FORMULA_SYNTAX_ERROR
    
    def test_validate_and_compile(self):
        """测试组合调用"""
        tree, node_count = validate_and_compile("close / nav")
        assert tree is not None
        assert node_count > 0


class TestEvaluator:
    """求值器测试"""
    
    def test_compile_simple(self):
        """测试简单公式编译"""
        tree = parse("close / nav")
        validate(tree)
        fn = compile_formula(tree)
        assert callable(fn)
    
    def test_evaluate_basic(self):
        """测试基本求值"""
        tree = parse("close / nav")
        validate(tree)
        fn = compile_formula(tree)
        
        context = {"close": 2.0, "nav": 1.0}
        result = evaluate(fn, context)
        assert result == 2.0
    
    def test_evaluate_division_by_zero(self):
        """测试除零"""
        tree = parse("close / nav")
        validate(tree)
        fn = compile_formula(tree)
        
        context = {"close": 2.0, "nav": 0}
        result = evaluate(fn, context)
        assert result is None
    
    def test_evaluate_none_field(self):
        """测试None字段"""
        tree = parse("close / nav")
        validate(tree)
        fn = compile_formula(tree)
        
        context = {"close": 2.0, "nav": None}
        result = evaluate(fn, context)
        assert result is None
    
    def test_evaluate_ternary(self):
        """测试三元表达式求值"""
        tree = parse("premium_rate > 5 ? premium_rate : 0")
        validate(tree)
        fn = compile_formula(tree)
        
        context = {"premium_rate": 10.0}
        result = evaluate(fn, context)
        assert result == 10.0
        
        context = {"premium_rate": 3.0}
        result = evaluate(fn, context)
        assert result == 0.0
    
    def test_evaluate_abs(self):
        """测试abs函数"""
        tree = parse("abs(premium_rate)")
        validate(tree)
        fn = compile_formula(tree)
        
        context = {"premium_rate": -5.0}
        result = evaluate(fn, context)
        assert result == 5.0
    
    def test_evaluate_ifnone(self):
        """测试ifnone函数"""
        tree = parse("ifnone(redeem_fee, 1.5)")
        validate(tree)
        fn = compile_formula(tree)
        
        context = {"redeem_fee": None}
        result = evaluate(fn, context)
        assert result == 1.5
        
        context = {"redeem_fee": 2.0}
        result = evaluate(fn, context)
        assert result == 2.0
    
    def test_batch_evaluate(self):
        """测试批量求值"""
        formulas = [
            {"name": "nav_premium", "expression": "close / nav - 1"},
        ]
        funds_data = [
            {"code": "160644", "close": 2.0, "nav": 1.0},
            {"code": "160645", "close": 1.5, "nav": 1.0},
        ]
        
        results = batch_evaluate(formulas, funds_data)
        assert "160644" in results
        assert "160645" in results
        assert results["160644"]["nav_premium"] == 1.0
        assert results["160645"]["nav_premium"] == 0.5
    
    def test_batch_evaluate_too_many_funds(self):
        """测试基金数量超限"""
        formulas = [{"name": "test", "expression": "close"}]
        funds_data = [{"code": str(i)} for i in range(2001)]
        
        with pytest.raises(Exception):
            batch_evaluate(formulas, funds_data)
    
    def test_complex_formula(self):
        """测试复杂公式"""
        tree = parse("max(abs(close - nav), min(volume, amount))")
        validate(tree)
        fn = compile_formula(tree)
        
        context = {"close": 2.5, "nav": 2.0, "volume": 1000, "amount": 5000}
        result = evaluate(fn, context)
        assert result == 1000
