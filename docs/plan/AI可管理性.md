# AI 可管理性 详细设计

## 核心原则

AI 能理解、能操作、能验证、能回滚。

**五层能力模型：**

| 层次 | 能力 | 依赖的支撑文件 |
|------|------|---------------|
| 理解 | AI 知道系统怎么工作 | context.md + file_index.md + ARCHITECTURE.md + DATA_DICTIONARY.md |
| 诊断 | AI 能查到系统状态 | admin API + 结构化日志 + knowledge_base.md |
| 操作 | AI 能执行修复操作 | admin API + prompts/*.md + conventions.md |
| 验证 | AI 能确认修改正确 | verify.sh + impact_matrix.json + benchmarks.json |
| 回滚 | AI 能撤销错误修改 | deploy.sh 回滚 + 迁移回滚 + DB 备份 |

---

## 一、.ai/ 目录文件（12 个）

所有 .ai/ 文件纳入 Git 版本管理（.ai/ 不加入 .gitignore），这样变更历史可追溯。

### 1.1 context.md

**用途：** AI 每次会话开始时读取，3 秒内了解项目全貌。

**模板：**

```markdown
# 金快查 - AI 上下文

## 项目简介
金快查 - 基金溢价率实时监控系统
技术栈: FastAPI + PostgreSQL + Redis + APScheduler
部署: 阿里云 2C2G, Nginx + systemd
前端: Cloudflare Pages（静态托管）
用户系统: Supabase Auth

## 当前状态
最新版本: v0.8.2
最近变更: 2026-05-29 新增缓存击穿保护
待处理: 预警系统（P1），SSE 实时推送（P2）

## 已知问题
- push2 字段码 f204（盘中估值）在部分基金上返回 0
- fundf10 持仓页偶发超时，需要重试

## 代码规范
- 异常用 exceptions.py 中的异常类，不用 HTTPException
- 日志用 logging 不用 print
- 配置用 config.py 不用硬编码
- 所有 Redis 操作有降级逻辑
- 所有 DB 操作用 async session

## 关键文件
- app.py: 入口
- hub/service.py: 中台编排
- processors/pipeline.py: 数据处理消费者
- scheduler.py: 定时任务
- formula_engine/: 公式引擎
```

**更新时机：** 每次大版本变更后，deploy.sh 自动追加"最近变更"。人工更新"已知问题"。

**技术选型：** Markdown 格式（AI 读取效率最高，比 JSON 更易理解上下文关系）。

---

### 1.2 file_index.md

**用途：** AI 需要改某个功能时，快速找到对应文件，不用全局搜索。

**模板：**

```markdown
# 文件索引（按功能分类）

## 数据采集
fetchers/realtime.py    → push2 + 腾讯实时行情（主备切换）
fetchers/fundamental.py → lsjz 净值+申赎（Semaphore(5) 并发）
fetchers/historical.py  → push2his 日线K线（AkShare 备源）
fetchers/info.py        → fundf10 持仓+基础信息（分批+进度持久化）

## 数据处理
processors/normalize.py → 多源字段映射（push2/腾讯/lsjz/fundf10 → 统一格式）
processors/validator.py → 校验+去重+涨跌停标记
processors/calculator.py → 派生字段计算（溢价率/换手率/涨跌幅/预计收益率）
processors/saver.py     → DB 批量 UPSERT（分批 100 条/事务）
processors/pipeline.py  → Stream 消费者主循环（5 种事件分派）

## 缓存+队列
cache.py                → Redis 缓存封装（含降级 + 缓存击穿保护）
mq.py                   → Redis Streams 封装（单条 stream:events）

## 公式引擎
formula_engine/fields.py    → 字段白名单（25 个字段，7 组）
formula_engine/parser.py    → AST 解析+校验+依赖分析+环检测
formula_engine/evaluator.py → 安全求值（compile→evaluate→batch_evaluate）

## API 层
routers/funds.py    → 基金端点（列表/详情/批量/图表/持仓/导出）
routers/assets.py   → 资产端点
routers/data.py     → 日线查询（字段白名单校验）
routers/formulas.py → 公式 CRUD + 校验（乐观锁）
routers/admin.py    → 诊断+操作+日志+管理后台
routers/stream.py   → SSE 实时推送

## 认证+权限
auth/middleware.py   → JWT 验证 + 身份注入
auth/dependencies.py → get_user_id / require_admin / require_paid

## 中台
hub/service.py       → 编排器（调 Service + 缓存失效）
services/fund_service.py    → 基金查询+实时合并+缓存击穿保护
services/formula_service.py → 公式 CRUD + 并发限制
services/system_service.py  → 健康检查+监控+刷新+物化视图锁

## 基础设施
config.py           → 配置集中管理（python-dotenv）
database.py         → SQLAlchemy async engine + session
models.py           → ORM 模型（11 张表）
trade_calendar.py   → 交易日判断（查 DB 缓存内存）
migration.py        → 建表+分区+物化视图+日历预置
exceptions.py       → 异常类层级+错误码+全局处理器
metrics.py          → 监控指标+告警
scheduler.py        → APScheduler 定时任务（9 个 job）
```

**更新时机：** 新增/删除文件时更新。

---

### 1.3 impact_matrix.json

**用途：** AI 修改某个模块前，自动评估影响范围、需要运行的测试、需要更新的文档。

**模板：**

```json
{
  "calculator.py": {
    "depends_on": ["fields.py", "exceptions.py"],
    "depended_by": ["pipeline.py", "evaluator.ts (frontend)"],
    "tests": ["test_calculator.py", "test_integration.py"],
    "affected_docs": ["DATA_DICTIONARY.md"],
    "risk": "medium",
    "notes": "修改计算公式后必须更新前后端一致性测试"
  },
  "fund_service.py": {
    "depends_on": ["database.py", "cache.py", "models.py", "exceptions.py"],
    "depended_by": ["hub/service.py"],
    "tests": ["test_fund_service.py", "test_integration.py"],
    "affected_docs": ["ARCHITECTURE.md", "api_contract.json"],
    "risk": "high",
    "notes": "含缓存击穿保护逻辑，修改缓存相关代码需谨慎"
  },
  "realtime.py": {
    "depends_on": ["mq.py", "metrics.py", "trade_calendar.py"],
    "depended_by": ["scheduler.py"],
    "tests": ["test_realtime.py"],
    "affected_docs": [],
    "risk": "medium",
    "notes": "push2 字段码是硬编码魔法数，修改前先确认字段映射"
  },
  "parser.py": {
    "depends_on": ["fields.py", "exceptions.py"],
    "depended_by": ["evaluator.py", "formula_service.py", "parser.ts (frontend)"],
    "tests": ["test_parser.py", "test_formula_consistency.py"],
    "affected_docs": ["ARCHITECTURE.md"],
    "risk": "low",
    "notes": "修改校验规则后必须同步更新前端 parser.ts"
  },
  "cache.py": {
    "depends_on": ["config.py"],
    "depended_by": ["fund_service.py", "formula_service.py", "pipeline.py"],
    "tests": ["test_cache.py", "test_integration.py"],
    "affected_docs": ["ARCHITECTURE.md"],
    "risk": "high",
    "notes": "所有 Redis 操作必须有降级逻辑，修改后全量回归测试"
  },
  "middleware.py": {
    "depends_on": ["config.py", "exceptions.py"],
    "depended_by": ["dependencies.py", "所有 router"],
    "tests": ["test_auth.py"],
    "affected_docs": ["ARCHITECTURE.md"],
    "risk": "high",
    "notes": "鉴权逻辑修改影响所有 API 端点"
  }
}
```

**使用方式：** AI 修改文件前读取 impact_matrix.json，修改后运行对应的 tests 列表。

---

### 1.4 benchmarks.json

**用途：** AI 修改代码后，对比性能基准线，发现退化。

**模板：**

```json
{
  "fund_list_api": {
    "p50_ms": 25,
    "p95_ms": 80,
    "p99_ms": 150,
    "measured_at": "2026-05-29",
    "conditions": "1500 funds, Redis warm, sort=amount desc, page=1"
  },
  "fund_detail_api": {
    "p50_ms": 15,
    "p95_ms": 40,
    "p99_ms": 80,
    "measured_at": "2026-05-29",
    "conditions": "single fund, Redis warm"
  },
  "formula_eval_1500_funds_5_formulas": {
    "p50_ms": 180,
    "p95_ms": 350,
    "p99_ms": 500,
    "measured_at": "2026-05-29",
    "conditions": "JS engine, compile+evaluate"
  },
  "push2_fetch_all": {
    "p50_ms": 800,
    "p95_ms": 2000,
    "p99_ms": 3500,
    "measured_at": "2026-05-29",
    "conditions": "single request, 1500 funds"
  },
  "lsjz_fetch_1500": {
    "p50_ms": 150000,
    "p95_ms": 180000,
    "p99_ms": 200000,
    "measured_at": "2026-05-29",
    "conditions": "1500 sequential, Semaphore(5), 0.3s interval"
  },
  "daily_save_1500_funds": {
    "p50_ms": 3000,
    "p95_ms": 5000,
    "p99_ms": 8000,
    "measured_at": "2026-05-29",
    "conditions": "batch 100, 15 batches"
  }
}
```

**测量方法：** `verify.sh` 中加 `--benchmark` 参数，自动记录每个关键路径的耗时到 benchmarks.json。

---

### 1.5 module_health.json

**用途：** AI 识别需要重构的模块，优先处理高风险模块。

**模板：**

```json
{
  "calculator.py": {
    "test_coverage": 95,
    "complexity": "low",
    "last_modified": "2026-05-20",
    "known_bugs": 0,
    "lines": 120,
    "health": "good"
  },
  "fund_service.py": {
    "test_coverage": 72,
    "complexity": "medium",
    "last_modified": "2026-05-29",
    "known_bugs": 1,
    "lines": 280,
    "health": "needs_attention",
    "notes": "缓存击穿保护逻辑复杂度高，建议拆分"
  },
  "pipeline.py": {
    "test_coverage": 65,
    "complexity": "medium",
    "last_modified": "2026-05-28",
    "known_bugs": 0,
    "lines": 200,
    "health": "needs_attention",
    "notes": "5 种事件处理逻辑应拆分为独立函数"
  }
}
```

**health 取值：** good / needs_attention / needs_refactor / deprecated

**更新方式：** 每周手动或脚本运行 `pytest --cov` + `radon cc`（复杂度分析），自动更新。

---

### 1.6 api_contract.json

**用途：** AI 修改 API 响应结构时，自动检查是否破坏了前端兼容性。

**模板：**

```json
{
  "GET /api/v1/funds": {
    "version": "v1",
    "response_fields": [
      "code", "name", "close", "nav", "premium_rate",
      "amount", "turnover_rate", "change_pct", "float_share",
      "fund_type", "purchase_status", "redeem_status"
    ],
    "required_fields": ["code", "name"],
    "meta_fields": ["page", "size", "total", "data_timestamp", "data_type", "realtime_available"],
    "last_changed": "2026-05-29",
    "change_reason": "新增 realtime_available 标记"
  },
  "GET /api/v1/funds/:code": {
    "version": "v1",
    "response_fields": [
      "info.code", "info.name", "info.fund_type", "info.index_code", "info.aum",
      "fee.purchase_fee_rate", "fee.redemption_fee_rate", "fee.purchase_status",
      "holdings[].code", "holdings[].name", "holdings[].pct",
      "latest_daily.close", "latest_daily.nav", "latest_daily.premium_rate"
    ],
    "required_fields": ["info.code", "info.name"],
    "last_changed": "2026-05-29"
  },
  "POST /api/v1/formulas": {
    "version": "v1",
    "request_fields": ["name", "expression", "description"],
    "required_fields": ["name", "expression"],
    "response_fields": ["id", "name", "expression", "description", "version", "created_at"],
    "last_changed": "2026-05-29"
  }
}
```

**检查方式：** AI 修改 API 后，对比 api_contract.json，如果有字段被删除或类型变更，标记为 breaking change。

---

### 1.7 knowledge_base.md

**用途：** AI 遇到错误时先查知识库，已有解决方案直接执行，不需要重新分析。

**模板：**

```markdown
# 已知问题知识库

## push2 超时
- 症状: fetcher/realtime 返回空列表
- 日志: [ERROR] [external_api] push2 connection timeout
- 原因: 东方财富偶尔限流或网络抖动
- 解决: 自动重试 3 次（tenacity），间隔 5 秒。仍失败切换腾讯备源
- 预防: 已有重试机制，通常自动恢复。连续 3 次失败触发告警
- 首次发现: 2026-05-15
- 出现频率: 每周 1-2 次

## Redis 连接断开
- 症状: API 返回 realtime_available: false
- 日志: [ERROR] [cache] Redis connection refused
- 原因: Redis 进程被 OOM killer 杀死（内存超 128MB）
- 解决: systemctl restart redis，检查 redis-cli info memory
- 预防: 已配置 maxmemory 128MB + allkeys-lru
- 首次发现: 2026-05-20
- 出现频率: 极少

## fundf10 HTML 解析失败
- 症状: info 采集返回空持仓
- 日志: [WARNING] [info] fundf10 parse failed for {code}
- 原因: 东方财富改版页面结构
- 解决: 检查 fundf10.eastmoney.com 页面，更新解析逻辑
- 预防: 连续 3 只解析失败自动中断并告警
- 首次发现: 2026-05-18
- 出现频率: 每月 1 次

## QDII 净值延迟
- 症状: 23:30 入库时 QDII 基金无当日净值
- 日志: [INFO] [daily_save] QDII nav not available for {code}, using estimated
- 原因: QDII 净值通常 T+1 或 T+2 才出
- 解决: 使用昨日净值，标记 nav_type='estimated'
- 预防: 23:00 单独跑一次 QDII 净值获取
- 首次发现: 2026-05-22
- 出现频率: 每个交易日

## 物化视图刷新慢
- 症状: 物化视图刷新耗时 > 5 秒
- 原因: fund_daily 数据量增长，JOIN 查询变慢
- 解决: 检查索引是否完整，VACUUM ANALYZE
- 预防: weekly_cleanup.sh 定期 VACUUM
- 首次发现: 待观察
- 出现频率: 待观察
```

**更新时机：** 每次遇到新的错误模式，记录症状+原因+解决方案。

---

### 1.8 review_checklist.md

**用途：** AI 写完代码后，对照清单自查，通过后才提交。

**模板：**

```markdown
# 代码审查自查清单

## 必查项（任何修改都要检查）
- [ ] 所有用户输入有校验（Pydantic model 或白名单）
- [ ] SQL 查询用参数化，无字符串拼接（grep f"SELECT 确认）
- [ ] 异常用 exceptions.py 中的类，不直接用 HTTPException
- [ ] 新增函数有 docstring（数据源/降级/Args/Returns/调用方）
- [ ] 新增函数有类型提示（参数+返回值）
- [ ] Redis 操作有 try-except 降级逻辑
- [ ] DB 操作在 async session 中，异常时自动 rollback
- [ ] 无硬编码魔法数字（用 constants.py 中的常量）
- [ ] 日志包含上下文（request_id, user_id, 操作参数）
- [ ] datetime 用 timezone-aware（datetime.now(timezone.utc)）
- [ ] Decimal 值入库前 round 到 4 位小数

## 测试项
- [ ] 新增代码有对应测试
- [ ] 测试覆盖正常路径和异常路径
- [ ] pytest tests/ 全部通过
- [ ] 核心模块覆盖率 > 90%（pytest --cov）

## 文档项
- [ ] CHANGELOG.md 已更新（或确认 deploy.sh 会自动更新）
- [ ] API 响应结构变更已更新 api_contract.json
- [ ] 新模块已更新 impact_matrix.json
- [ ] 新模块已更新 file_index.md
- [ ] 已知问题已更新 knowledge_base.md（如有新的错误模式）

## 安全项
- [ ] 无 SQL 注入风险
- [ ] 无 eval/exec 调用
- [ ] 公式引擎用 AST 白名单，不用 eval
- [ ] 敏感配置不出现在日志中（密码/token/密钥）
- [ ] admin 端点需要 admin 权限
```

---

### 1.9 conventions.md

**用途：** AI 和人类开发者的协作约定，确保一致性。

**模板：**

```markdown
# AI 协作约定

## 代码风格
- Python: PEP 8, black 格式化（line-length=100）
- TypeScript: prettier 格式化
- 每行最大 100 字符
- 变量命名: snake_case（Python）, camelCase（TypeScript）
- 常量命名: UPPER_SNAKE_CASE

## Git 约定
- commit message: type(scope): description
  - type: feat / fix / refactor / docs / test / chore
  - scope: fetcher / processor / router / formula / cache / auth
  - 示例: fix(fetcher): handle push2 timeout with retry
- 不要在一个 commit 中做多件事
- 大功能用 feature branch，完成后 PR 到 dev

## 沟通约定
- 不确定时问，不要猜
- 修改前先说计划，确认后再动手
- 每次修改说明理由，不只是"改了什么"
- 涉及数据库 schema 变更必须说明迁移方案

## 文件组织
- 新增文件前检查是否可以放在已有文件中
- 单文件不超过 300 行，超过则拆分
- 测试文件和源文件同目录或 tests/ 目录
- 配置相关放 config.py，不散落在各文件中

## 错误处理约定
- 业务异常用 exceptions.py 中的类
- 不在 service 层直接 raise HTTPException
- 所有外部调用（API/Redis/DB）必须有超时和重试
- 错误日志包含足够上下文，能独立定位问题
```

---

### 1.10 prompts/*.md（5 个标准操作流程）

**用途：** AI 执行常见任务时，按标准流程操作，避免遗漏步骤。

**fix_bug.md：**

```markdown
# 修 Bug 标准流程

## 步骤
1. 读 .ai/context.md 了解项目背景
2. 读 .ai/knowledge_base.md 查看是否已有解决方案
3. 复现问题:
   - 运行相关测试: pytest tests/test_xxx.py -v
   - 或调用诊断 API: GET /api/v1/admin/diagnose/xxx
   - 或查看日志: GET /api/v1/admin/logs?level=ERROR&lines=50
4. 定位根因:
   - 不要用猜，用日志/数据/测试确认
   - 如果是数据问题，查 /api/v1/admin/diagnose/fund?code=xxx
5. 修复:
   - 只改必要的文件，不做无关重构
   - 读 .ai/impact_matrix.json 确认影响范围
6. 验证:
   - 运行受影响模块的测试: pytest tests/test_xxx.py
   - 运行 verify.sh 确认全量通过
7. 记录:
   - 更新 CHANGELOG.md（如果 deploy.sh 不自动处理）
   - 更新 .ai/knowledge_base.md（如果是新的错误模式）
   - 更新 .ai/context.md 的"已知问题"（如果解决了已知问题）
```

**add_feature.md：**

```markdown
# 加功能标准流程

## 步骤
1. 读 .ai/context.md 了解项目背景
2. 读 .ai/ARCHITECTURE.md 了解系统架构
3. 读 .ai/impact_matrix.json 确认需要修改的模块
4. 设计方案:
   - 说明要改哪些文件、新增哪些文件
   - 说明数据库是否需要迁移
   - 说明 API 是否有变更
   - 读 .ai/conventions.md 确认代码风格
5. 实现:
   - 按设计方案逐文件修改
   - 每个文件修改后立即运行相关测试
6. 验证:
   - 运行 verify.sh 全量验证
   - 如果有 API 变更，更新 .ai/api_contract.json
7. 记录:
   - 更新 .ai/file_index.md（新增文件）
   - 更新 .ai/impact_matrix.json（新增依赖关系）
   - 更新 CHANGELOG.md
```

**ops_diagnose.md：**

```markdown
# 运维诊断标准流程

## 步骤
1. 读 .ai/context.md 了解当前状态
2. 读 .ai/knowledge_base.md 查看已知问题
3. 调用诊断 API 获取系统状态:
   - GET /api/v1/health → 整体状态
   - GET /api/v1/admin/monitor → 详细监控
   - GET /api/v1/admin/diagnose/redis → Redis 状态
   - GET /api/v1/admin/diagnose/db → 数据库状态
   - GET /api/v1/admin/diagnose/fetcher → 采集状态
   - GET /api/v1/admin/diagnose/queue → 队列状态
4. 分析:
   - 对比 .ai/benchmarks.json 判断是否异常
   - 对比 .ai/knowledge_base.md 判断是否已知问题
5. 输出诊断报告:
   - 问题描述
   - 根因分析
   - 建议操作
   - 风险评估
```

---

### 1.11 scripts/assess_change.sh

**用途：** AI 修改代码前，自动评估影响范围。

**实现：**

```bash
#!/bin/bash
# .ai/scripts/assess_change.sh
# 用法: bash .ai/scripts/assess_change.sh fund_service.py calculator.py

echo "=== 变更影响评估 ==="
echo "修改文件: $@"
echo ""

for file in "$@"; do
    echo "--- $file ---"

    # 从 impact_matrix.json 提取依赖
    echo "依赖模块:"
    python3 -c "
import json
with open('.ai/impact_matrix.json') as f:
    matrix = json.load(f)
if '$file' in matrix:
    info = matrix['$file']
    print(f\"  depends_on: {info.get('depends_on', [])}\")
    print(f\"  depended_by: {info.get('depended_by', [])}\")
    print(f\"  risk: {info.get('risk', 'unknown')}\")
    print(f\"  notes: {info.get('notes', 'none')}\")
else:
    print('  未在 impact_matrix.json 中找到')
"

    # 列出需要运行的测试
    echo "需要运行的测试:"
    python3 -c "
import json
with open('.ai/impact_matrix.json') as f:
    matrix = json.load(f)
if '$file' in matrix:
    for t in matrix['$file'].get('tests', []):
        print(f'  pytest tests/{t} -v')
"

    # 列出需要更新的文档
    echo "需要更新的文档:"
    python3 -c "
import json
with open('.ai/impact_matrix.json') as f:
    matrix = json.load(f)
if '$file' in matrix:
    for d in matrix['$file'].get('affected_docs', []):
        print(f'  {d}')
"
    echo ""
done

echo "=== 完成 ==="
```

---

### 1.12 AI 会话初始化流程

**用途：** AI 开始新会话时的标准化流程。

```
AI 会话开始
  ↓
读 .ai/context.md → 了解项目背景、当前状态、已知问题
  ↓
读 .ai/conventions.md → 了解代码风格和协作约定
  ↓
等待用户指令
  ↓
收到指令后:
  修 Bug → 读 prompts/fix_bug.md
  加功能 → 读 prompts/add_feature.md
  运维 → 读 prompts/ops_diagnose.md
  ↓
读 .ai/impact_matrix.json → 确认需要修改的模块
  ↓
读 .ai/knowledge_base.md → 确认是否有已知解决方案
  ↓
执行操作
  ↓
运行 verify.sh → 确认修改正确
  ↓
更新相关 .ai/ 文件
```

---

## 二、项目文档（独立文件）

### 2.1 ARCHITECTURE.md

**用途：** 系统全局地图，AI 理解架构的核心参考。

**模板结构：**

```markdown
# 系统架构

## 技术栈
- 后端: FastAPI + SQLAlchemy async + asyncpg
- 缓存: Redis（缓存+Streams 消息队列）
- 数据库: PostgreSQL 14（shared_buffers=192MB）
- 定时任务: APScheduler（进程内）
- 前端: Cloudflare Pages（静态托管）
- 用户系统: Supabase Auth（JWT）
- 部署: 阿里云 2C2G, Nginx + systemd

## 分层架构
[前端] → [Nginx] → [认证中间件] → [路由层] → [Hub 编排器] → [Service 层] → [存储层]
                                                                        ↑
[定时任务] → [Fetcher] → [Redis Stream] → [Consumer/Processor] → [DB/Redis]

## 数据流
### 交易时段（9:30-15:00）
每5分钟: push2 → Stream → Consumer → Redis rt:all (TTL 60s) + rt:close:{date}
AkShare 交叉验证在后台异步执行

### 日终（20:00-23:30）
20:00  lsjz → Stream → Consumer → Redis nav:all
20:30  push2his → Stream → Consumer → Redis kline:fund:{date}
23:00  lsjz QDII 补充
23:30  scheduler → Stream → Consumer → 合并 → 计算 → DB fund_daily → 刷新物化视图

### 每周
周一~周五: fundf10 分批 → Stream → Consumer → DB fund_info/fund_fee/fund_holdings
周一: push2 代码列表扫描

## 模块依赖关系
[简化版依赖图，展示核心模块间的调用关系]

## 设计决策（ADR）
### 为什么用 SQLAlchemy async 而不是 asyncpg 直连
- ORM 查询可读性好，适合 API 层
- 批量写入用原生 SQL（executemany），性能不受影响
- 2C2G 不需要 ORM 的额外开销担忧（查询量小）

### 为什么用 Redis Streams 而不是 asyncio.Queue
- 进程崩溃后 Stream 数据不丢失
- 单进程下 asyncio.Queue 也够用，但 Stream 更利于后续扩展
- 技术锻炼目的

### 为什么公式结果不存后端
- 后端零计算开销
- 用户隐私（公式策略不经过服务器）
- 离线可用（前端缓存后可断网计算）

## 已知限制
- 单机架构，无水平扩展能力
- 2C2G 内存有限，Redis maxmemory=128MB
- push2 字段码是硬编码，可能随 API 变化
- fundf10 爬取依赖 HTML 结构，改版时需更新解析
```

---

### 2.2 DATA_DICTIONARY.md

**用途：** AI 写 SQL 查询或排查数据问题时，了解每个字段的含义。

**模板（以 fund_daily 为例）：**

```markdown
# 数据字典

## fund_daily
基金每日交易数据。每个交易日每只基金一条记录。
主键: (code, trade_date)
分区: 无（数据量可控，37.5万行/年）
索引: idx_daily_code_date(code, trade_date DESC), idx_daily_date(trade_date DESC)

| 字段 | 类型 | 说明 | 取值范围 | 允许 NULL | 来源 |
|------|------|------|----------|-----------|------|
| code | VARCHAR(10) | 基金代码 | 6位数字，如 160644 | 否 | fund_code_list |
| trade_date | DATE | 交易日期 | 工作日 | 否 | trade_calendar |
| name | VARCHAR(50) | 基金名称 | - | 否 | push2 |
| open | NUMERIC(12,4) | 开盘价 | > 0 | 是（停牌） | push2his |
| high | NUMERIC(12,4) | 最高价 | > 0 | 是（停牌） | push2his |
| low | NUMERIC(12,4) | 最低价 | > 0 | 是（停牌） | push2his |
| close | NUMERIC(12,4) | 收盘价 | > 0 | 是（停牌） | push2his |
| volume | BIGINT | 成交量（手） | >= 0 | 是（停牌） | push2his |
| amount | NUMERIC(18,2) | 成交额（元） | >= 0 | 是（停牌） | push2his |
| nav | NUMERIC(12,6) | 单位净值 | > 0 | 是（QDII延迟） | lsjz |
| nav_date | DATE | 净值日期 | <= trade_date | 是 | lsjz |
| nav_type | VARCHAR(10) | 净值类型 | confirmed / estimated | 否 | calculator |
| premium_rate | NUMERIC(8,4) | 收盘溢价率% | 理论 -100 ~ +∞ | 是 | calculator |
| turnover_rate | NUMERIC(8,4) | 换手率% | 0 ~ 100+ | 是 | calculator |
| change_pct | NUMERIC(8,4) | 涨跌幅% | 理论 -100 ~ +∞ | 是 | calculator |
| float_share | NUMERIC(16,2) | 流通份额（万份） | > 0 | 是 | push2 |
| total_share | NUMERIC(16,2) | 总份额（万份） | > 0 | 是 | push2 |
| limit_up | NUMERIC(12,4) | 涨停价 | > 0 | 是 | push2 |
| limit_down | NUMERIC(12,4) | 跌停价 | > 0 | 是 | push2 |
| risk_warning | VARCHAR(50) | 风控提示 | 涨停标的/跌停标的/NULL | 是 | validator |

### 常见查询
```sql
-- 获取最新交易日全部基金
SELECT * FROM fund_daily WHERE trade_date = (SELECT MAX(trade_date) FROM fund_daily);

-- 获取单只基金历史
SELECT * FROM fund_daily WHERE code = '160644' ORDER BY trade_date DESC LIMIT 60;

-- 高溢价基金
SELECT code, name, premium_rate FROM fund_daily
WHERE trade_date = (SELECT MAX(trade_date) FROM fund_daily)
AND premium_rate > 10
ORDER BY premium_rate DESC;
```
```

---

### 2.3 verify.sh

**用途：** AI 修改代码后的标准验证脚本。

```bash
#!/bin/bash
# verify.sh

set -e

echo "=== 1. 运行测试 ==="
pytest tests/ --tb=short -q
echo "✓ 测试通过"

echo ""
echo "=== 2. 检查类型 ==="
pyright --outputjson > /dev/null 2>&1 && echo "✓ 类型检查通过" || echo "⚠ 类型检查有警告"

echo ""
echo "=== 3. 检查覆盖率 ==="
pytest tests/ --cov=. --cov-report=term-missing --cov-fail-under=80 -q 2>/dev/null
echo "✓ 覆盖率检查通过"

echo ""
echo "=== 4. 检查数据库迁移 ==="
python migration.py check 2>/dev/null && echo "✓ 迁移检查通过" || echo "⚠ 需要执行迁移"

echo ""
echo "=== 5. 健康检查（如服务运行中）===" 
if curl -sf http://127.0.0.1:8000/api/v1/health > /dev/null 2>&1; then
    echo "✓ 服务健康"
else
    echo "⚠ 服务未运行（本地开发时正常）"
fi

echo ""
echo "=== 验证完成 ==="
```

---

### 2.4 sql/seed/（种子数据）

**用途：** AI 在本地测试时，数据库有真实数据。

| 文件 | 内容 | 数据量 |
|------|------|--------|
| seed_trade_calendar.sql | 当年交易日历 | ~244 行 |
| seed_fund_code_list.sql | 50 只代表性基金代码 | 50 行 |
| seed_fund_info.sql | 对应的基础信息 | 50 行 |
| seed_fund_fee.sql | 对应的费率 | 50 行 |
| seed_fund_daily.sql | 最近 30 天日线 | 1,500 行 |

**使用方式：** `python migration.py seed` → 按顺序执行所有 seed 文件。

---

### 2.5 sql/migrations/（迁移+回滚）

**命名规范：** `{序号}_{描述}.sql` + `{序号}_{描述}_rollback.sql`

```
sql/migrations/
  001_init.sql                     # 建表
  001_init_rollback.sql            # DROP TABLE
  002_add_nav_type.sql             # ALTER TABLE ADD COLUMN
  002_add_nav_type_rollback.sql    # ALTER TABLE DROP COLUMN
  003_add_partitions.sql           # 创建分区
  003_add_partitions_rollback.sql  # 删除分区
```

**执行方式：**
```bash
python migration.py apply 003       # 执行 003
python migration.py rollback 003    # 回滚 003
python migration.py status          # 查看已执行的迁移
```

---

## 三、模块文档要求

### 3.1 __init__.py 声明格式

```python
# services/fund_service.py
"""
基金查询服务

依赖: database, cache, models, exceptions
被依赖: hub/service.py
对外接口: get_fund_list, get_fund_detail, get_fund_batch, merge_realtime

数据源: fund_snapshot 物化视图 + Redis rt:all
降级: Redis 不可用时只返回 DB 数据，realtime_available=False
"""
```

### 3.2 公开函数 docstring 格式

```python
async def get_fund_list(
    page: int, size: int, sort: str, order: str,
    filter_type: str, search: str,
    db: AsyncSession
) -> dict:
    """
    获取基金列表（物化视图 + Redis 实时数据合并）

    数据源: fund_snapshot 物化视图 + Redis rt:all
    降级: Redis 不可用时只返回 DB 数据，realtime_available=False
    缓存击穿保护: Redis SET NX 锁，第一个请求查 DB 写缓存，其他等待

    Args:
        page: 页码，从 1 开始
        size: 每页条数，最大 100
        sort: 排序字段，白名单: premium_rate/close/amount/turnover_rate/change_pct
        order: asc/desc
        filter_type: all/premium/discount/trading/suspended
        search: 代码或名称模糊匹配（ILIKE）
        db: SQLAlchemy async session

    Returns:
        {"code": 0, "data": [...], "meta": {...}, "realtime_available": bool}

    调用方: hub/service.py
    """
```

### 3.3 测试覆盖率要求

| 模块 | 最低覆盖率 | 工具 |
|------|-----------|------|
| calculator.py | 95% | pytest-cov |
| parser.py | 95% | pytest-cov |
| evaluator.py | 95% | pytest-cov |
| normalize.py | 90% | pytest-cov |
| validator.py | 90% | pytest-cov |
| fund_service.py | 80% | pytest-cov |
| formula_service.py | 80% | pytest-cov |
| routers/*.py | 70% | pytest-cov |
| 其他 | 60% | pytest-cov |

### 3.4 类型检查

```bash
# Pyright 配置（pyrightconfig.json）
{
  "pythonVersion": "3.11",
  "typeCheckingMode": "basic",
  "reportMissingImports": true,
  "reportMissingTypeStubs": false
}
```

CI 中运行 `pyright`，warning 级别不阻断，error 级别阻断部署。

---

## 四、AI 操作边界

### 4.1 AI 可以做的操作

| 操作 | 方式 | 约束 |
|------|------|------|
| 查看系统状态 | /api/v1/admin/diagnose/* | 无限制 |
| 查看日志 | /api/v1/admin/logs | 无限制 |
| 查看缓存内容 | /api/v1/admin/diagnose/cache | 无限制 |
| 清空缓存 | /api/v1/admin/ops/cache/clear | 需要 admin_write 权限 |
| 触发采集 | /api/v1/admin/ops/refresh | 需要 admin_write 权限 |
| 刷新物化视图 | /api/v1/admin/ops/materialized-view/refresh | 需要 admin_write 权限 |
| 修改代码 | git commit + push | 必须通过 verify.sh |
| 执行迁移 | python migration.py apply | 必须配套 rollback 脚本 |

### 4.2 AI 不可以做的操作（需要人类确认）

| 操作 | 原因 |
|------|------|
| DROP TABLE / DROP DATABASE | 不可逆数据丢失 |
| DELETE FROM（批量删除） | 不可逆数据丢失 |
| 修改 .env 中的密钥 | 影响所有用户 |
| 修改 systemd/nginx 配置 | 可能导致服务不可用 |
| git push --force | 丢失历史 |
| 修改 auth/middleware.py | 影响所有 API 安全 |

### 4.3 AI 操作审计

所有 admin_write 操作记录到 admin_audit_log 表，包含：
- operator: 'ai_claude' / 'ai_codex' / 'admin_user'
- action: 操作类型
- target: 操作目标
- params: 请求参数
- result: success / failed
- created_at: 时间戳

---

## 五、.ai/ 文件维护规则

### 自动更新（deploy.sh）

| 文件 | 触发时机 | 更新内容 |
|------|---------|---------|
| CHANGELOG.md | 每次部署 | git log 追加 |
| context.md 最近变更 | 每次部署 | 追加最新 commit |

### 手动更新（AI 或人类）

| 文件 | 触发时机 | 更新者 |
|------|---------|-------|
| context.md 已知问题 | 遇到新问题/解决问题时 | AI |
| file_index.md | 新增/删除文件时 | AI |
| impact_matrix.json | 新增/修改模块依赖时 | AI |
| benchmarks.json | 性能测试后 | AI |
| module_health.json | 每周 | 人工/脚本 |
| api_contract.json | API 变更时 | AI |
| knowledge_base.md | 遇到新错误模式时 | AI |
| review_checklist.md | 代码规范变更时 | 人工 |
| conventions.md | 协作规范变更时 | 人工 |
| prompts/*.md | 流程优化时 | 人工 |

### 一致性检查

每次部署前，deploy.sh 自动检查：
- api_contract.json 中的端点是否和 routers/ 中的实际端点一致
- file_index.md 中的文件是否都存在
- impact_matrix.json 中的模块是否都存在

不一致时告警但不阻断部署。