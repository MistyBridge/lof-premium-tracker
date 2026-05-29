# 金快查 V2 开发计划

## 开发原则

1. **先能跑，再跑好**：每个阶段的目标是能在本地或服务器上运行，不是完美
2. **先骨架，再填肉**：先搭框架验证数据流，再填充业务逻辑
3. **每步可验证**：每个阶段结束时有明确的验证标准，能跑通才算完成
4. **AI 从第一步就参与**：.ai/ 文件在第一个阶段就创建，后续每个阶段同步更新

---

## 阶段总览

阶段0: 项目脚手架（2小时）
  ↓
阶段1: 运维工程（3小时）—— 能部署到服务器
  ↓
阶段2: AI 可管理性（2小时）—— AI 能理解和操作项目
  ↓
阶段3: M1 基础设施层（4小时）—— 能启动服务
  ↓
阶段4: M2 认证层（2小时）—— 能鉴权
  ↓
阶段5: M3 采集层（4小时）—— 能采集数据
  ↓
阶段6: M4 处理层（4小时）—— 能清洗入库
  ↓
阶段7: M5 公式引擎（3小时）—— 能计算公式
  ↓
阶段8: M6 服务层（4小时）—— 能查询数据
  ↓
阶段9: M7 调度层（2小时）—— 能自动运行
  ↓
阶段10: M8 路由层（3小时）—— 能调 API
  ↓
阶段11: M9 前端对接（4小时）—— 能在浏览器用
  ↓
阶段12: 联调+优化+上线（4小时）

总计约 37 小时

---

## 阶段 0：项目脚手架

**目标：** 本地有一个能 git clone 后 5 分钟内跑起来的项目骨架。

### 做什么

1. Git 仓库初始化
2. 创建目录结构（按 M1 设计的文件位置）
3. docker-compose.dev.yml（本地 PostgreSQL + Redis）
4. .env.dev（指向本地 DB/Redis）
5. .gitignore
6. requirements.txt（锁定版本）
7. 空的 app.py
8. 空的 __init__.py 文件

### 验证标准

git clone → docker-compose up -d → pip install → uvicorn app:app → 浏览器返回 ok

### 预计耗时：2 小时

---

## 阶段 1：运维工程

**目标：** 服务器上有一个能部署、能回滚、能监控的基础环境。

### 做什么

按 docs/plan/运维工程.md 实施：

1. 阿里云环境搭建（PostgreSQL 14 + Redis 7 + Python 3.11 + Nginx）
2. systemd 服务配置（MemoryMax=512M, Restart=always, TimeoutStopSec=30）
3. deploy.sh（一键部署 + 前置检查 + 失败回滚）
4. rollback.sh（一键回滚）
5. backup.sh + verify_backup.sh（每日备份 + 每周验证）
6. weekly_cleanup.sh（日志清理 + VACUUM + 磁盘检查）
7. .bash_aliases（SSH 快捷命令）
8. ufw 防火墙（只开放 22/80/443）

### 验证标准

- deploy.sh 执行成功 → health check 返回 ok
- rollback.sh 能回滚到上一个版本
- backup.sh 能生成备份文件到 OSS
- jk-health / jk-status / jk-log 命令可用

### 预计耗时：3 小时

---

## 阶段 2：AI 可管理性

**目标：** AI 接手项目时能在 3 秒内了解全貌，修改代码时能自动评估影响。

### 做什么

按 docs/plan/AI可管理性.md 创建 .ai/ 目录下的所有文件：

1. 上下文文件（context.md + file_index.md）
2. 工程规范文件（conventions.md + review_checklist.md）
3. AI 操作流程（prompts/fix_bug.md + add_feature.md + ops_diagnose.md + ops_fix.md）
4. 项目元数据（impact_matrix.json + benchmarks.json + module_health.json + api_contract.json + knowledge_base.md）
5. 项目文档（ARCHITECTURE.md + DATA_DICTIONARY.md + constants.py + verify.sh + sql/seed/ + sql/migrations/）
6. 评估脚本（.ai/scripts/assess_change.sh）

### 验证标准

- AI 读 .ai/context.md → 3 秒了解项目
- AI 读 .ai/impact_matrix.json → 知道修改影响范围
- verify.sh 能正常运行

### 预计耗时：2 小时

---

## 阶段 3：M1 基础设施层

**目标：** FastAPI 服务能启动，能连 DB 和 Redis，能执行迁移。

### 做什么

按 docs/plan/M1_基础设施层.md 实施，顺序：

1. config.py（Pydantic Settings）
2. constants.py（业务常量）
3. exceptions.py（异常类 + 错误码 + 全局处理器）
4. database.py（SQLAlchemy async engine + session）
5. models.py（16 张表 ORM 模型）
6. migration.py（建表 + 分区 + 物化视图 + 日历预置 + 校验）
7. trade_calendar.py（交易日判断）
8. cache.py（Redis 缓存 + 降级）
9. mq.py（Redis Streams）
10. metrics.py（监控指标 + 告警）
11. app.py（lifespan + 中间件骨架 + 全局异常处理器）
12. tests/test_m1_smoke.py（冒烟测试）

### 验证标准

- python migration.py → 16 张表 + 物化视图 + 分区全部创建
- pytest tests/test_m1_smoke.py → 14 项全部通过
- uvicorn app:app → /api/v1/health 返回 ok

### 预计耗时：4 小时

---

## 阶段 4：M2 认证层

**目标：** API 能鉴权，不同权限的用户看到不同内容。

### 做什么

按 docs/plan/M2_认证层.md 实施：

1. auth/__init__.py
2. auth/middleware.py（JWT 验证 + 身份注入 + 请求日志）
3. auth/dependencies.py（get_user_id / require_admin / get_optional_user）
4. CORS 配置（在 app.py 中挂载 CORSMiddleware）
5. tests/test_auth.py（14 项测试）

### 验证标准

- 无 token 请求 /api/v1/health → 正常响应
- 无 token 请求 /api/v1/funds → 40101
- 有效 token → 正常响应，user_id 正确注入
- 过期 token → 40102
- 管理员访问 admin 端点 → 正常
- 普通用户访问 admin 端点 → 40301

### 预计耗时：2 小时

---

## 阶段 5：M3 采集层

**目标：** 能从外部 API 获取数据并发布到 Redis Stream。

### 做什么

按 docs/plan/M3_数据采集层.md 实施：

1. fetchers/__init__.py（工具函数 + 统一导出）
2. fetchers/realtime.py（push2 主 + 腾讯备 + 字段码抽查 + 部分数据防护）
3. fetchers/fundamental.py（lsjz 批量 + Semaphore(5) + 重试）
4. fetchers/historical.py（push2his 主 + AkShare 备 + 资产日线）
5. fetchers/info.py（fundf10 爬取 + 分批进度 + HTML 变更检测）
6. tests/test_fetchers.py

### 验证标准

- fetch_realtime() → 返回约 1500 条数据
- push2 失败 → 自动降级腾讯
- 数据量 < 80% → 不覆盖旧数据
- fetch_info 中断后重启 → 从 last_code 续接
- 所有 fetcher 发布到 Stream → consume_events 能读到

### 预计耗时：4 小时

---

## 阶段 6：M4 处理层

**目标：** Stream 消费者能处理事件，数据能清洗入库。

### 做什么

按 docs/plan/M4_数据处理层.md 实施：

1. processors/normalize.py（4 个 normalize 函数 + to_optional_float + clean_code）
2. processors/validator.py（校验 + 去重 + 涨跌停标记 + 异常检测）
3. processors/calculator.py（6 个 calc 函数 + calc_daily_fields）
4. processors/saver.py（batch_upsert + refresh_mv + ensure_partition）
5. processors/pipeline.py（消费者主循环 + 5 个 process 函数 + daily_save + 毒消息处理）
6. 回溯修改 M3 fetcher（确认只输出原始数据，不做字段映射）
7. tests/test_processors.py

### 验证标准

- normalize push2 数据 → 字段正确映射，类型正确
- validator 价格 <= 0 → 标记异常但保留
- calculator calc_premium_rate(2.0, 1.8) → 11.1111
- saver 1500 条写入 → 分 15 批全部成功
- pipeline 消费 daily_save → fund_daily 入库 + 物化视图刷新
- 毒消息失败 3 次 → 强制 ack

### 预计耗时：4 小时

---

## 阶段 7：M5 公式引擎（可与阶段 5/6 并行）

**目标：** 前后端都能解析和求值用户自定义公式。

### 做什么

按 docs/plan/M5_公式引擎.md 实施：

1. formula_engine/fields.py（25 字段白名单 + JSON 导出）
2. formula_engine/parser.py（parse + validate + complexity + analyze_dependencies + LRU）
3. formula_engine/evaluator.py（compile + evaluate + batch_evaluate + 性能边界）
4. tests/test_formula_engine.py（test_cases.json）
5. frontend/src/formula/fields.ts（从 JSON 导入）
6. frontend/src/formula/parser.ts（JS 版解析 + 校验）
7. frontend/src/formula/evaluator.ts（JS 版求值，容错返回 null）
8. tests/test_formula_consistency.py（前后端一致性）

### 验证标准

- close / nav - 1 → 正常解析求值
- A->B->C->A 循环 → 40002 + cycle 路径
- 1500 基金 x 5 公式 → < 500ms（Python）/ < 200ms（JS）
- Python 和 JS 同一组 test_cases → 结果一致

### 预计耗时：3 小时

---

## 阶段 8：M6 服务层

**目标：** Hub + Service 能组装完整的 API 响应。

### 做什么

按 docs/plan/M6_业务服务层.md 实施：

1. services/fund_service.py（基金查询 + 缓存击穿保护 + 降级标记 + 筛选增强）
2. services/asset_service.py（资产查询）
3. services/data_service.py（日线查询 + 字段白名单 + 日期校验）
4. services/formula_service.py（CRUD + 乐观锁 + 并发限制 + 删除检查）
5. services/alert_service.py（预警 CRUD + 条件解析 + 触发检查）
6. services/system_service.py（健康 + 监控 + 诊断 + 操作 + 审计 + 物化视图锁）
7. services/sse_service.py（SSE 增量推送 + 心跳 + 连接清理）
8. hub/service.py（编排 + 跨 Service 协调 + 缓存失效）
9. tests/test_services.py

### 验证标准

- fund_service.get_fund_list() → 分页数据 + 实时溢价率
- Redis 不可用 → DB 数据 + realtime_available: false
- formula_service 乐观锁 → version 不匹配返回 409
- 物化视图并发刷新 → 第 2 个返回"进行中"
- admin_write 操作 → 写入 admin_audit_log

### 预计耗时：4 小时

---

## 阶段 9：M7 调度层

**目标：** 定时任务能自动运行，数据每日自动更新。

### 做什么

按 docs/plan/M7_调度层.md 实施：

1. scheduler.py（9 个定时任务 + job 统一配置）
2. 重启补执行逻辑（查 job_log，补执行错过的任务）
3. QDII 依赖处理（非 QDII 先入库，QDII 延迟重试）
4. fetch_info 分批逻辑（先重试 failed_codes，再取新批次）
5. 消费者启动（在 app.py lifespan 中 stream_consumer 协程）
6. 交易日历数据验证

### 验证标准

- 交易时段 → fetch_realtime 每 5 分钟触发
- 非交易日 → 任务跳过
- 进程重启 → 错过的任务补执行
- job_log 记录每次执行的 status + duration_ms
- 连续 3 次失败 → metrics.alert() 触发

### 预计耗时：2 小时

---

## 阶段 10：M8 路由层

**目标：** 45 个 API 端点全部可用，OpenAPI 文档自动生成。

### 做什么

按 docs/plan/M8_路由层.md 实施：

1. schemas/request.py（9 个请求模型 + 排序白名单 + 代码清洗 + 日期校验）
2. schemas/response.py（13 个响应模型）
3. routers/system.py（/health，公开）
4. routers/funds.py（6 个端点）
5. routers/assets.py（4 个端点）
6. routers/data.py（3 个端点 + 字段白名单）
7. routers/formulas.py（11 个端点 + 乐观锁 + 409 处理）
8. routers/watchlist.py（3 个端点）
9. routers/alerts.py（3 个端点，P1）
10. routers/admin.py（15 个端点 + 审计日志 + 防重）
11. routers/stream.py（1 个 SSE 端点，P2）
12. app.py 路由注册

### 验证标准

- 浏览器 /docs → 45 个端点全部列出
- GET /api/v1/funds?premium_min=5&fund_type=ETF → 筛选正确
- POST /api/v1/formulas + 非法表达式 → 40002
- OPTIONS /api/v1/funds → CORS 预检 200
- 基金代码 " 160,644 " → 清洗为 160644

### 预计耗时：3 小时

---

## 阶段 11：M9 前端对接

**目标：** 浏览器中能完整使用所有功能。

### 做什么

按 docs/plan/M9_前端对接层.md 实施：

**P0（必须）：**
1. js/api-client-v1.js（token 单例刷新 + 请求缓存 + 错误码分发）
2. js/column-manager.js（列管理器升级 + 旧 key 兼容）
3. js/filter-panel.js（增强筛选 + 防抖 + 预设保存）
4. js/watchlist.js（自选 + 乐观更新）
5. js/formula/（fields.js + parser.js + evaluator.js）
6. js/formula-editor.js（语法高亮 + 错误标记 + 示例 + 预览）
7. admin/index.html（管理后台静态页面）
8. 全局集成（三态 UI + data_type 处理 + 错误处理）

**P1：** js/alerts.js（预警 + AND/OR 条件组）

**P2：** sse-client / export / virtual-scroll / keyboard / status-indicator

### 验证标准

- 基金列表加载 → 数据正确渲染
- 筛选面板 → 7 个条件组合正确
- 公式编辑器 → 语法高亮 + 校验 + 实时预览
- 自选添加 → 星标立刻翻转（乐观更新）
- SSE 交易时段 → 增量更新 + 变化高亮
- 管理后台 → 监控数据 + 操作按钮可用

### 预计耗时：4 小时

---

## 阶段 12：联调 + 优化 + 上线

**目标：** 全链路跑通，部署到生产环境。

### 做什么

1. **联调测试**：采集 → 入库 → API → 前端完整数据流；交易/非交易时段；Redis 降级；并发
2. **性能优化**：对比 benchmarks.json；慢查询 EXPLAIN ANALYZE；响应压缩验证
3. **安全检查**：.env 不在 Git；敏感信息不泄露；CORS 正确；admin 需要权限
4. **上线部署**：deploy.sh；SSL 证书；DNS 切换；监控验证
5. **文档更新**：CHANGELOG.md；.ai/context.md；api_contract.json；benchmarks.json

### 验证标准

- 生产环境 health check → ok
- 前端页面正常加载 → 数据正确
- deploy.sh / rollback.sh → 正常工作

### 预计耗时：4 小时

---

## 阶段依赖关系

阶段0 → 阶段1 → 阶段2 → 阶段3 → 阶段4 → 阶段5 → 阶段6 → 阶段8 → 阶段9 → 阶段10 → 阶段11 → 阶段12
                                                  ↑
                            阶段7（可与阶段5/6并行）┘

## 每个阶段结束后的动作

1. 运行 verify.sh 确认验证标准通过
2. git commit + push
3. 更新 .ai/context.md
4. 更新 .ai/module_health.json
5. 更新 .ai/api_contract.json（如有 API 变更）
6. 更新 .ai/file_index.md（如有新文件）
7. 更新 .ai/impact_matrix.json（如有新依赖）
8. 更新 .ai/knowledge_base.md（如有新错误模式）

## 风险和应对

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| push2/fundf10 接口变更 | 中 | 数据采集中断 | 字段码抽查 + HTML 变更检测 + 告警 |
| 服务器资源不足 | 低 | 服务不稳定 | MemoryMax 限制 + 监控告警 + 升级路径 |
| 前后端公式引擎不一致 | 中 | 计算结果不同 | 共享 test_cases.json + 一致性测试 |
| 外部 API 限流 | 中 | 采集失败 | Semaphore 并发控制 + 重试 + 备源 |
| DB 磁盘满 | 低 | 写入失败 | weekly_cleanup + 磁盘告警 + 分区裁剪 |
