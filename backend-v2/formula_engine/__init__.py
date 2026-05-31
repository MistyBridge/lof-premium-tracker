"""
公式引擎模块 — M5 公式引擎

依赖: constants
被依赖: services, routers, 前端 JS
对外接口:
  - parse(expr): 解析表达式 → AST
  - validate(expr): 校验表达式合法性
  - evaluate(expr, data): 求值
  - batch_evaluate(exprs, funds): 批量求值
  - FIELDS: 字段白名单
"""