# 第二轮任务分配

---

## 柯1 — 补完 M1 + M4 处理层

### 任务A: 补完 migration.py（紧急）
migration.py 目前只有1行 placeholder。需要完整实现：
- CREATE TABLE IF NOT EXISTS（16张表，参考 models.py）
- CREATE INDEX IF NOT EXISTS（所有索引）
- asset_daily 按月分区（当月+下月）
- 物化视图 fund_snapshot
- 交易日历预置数据（2025-2026年中国股市交易日）
- 校验交易日数量（200-260）
- 命令行: python migration.py [check|status|seed|validate]
- 参考: docs/plan/M1_基础设施层.md 第十节

### 任务B: 补完 tests/test_m1_smoke.py
14项 pytest 冒烟测试，参考 docs/plan/M1_基础设施层.md 第十九节

### 任务C: M4 处理层（如A/B已完成）
创建以下文件：
1. processors/normalize.py — 多源字段映射（push2/腾讯/lsjz/fundf10 → 统一格式）
2. processors/validator.py — 校验+去重+涨跌停标记+异常检测
3. processors/calculator.py — 派生字段计算（溢价率/换手率/涨跌幅/预计收益率）
4. processors/saver.py — DB批量UPSERT（分批100条/事务）
5. processors/pipeline.py — Stream消费者主循环（5种事件分派+毒消息处理）
6. tests/test_processors.py — 处理层测试
参考: docs/plan/M4_数据处理层.md

---

## 柯2 — 补完剩余3个文件

### 任务: 完成以下3个文件
1. **DATA_DICTIONARY.md** — 目前只有 fund_info 1张表。需要补充全部16张表的字段字典：
   fund_info / fund_daily / fund_fee / fund_holdings / fund_code_list /
   asset_master / asset_daily / fund_asset_map / trade_calendar /
   fetch_progress / job_log / admin_audit_log / user_formula /
   user_formula_group / user_watchlist / user_alert
   每张表包含: 字段/类型/说明/取值范围/允许NULL/来源/常见查询SQL

2. **verify.sh** — 标准验证脚本（pytest+迁移检查+健康检查）

3. **sql/seed/seed_trade_calendar.sql** — 2025-2026年中国股市交易日历INSERT语句（约500行）

4. **sql/seed/seed_fund_code_list.sql** — 50只代表性LOF基金代码INSERT语句

---

## 柯3 — M3 数据采集层

任务文件已存在: backend-v2/tasks/柯3_M3采集层.md

创建以下文件：
1. fetchers/__init__.py — 更新（统一导出+工具函数）
2. fetchers/realtime.py — push2主+腾讯备（实时行情）
3. fetchers/fundamental.py — lsjz净值+申赎（Semaphore并发）
4. fetchers/historical.py — push2his主+AkShare备（日线K线）
5. fetchers/info.py — fundf10 HTML爬取（持仓+费率+分批进度）
6. tests/test_fetchers.py — 8项测试

参考: docs/plan/M3_数据采集层.md