# 柯2 任务：AI可管理性 + 项目文档 + 运维脚本

## 身份
你是金快查 v2 项目文档工程师"柯2"，负责AI治理层和项目基础设施文档。

## 项目背景
金快查 — LOF基金实时折溢价监控系统。
技术栈: FastAPI + PostgreSQL 14 + Redis 6 + APScheduler
部署: 阿里云 2C2G (101.200.129.61)，Nginx + systemd
前端: Cloudflare Pages (jinkuaicha.com)
API: api.jinkuaicha.com → ECS 101.200.129.61
代码目录: backend-v2/

## 你的18个文件

### .ai/ 元数据文件（11个）
1. **.ai/file_index.md** — 按功能分类的文件索引（数据采集/数据处理/缓存队列/公式引擎/API层/认证/中台/基础设施）
2. **.ai/impact_matrix.json** — 模块影响矩阵（depends_on/depended_by/tests/affected_docs/risk/notes）
3. **.ai/benchmarks.json** — 性能基准线（fund_list_api/fund_detail_api/formula_eval/push2_fetch/lsjz_fetch/daily_save）
4. **.ai/module_health.json** — 模块健康度（test_coverage/complexity/last_modified/health）
5. **.ai/api_contract.json** — API契约（GET /api/v1/funds, GET /api/v1/funds/:code, POST /api/v1/formulas 等端点的字段定义）
6. **.ai/knowledge_base.md** — 已知问题知识库（push2超时/Redis断连/fundf10解析失败/QDII延迟/物化视图慢）
7. **.ai/review_checklist.md** — 代码审查自查清单（必查项/测试项/文档项/安全项）
8. **.ai/conventions.md** — AI协作约定（代码风格/Git约定/沟通约定/文件组织/错误处理）
9. **.ai/prompts/fix_bug.md** — 修Bug标准流程
10. **.ai/prompts/add_feature.md** — 加功能标准流程
11. **.ai/prompts/ops_diagnose.md** — 运维诊断标准流程

### 项目文档（4个）
12. **.ai/scripts/assess_change.sh** — 变更影响评估脚本（读impact_matrix.json输出依赖/测试/文档）
13. **ARCHITECTURE.md** — 系统架构文档（技术栈/分层架构/数据流/设计决策ADR/已知限制）
14. **DATA_DICTIONARY.md** — 数据字典（每张表的字段说明+类型+取值范围+来源+常见查询SQL）
15. **verify.sh** — 标准验证脚本（pytest+类型检查+覆盖率+迁移检查+健康检查）

### 运维+数据（3个）
16. **constants.py** — 完整业务常量清单（和柯1协调，如果柯1已写则跳过。包括：校验阈值/采集参数/公式引擎/API/缓存/SSE共6组约30个常量）
17. **sql/seed/seed_trade_calendar.sql** — 2025-2026年交易日历种子数据（约500行INSERT）
18. **sql/seed/seed_fund_code_list.sql** — 50只代表性LOF基金代码种子数据

## 技术参考
完整设计见 docs/plan/AI可管理性.md

## 规范
- Markdown 格式，清晰的层级结构
- JSON 用标准格式，便于程序读取
- shell 脚本加 shebang + set -e
- 常量命名 UPPER_SNAKE_CASE