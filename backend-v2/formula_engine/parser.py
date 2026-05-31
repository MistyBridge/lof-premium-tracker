# -*- coding: utf-8 -*-
"""
AST解析 + 安全校验 + 复杂度评估 + 依赖分析 + 环检测 + LRU缓存
"""
import ast
from functools import lru_cache
from typing import Set, List, Dict, Optional, Tuple, Any

from exceptions import (
    ValidationException,
    FORMULA_SYNTAX_ERROR,
    FORMULA_INVALID_FIELD,
    FORMULA_COMPLEXITY_EXCEEDED,
)
from .fields import ALLOWED_FIELD_IDS, SAFE_FUNCTION_NAMES, SAFE_FUNCTIONS

MAX_COMPLEXITY = 100


@lru_cache(maxsize=256)
def parse(expression: str) -> ast.Expression:
    """解析表达式为AST"""
    try:
        tree = ast.parse(expression, mode="eval")
        return tree
    except SyntaxError as e:
        raise ValidationException(
            code=FORMULA_SYNTAX_ERROR,
            message="表达式语法错误",
            detail=f"Line {e.lineno}, Col {e.offset}: {e.msg}"
        )


def validate(tree: ast.Expression) -> None:
    """递归校验AST安全性"""
    _validate_node(tree.body)


def _validate_node(node: ast.AST) -> None:
    """递归校验单个节点"""
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)):
            raise ValidationException(
                code=FORMULA_INVALID_FIELD,
                message="不支持的字段",
                detail=f"Only numeric constants allowed, got {type(node.value).__name__}"
            )
        return
    
    if isinstance(node, ast.Name):
        if node.id not in ALLOWED_FIELD_IDS:
            raise ValidationException(
                code=FORMULA_INVALID_FIELD,
                message="不支持的字段",
                detail=f"unknown field: {node.id}"
            )
        return
    
    if isinstance(node, ast.BinOp):
        allowed_ops = {ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow}
        if type(node.op) not in allowed_ops:
            raise ValidationException(
                code=FORMULA_INVALID_FIELD,
                message="不支持的字段",
                detail=f"Unsupported operator: {type(node.op).__name__}"
            )
        _validate_node(node.left)
        _validate_node(node.right)
        return
    
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ast.USub):
            raise ValidationException(
                code=FORMULA_INVALID_FIELD,
                message="不支持的字段",
                detail=f"Unsupported unary operator: {type(node.op).__name__}"
            )
        _validate_node(node.operand)
        return
    
    if isinstance(node, ast.Compare):
        allowed_ops = {ast.Gt, ast.Lt, ast.GtE, ast.LtE, ast.Eq, ast.NotEq}
        for op in node.ops:
            if type(op) not in allowed_ops:
                raise ValidationException(
                    code=FORMULA_INVALID_FIELD,
                    message="不支持的字段",
                    detail=f"Unsupported comparison operator: {type(op).__name__}"
                )
        _validate_node(node.left)
        for comparator in node.comparators:
            _validate_node(comparator)
        return
    
    if isinstance(node, ast.IfExp):
        _validate_node(node.test)
        _validate_node(node.body)
        _validate_node(node.orelse)
        return
    
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValidationException(
                code=FORMULA_INVALID_FIELD,
                message="不支持的字段",
                detail="Only direct function calls allowed"
            )
        
        func_name = node.func.id
        if func_name not in SAFE_FUNCTION_NAMES:
            raise ValidationException(
                code=FORMULA_INVALID_FIELD,
                message="不支持的字段",
                detail=f"unknown function: {func_name}"
            )
        
        func_info = SAFE_FUNCTIONS[func_name]
        num_args = len(node.args)
        
        if num_args < func_info["min_args"]:
            raise ValidationException(
                code=FORMULA_INVALID_FIELD,
                message="不支持的字段",
                detail=f"{func_name}() requires at least {func_info['min_args']} arguments, got {num_args}"
            )
        
        if func_info["max_args"] is not None and num_args > func_info["max_args"]:
            raise ValidationException(
                code=FORMULA_INVALID_FIELD,
                message="不支持的字段",
                detail=f"{func_name}() requires at most {func_info['max_args']} arguments, got {num_args}"
            )
        
        for arg in node.args:
            _validate_node(arg)
        return
    
    raise ValidationException(
        code=FORMULA_INVALID_FIELD,
        message="不支持的字段",
        detail=f"Unsupported node type: {type(node).__name__}"
    )


def complexity(tree: ast.Expression) -> int:
    """计算AST复杂度"""
    node_count = _count_nodes(tree)
    if node_count > MAX_COMPLEXITY:
        raise ValidationException(
            code=FORMULA_COMPLEXITY_EXCEEDED,
            message="表达式过于复杂",
            detail={"nodes": node_count, "max": MAX_COMPLEXITY}
        )
    return node_count


def _count_nodes(node: ast.AST) -> int:
    """递归计数节点"""
    count = 1
    for child in ast.iter_child_nodes(node):
        count += _count_nodes(child)
    return count


def validate_and_compile(expression: str) -> Tuple[ast.Expression, int]:
    """组合调用：parse -> validate -> complexity"""
    tree = parse(expression)
    validate(tree)
    node_count = complexity(tree)
    return tree, node_count


def extract_names(tree: ast.Expression) -> Set[str]:
    """提取AST中所有变量名"""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
    return names


def analyze_dependencies(formulas: List[Dict[str, str]]) -> List[str]:
    """公式间依赖分析 + 环检测"""
    formula_names = {f["name"] for f in formulas}
    graph: Dict[str, Set[str]] = {}
    
    for formula in formulas:
        name = formula["name"]
        expression = formula["expression"]
        
        if name in ALLOWED_FIELD_IDS:
            raise ValidationException(
                code=FORMULA_INVALID_FIELD,
                message="不支持的字段",
                detail=f"Formula name '{name}' conflicts with built-in field"
            )
        
        tree = parse(expression)
        validate(tree)
        names = extract_names(tree)
        formula_refs = names & formula_names
        graph[name] = formula_refs
    
    visited = set()
    visiting = set()
    order = []
    
    def dfs(node: str, path: List[str]) -> None:
        if node in visited:
            return
        if node in visiting:
            cycle_start = path.index(node)
            cycle = path[cycle_start:] + [node]
            raise ValidationException(
                code=FORMULA_SYNTAX_ERROR,
                message="公式存在循环依赖",
                detail={"cycle": cycle}
            )
        
        visiting.add(node)
        path.append(node)
        
        for dep in graph.get(node, []):
            dfs(dep, path)
        
        path.pop()
        visiting.remove(node)
        visited.add(node)
        order.append(node)
    
    for formula_name in formula_names:
        if formula_name not in visited:
            dfs(formula_name, [])
    
    return order
