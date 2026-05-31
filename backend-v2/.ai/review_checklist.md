# 代码审查自查清单

## 必查项（任何修改都要检查）
- [ ] 所有用户输入有校验（Pydantic model 或白名单）
- [ ] SQL 查询用参数化，无字符串拼接（grep `f"SELECT` 确认）
- [ ] 异常用 exceptions.py 中的类，不直接用 HTTPException
- [ ] 新增函数有 docstring（数据源/降级/Args/Returns/调用方）
- [ ] 新增函数有类型提示（参数+返回值）
- [ ] Redis 操作有 try-except 降级逻辑
- [ ] DB 操作在 async session 中，异常时自动 rollback
- [ ] 无硬编码魔法数字（用 constants.py 中的常量）
- [ ] 日志包含上下文（request_id, user_id, 操作参数）
- [ ] datetime 用 timezone-aware（datetime.now(timezone.utc)）
- [ ] Decimal 值入库前 round 到 4 位小数
- [ ] 无 `eval()` / `exec()` 调用（公式引擎用 AST 白名单）
- [ ] 敏感配置不出现在日志中（密码/token/密钥）

## 测试项
- [ ] 新增代码有对应测试
- [ ] 测试覆盖正常路径和异常路径
- [ ] pytest tests/ 全部通过
- [ ] 核心模块覆盖率 > 90%（calculator/parser/evaluator/normalize/validator）
- [ ] 其他模块覆盖率 > 60%

## 文档项
- [ ] API 响应结构变更已更新 api_contract.json
- [ ] 新模块已更新 impact_matrix.json
- [ ] 新模块已更新 file_index.md
- [ ] 已知问题已更新 knowledge_base.md（如有新的错误模式）
- [ ] 模块健康度已更新 module_health.json

## 安全项
- [ ] 无 SQL 注入风险
- [ ] 无 eval/exec 调用
- [ ] 公式引擎用 AST 白名单，不用 eval
- [ ] 敏感配置不出现在日志中（密码/token/密钥）
- [ ] admin 端点需要 admin 权限
- [ ] CORS 精确匹配，不用 `*`
- [ ] 用户输入长度限制（名称 < 100 字符，表达式 < 500 字符）

## 性能项
- [ ] 无 N+1 查询（用 JOIN 或 IN 批量查询）
- [ ] 批量操作用分批处理（100 条/事务）
- [ ] Redis SCAN 替代 KEYS（避免阻塞）
- [ ] 外部 API 调用有超时（10 秒）
- [ ] 数据库查询有 LIMIT（不允许无 LIMIT 的全表扫描）
