# 文件索引（按功能分类）

## 基础设施
config.py           → 配置集中管理（Pydantic Settings，从 .env 读取）
database.py         → SQLAlchemy async engine + session + 依赖注入
models.py           → ORM 模型（16 张表）
migration.py        → 建表 + 分区 + 物化视图 + 日历预置 + 校验
trade_calendar.py   → 交易日判断（查 DB 缓存内存）
cache.py            → Redis 缓存封装（含降级 + 缓存击穿保护）
mq.py               → Redis Streams 封装（单条 stream:events）
metrics.py          → 监控指标 + 告警（webhook 推送）
exceptions.py       → 异常类层级 + 错误码 + 全局处理器
constants.py        → 业务常量集中定义

## 数据采集
fetchers/__init__.py   → 工具函数 + 统一导出
fetchers/realtime.py   → push2 主 + 腾讯备 实时行情（字段码抽查 + 部分数据防护）
fetchers/fundamental.py → lsjz 净值 + 申赎状态（Semaphore(5) 并发 + 重试）
fetchers/historical.py → push2his 日线 K 线（AkShare 备源 + 8 级降级）
fetchers/info.py       → fundf10 持仓 + 基础信息 + 费率（分批 + 进度持久化 + HTML 变更检测）

## 数据处理
processors/__init__.py  → 工具函数
processors/normalize.py → 多源字段映射（push2/腾讯/lsjz/fundf10 → 统一格式）
processors/validator.py → 校验 + 去重 + 涨跌停标记 + 异常检测
processors/calculator.py → 派生字段计算（溢价率/换手率/涨跌幅/预计收益率/三日均溢）
processors/saver.py     → DB 批量 UPSERT（分批 100 条/事务）+ 刷新物化视图
processors/pipeline.py  → Stream 消费者主循环（5 种事件分派 + 毒消息处理）

## 公式引擎
formula_engine/fields.py    → 字段白名单（25 个字段，7 组）
formula_engine/parser.py    → AST 解析 + 校验 + 依赖分析 + 环检测 + LRU 缓存
formula_engine/evaluator.py → 安全求值（compile → evaluate → batch_evaluate）

## 业务服务层
services/fund_service.py    → 基金查询 + 实时合并 + 缓存击穿保护 + 降级标记
services/asset_service.py   → 资产查询
services/data_service.py    → 日线查询 + 字段白名单 + 日期校验
services/formula_service.py → 公式 CRUD + 乐观锁 + 并发限制 + 删除检查
services/alert_service.py   → 预警 CRUD + 条件解析 + 触发检查
services/system_service.py  → 健康检查 + 监控 + 诊断 + 操作 + 审计 + 物化视图锁
services/sse_service.py     → SSE 增量推送 + 心跳 + 连接清理

## 中台编排
hub/__init__.py    → 包初始化
hub/service.py     → 编排器（调 Service + 跨 Service 协调 + 缓存失效）

## 认证 + 权限
auth/__init__.py      → 包初始化
auth/middleware.py     → JWT 验证 + 身份注入 + 请求日志
auth/dependencies.py  → get_user_id / require_admin / require_paid / get_optional_user

## API 路由层
routers/__init__.py   → 路由注册
routers/system.py     → /health（公开）
routers/funds.py      → 基金端点（列表/详情/批量/图表/持仓/导出）
routers/assets.py     → 资产端点
routers/data.py       → 日线查询（字段白名单校验）
routers/formulas.py   → 公式 CRUD + 校验（乐观锁 + 409 处理）
routers/watchlist.py  → 自选列表
routers/alerts.py     → 预警规则（P1）
routers/admin.py      → 诊断 + 操作 + 日志 + 管理后台（15 个端点）
routers/stream.py     → SSE 实时推送（P2）

## 数据模型 + 校验
schemas/__init__.py   → 包初始化
schemas/request.py    → 请求模型（9 个 + 排序白名单 + 代码清洗 + 日期校验）
schemas/response.py   → 响应模型（13 个）

## 调度
scheduler.py          → APScheduler 定时任务（9 个 job + 重启补执行 + QDII 延迟重试）

## 运维脚本（服务器端）
scripts/deploy.sh         → 一键部署 + 前置检查 + 失败回滚
scripts/rollback.sh       → 一键回滚
scripts/backup.sh         → 每日备份
scripts/verify_backup.sh  → 每周备份验证
scripts/weekly_cleanup.sh → 日志清理 + VACUUM + 磁盘检查

## 测试
tests/test_m1_smoke.py         → M1 冒烟测试（14 项）
tests/test_auth.py             → M2 认证测试（14 项）
tests/test_fetchers.py         → M3 采集层测试
tests/test_processors.py       → M4 处理层测试
tests/test_formula_engine.py   → M5 公式引擎测试
tests/test_formula_consistency.py → 前后端公式一致性测试
tests/test_services.py         → M6 服务层测试

## SQL
sql/migrations/      → 迁移文件（{序号}_{描述}.sql + _rollback.sql）
sql/seed/            → 种子数据（交易日历 + 50 只基金 + 30 天日线）

## AI 治理
.ai/context.md           → AI 会话上下文（3 秒了解项目）
.ai/file_index.md        → 本文件
.ai/impact_matrix.json   → 模块依赖 + 影响范围
.ai/benchmarks.json      → 性能基准线
.ai/module_health.json   → 模块健康度
.ai/api_contract.json    → API 契约（字段 + 类型）
.ai/knowledge_base.md    → 已知问题知识库
.ai/review_checklist.md  → 代码审查自查清单
.ai/conventions.md       → AI 协作约定
.ai/prompts/fix_bug.md   → 修 Bug 标准流程
.ai/prompts/add_feature.md → 加功能标准流程
.ai/prompts/ops_diagnose.md → 运维诊断标准流程
.ai/scripts/assess_change.sh → 变更影响评估脚本
