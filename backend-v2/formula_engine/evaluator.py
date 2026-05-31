# -*- coding: utf-8 -*-
"""
AST编译为闭包 + 安全求值 + 批量求值 + 性能边界
"""
import ast
from typing import Union, Dict, List, Any, Optional, Callable

from exceptions import (
    ValidationException,
    QUERY_TOO_MANY_CODES,
    FORMULA_SYNTAX_ERROR,
)
from .fields import ALLOWED_FIELD_IDS, SAFE_FUNCTION_NAMES
from .parser import parse, validate, validate_and_compile, analyze_dependencies

# 性能边界
MAX_FUNDS = 2000
MAX_FORMULAS = 10
MAX_ESTIMATED_TIME_MS = 5000


def ifnone(x: Any, default: Any) -> Any:
    """自定义函数：x为None时返回default"""
    return default if x is None else x


# 安全函数映射
SAFE_FUNCTIONS_MAP = {
    "abs": abs,
    "max": max,
    "min": min,
    "round": round,
    "ifnone": ifnone,
}


def compile_formula(tree: ast.Expression) -> Callable[[Dict[str, Any]], Union[float, bool, None]]:
    """将AST编译为轻量闭包函数"""
    return _compile_node(tree.body)


def _compile_node(node: ast.AST) -> Callable[[Dict[str, Any]], Any]:
    """递归编译AST节点"""
    if isinstance(node, ast.Constant):
        value = node.value
        return lambda ctx: value
    
    if isinstance(node, ast.Name):
        field_name = node.id
        return lambda ctx: ctx.get(field_name)
    
    if isinstance(node, ast.BinOp):
        left_fn = _compile_node(node.left)
        right_fn = _compile_node(node.right)
        op = node.op
        
        if isinstance(op, ast.Add):
            return lambda ctx: _safe_add(left_fn(ctx), right_fn(ctx))
        elif isinstance(op, ast.Sub):
            return lambda ctx: _safe_sub(left_fn(ctx), right_fn(ctx))
        elif isinstance(op, ast.Mult):
            return lambda ctx: _safe_mul(left_fn(ctx), right_fn(ctx))
        elif isinstance(op, ast.Div):
            return lambda ctx: _safe_div(left_fn(ctx), right_fn(ctx))
        elif isinstance(op, ast.Mod):
            return lambda ctx: _safe_mod(left_fn(ctx), right_fn(ctx))
        elif isinstance(op, ast.Pow):
            return lambda ctx: _safe_pow(left_fn(ctx), right_fn(ctx))
    
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        operand_fn = _compile_node(node.operand)
        return lambda ctx: _safe_neg(operand_fn(ctx))
    
    if isinstance(node, ast.Compare):
        left_fn = _compile_node(node.left)
        comparators_fns = [_compile_node(c) for c in node.comparators]
        ops = node.ops
        
        def compare_fn(ctx):
            left_val = left_fn(ctx)
            result = True
            for op, comp_fn in zip(ops, comparators_fns):
                right_val = comp_fn(ctx)
                if left_val is None or right_val is None:
                    return None
                if isinstance(op, ast.Gt):
                    result = result and (left_val > right_val)
                elif isinstance(op, ast.Lt):
                    result = result and (left_val < right_val)
                elif isinstance(op, ast.GtE):
                    result = result and (left_val >= right_val)
                elif isinstance(op, ast.LtE):
                    result = result and (left_val <= right_val)
                elif isinstance(op, ast.Eq):
                    result = result and (left_val == right_val)
                elif isinstance(op, ast.NotEq):
                    result = result and (left_val != right_val)
                left_val = right_val
            return result
        
        return compare_fn
    
    if isinstance(node, ast.IfExp):
        test_fn = _compile_node(node.test)
        body_fn = _compile_node(node.body)
        orelse_fn = _compile_node(node.orelse)
        return lambda ctx: body_fn(ctx) if test_fn(ctx) else orelse_fn(ctx)
    
    if isinstance(node, ast.Call):
        func_name = node.func.id
        args_fns = [_compile_node(arg) for arg in node.args]
        
        if func_name == "ifnone":
            return lambda ctx: ifnone(args_fns[0](ctx), args_fns[1](ctx) if len(args_fns) > 1 else None)
        
        safe_func = SAFE_FUNCTIONS_MAP.get(func_name)
        if safe_func:
            return lambda ctx: _safe_func_call(safe_func, [fn(ctx) for fn in args_fns])
    
    raise ValidationException(
        code=FORMULA_INVALID_FIELD,
        message="不支持的字段",
        detail=f"Cannot compile node type: {type(node).__name__}"
    )


def _safe_add(a: Any, b: Any) -> Any:
    if a is None or b is None:
        return None
    return a + b


def _safe_sub(a: Any, b: Any) -> Any:
    if a is None or b is None:
        return None
    return a - b


def _safe_mul(a: Any, b: Any) -> Any:
    if a is None or b is None:
        return None
    return a * b


def _safe_div(a: Any, b: Any) -> Any:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _safe_mod(a: Any, b: Any) -> Any:
    if a is None or b is None or b == 0:
        return None
    return a % b


def _safe_pow(a: Any, b: Any) -> Any:
    if a is None or b is None:
        return None
    try:
        return a ** b
    except (OverflowError, ValueError):
        return None


def _safe_neg(a: Any) -> Any:
    if a is None:
        return None
    return -a


def _safe_func_call(func: Callable, args: List[Any]) -> Any:
    """安全调用函数，任何异常返回None"""
    if any(arg is None for arg in args):
        return None
    try:
        return func(*args)
    except Exception:
        return None


def evaluate(fn: Callable[[Dict[str, Any]], Any], context: Dict[str, Any]) -> Union[float, bool, None]:
    """调用编译后的闭包求值"""
    try:
        result = fn(context)
        if result is None:
            return None
        if isinstance(result, bool):
            return result
        if isinstance(result, (int, float)):
            return float(result)
        return None
    except Exception:
        return None


def batch_evaluate(
    formulas: List[Dict[str, str]],
    funds_data: List[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """批量求值"""
    if len(funds_data) > MAX_FUNDS:
        raise ValidationException(
            code=QUERY_TOO_MANY_CODES,
            message="查询基金数量超限",
            detail={"requested": len(funds_data), "max": MAX_FUNDS}
        )
    
    if len(formulas) > MAX_FORMULAS:
        raise ValidationException(
            code=FORMULA_SYNTAX_ERROR,
            message="公式数量超限",
            detail=f"Max {MAX_FORMULAS} formulas allowed"
        )
    
    sorted_names = analyze_dependencies(formulas)
    formula_map = {f["name"]: f["expression"] for f in formulas}
    
    compiled_formulas = []
    total_nodes = 0
    for name in sorted_names:
        expr = formula_map[name]
        tree, node_count = validate_and_compile(expr)
        fn = compile_formula(tree)
        compiled_formulas.append((name, fn))
        total_nodes += node_count
    
    avg_nodes = total_nodes / len(compiled_formulas) if compiled_formulas else 0
    estimated_ms = len(funds_data) * len(compiled_formulas) * avg_nodes * 0.001
    if estimated_ms > MAX_ESTIMATED_TIME_MS:
        raise ValidationException(
            code=FORMULA_SYNTAX_ERROR,
            message="计算量过大",
            detail=f"Estimated time: {estimated_ms:.0f}ms > {MAX_ESTIMATED_TIME_MS}ms"
        )
    
    results = {}
    for fund in funds_data:
        code = fund.get("code", "unknown")
        context = fund.copy()
        fund_results = {}
        
        try:
            for name, fn in compiled_formulas:
                result = evaluate(fn, context)
                fund_results[name] = result
                context[name] = result
        except Exception:
            for name in sorted_names:
                if name not in fund_results:
                    fund_results[name] = None
        
        results[code] = fund_results
    
    return results
