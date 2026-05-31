# 修 Bug 标准流程

## 步骤

### 1. 了解背景
读 `.ai/context.md` 了解项目当前状态和已知问题。

### 2. 查知识库
读 `.ai/knowledge_base.md` 查看是否已有解决方案。已知问题直接执行解决方案，不需要重新分析。

### 3. 复现问题
- 运行相关测试: `pytest tests/test_xxx.py -v`
- 或调用诊断 API: `GET /api/v1/admin/diagnose/xxx`
- 或查看日志: `GET /api/v1/admin/logs?level=ERROR&lines=50`
- 或查看服务器日志: `journalctl -u jinkuaicha -n 50 --no-pager`

### 4. 定位根因
- 不要用猜，用日志/数据/测试确认
- 如果是数据问题，查 `GET /api/v1/admin/diagnose/fund?code=xxx`
- 如果是外部 API 问题，检查 fetcher 日志和降级逻辑
- 如果是性能问题，对比 `.ai/benchmarks.json`

### 5. 读影响矩阵
读 `.ai/impact_matrix.json` 确认：
- 该模块依赖哪些其他模块
- 哪些模块依赖该模块
- 需要运行哪些测试
- 需要更新哪些文档

### 6. 修复
- 只改必要的文件，不做无关重构
- 遵循 `.ai/conventions.md` 代码规范
- 遵循 `.ai/review_checklist.md` 自查

### 7. 验证
- 运行受影响模块的测试: `pytest tests/test_xxx.py -v`
- 运行 verify.sh 确认全量通过
- 如果修了 API 响应结构，对比 `api_contract.json`

### 8. 记录
- 更新 `.ai/knowledge_base.md`（如果是新的错误模式）
- 更新 `.ai/context.md` 的"已知问题"（如果解决了已知问题）
- 更新 `.ai/module_health.json`（如果模块健康度变化）
- Git commit: `fix(scope): description`
