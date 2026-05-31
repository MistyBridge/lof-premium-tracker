# 加功能标准流程

## 步骤

### 1. 了解背景
读 `.ai/context.md` 了解项目当前状态。
读 `ARCHITECTURE.md` 了解系统架构和分层规则。

### 2. 评估影响
读 `.ai/impact_matrix.json` 确认需要修改的模块和依赖关系。
读 `.ai/api_contract.json` 确认现有 API 契约（如果涉及 API 变更）。

### 3. 设计方案
向用户说明：
- 要改哪些文件、新增哪些文件
- 数据库是否需要迁移（如有，提供迁移脚本和回滚脚本）
- API 是否有变更（如有，说明 breaking change 风险）
- 新增功能的测试策略
- 预计性能影响（对比 benchmarks.json）

读 `.ai/conventions.md` 确认代码风格。

### 4. 实现
- 按设计方案逐文件修改
- 每个文件修改后立即运行相关测试
- 遵循 `.ai/review_checklist.md` 自查
- 单文件不超过 300 行，超过则拆分

### 5. 验证
- 运行 verify.sh 全量验证
- 如果有 API 变更，确认前端兼容性
- 如果有数据库变更，确认迁移脚本能执行和回滚
- 检查性能：对比 benchmarks.json 确认无退化

### 6. 记录
- 更新 `.ai/file_index.md`（新增文件）
- 更新 `.ai/impact_matrix.json`（新增依赖关系）
- 更新 `.ai/api_contract.json`（API 变更）
- 更新 `.ai/module_health.json`（新模块健康度）
- Git commit: `feat(scope): description`
