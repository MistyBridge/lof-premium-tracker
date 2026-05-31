# 数据字典

> 基于 models.py ORM 定义。字段类型以 PostgreSQL 实际存储为准。

---

## 1. fund_info - 基金基础信息

PK: code

| 字段 | 类型 | 说明 | 取值范围 | NULL | 来源 |
|------|------|------|----------|------|------|
| code | VARCHAR(6) | 基金代码 | 6位数字 | 否 | fund_code_list |
| name | VARCHAR(100) | 基金名称 | -- | 否 | push2/fundf10 |
| fund_type | VARCHAR(20) | 基金类型 | LOF/ETF/QDII | 是 | fundf10 |
| index_code | VARCHAR(20) | 跟踪指数 | 如000300 | 是 | fundf10 |
| market | CHAR(2) | 上市市场 | SH/SZ | 否 | push2delay |
| aum | NUMERIC(16,2) | 基金规模(亿元) | >0 | 是 | fundf10 |
| listing_date | DATE | 上市日期 | -- | 是 | fundf10 |
| redeem_days | INTEGER | 赎回到账天数 | 1-7 | 否(默认2) | fundf10 |
| qdii_quota_status | VARCHAR(20) | QDII额度状态 | open/suspended/limited | 否(默认open) | fundf10 |
| updated_at | TIMESTAMPTZ | 更新时间 | -- | 否 | 系统 |


---

## 2. fund_daily - 日线数据(365天)

PK: (code, trade_date)

| 字段 | 类型 | 说明 | 取值范围 | NULL | 来源 |
|------|------|------|----------|------|------|
| code | VARCHAR(6) | 基金代码 | 6位数字 | 否 | fund_code_list |
| trade_date | DATE | 交易日期 | 工作日 | 否 | trade_calendar |
| open | NUMERIC(12,4) | 开盘价 | >0 | 是(停牌) | push2his |
| high | NUMERIC(12,4) | 最高价 | >0 | 是(停牌) | push2his |
| low | NUMERIC(12,4) | 最低价 | >0 | 是(停牌) | push2his |
| close | NUMERIC(12,4) | 收盘价 | >0 | 是(停牌) | push2his/push2 |
| volume | BIGINT | 成交量(手) | >=0 | 是(停牌) | push2his |
| amount | NUMERIC(16,2) | 成交额(元) | >=0 | 是(停牌) | push2his/push2 |
| nav | NUMERIC(12,4) | 单位净值 | >0 | 是(QDII延迟) | lsjz |
| nav_date | DATE | 净值日期 | <=trade_date | 是 | lsjz |
| nav_type | VARCHAR(20) | 净值类型 | confirmed/estimated | 否(默认confirmed) | calculator |
| nav_source | VARCHAR(20) | 净值来源 | lsjz/estimated | 是 | fetcher |
| data_source | VARCHAR(20) | 价格来源 | push2/akshare/tencent/manual | 是 | fetcher |
| float_share | NUMERIC(16,2) | 流通份额(万份) | >0 | 是 | push2 |
| total_share | NUMERIC(16,2) | 总份额(万份) | >0 | 是 | push2 |
| premium_rate | NUMERIC(10,4) | 溢价率(%) | -100~+inf | 是 | calculator |
| turnover_rate | NUMERIC(10,4) | 换手率(%) | 0~100+ | 是 | calculator |
| change_pct | NUMERIC(10,4) | 涨跌幅(%) | -100~+inf | 是 | calculator |
| fetch_batch_id | VARCHAR(36) | 采集批次UUID | -- | 是 | 系统 |
| created_at | TIMESTAMPTZ | 创建时间 | -- | 否 | 系统 |
| updated_at | TIMESTAMPTZ | 更新时间 | -- | 否 | 系统 |


---

## 3. fund_fee - 费率数据(TTL 24h)

PK: code

| 字段 | 类型 | 说明 | 取值范围 | NULL | 来源 |
|------|------|------|----------|------|------|
| code | VARCHAR(6) | 基金代码 | 6位数字 | 否 | fund_code_list |
| purchase_fee_rate | NUMERIC(10,4) | 申购费率(%) | 0~5 | 是 | fundf10 |
| redemption_fee_rate | NUMERIC(10,4) | 赎回费率(%) | 0~5 | 是 | fundf10 |
| purchase_limit | NUMERIC(16,2) | 申购限额(元) | >0 | 是(无限额) | fundf10 |
| purchase_status | VARCHAR(20) | 申购状态 | open/closed/suspended | 是 | fundf10 |
| redeem_status | VARCHAR(20) | 赎回状态 | open/closed/suspended | 是 | fundf10 |
| fetched_at | TIMESTAMPTZ | 抓取时间 | -- | 否 | 系统 |


---

## 4. fund_holdings - 十大持仓

PK: code

| 字段 | 类型 | 说明 | 取值范围 | NULL | 来源 |
|------|------|------|----------|------|------|
| code | VARCHAR(6) | 基金代码 | 6位数字 | 否 | fund_code_list |
| quarter | VARCHAR(10) | 报告期 | 如2026Q1 | 否 | fundf10 |
| report_date | DATE | 报告日期 | -- | 是 | fundf10 |
| holdings | JSONB | 持仓数据 | [{code,name,pct}] | 否(默认[]) | fundf10 |
| updated_at | TIMESTAMPTZ | 更新时间 | -- | 否 | 系统 |


---

## 5. fund_code_list - LOF代码列表

PK: code

| 字段 | 类型 | 说明 | 取值范围 | NULL | 来源 |
|------|------|------|----------|------|------|
| code | VARCHAR(6) | 基金代码 | 6位数字 | 否 | push2delay |
| name | VARCHAR(100) | 基金名称 | -- | 是 | push2delay |
| market | CHAR(2) | 上市市场 | SH/SZ | 否 | push2delay |
| last_seen | DATE | 最后出现日期 | -- | 否 | 系统 |
| updated_at | TIMESTAMPTZ | 更新时间 | -- | 否 | 系统 |


---

## 6. asset_master - 底层资产主表

PK: code

| 字段 | 类型 | 说明 | 取值范围 | NULL | 来源 |
|------|------|------|----------|------|------|
| code | VARCHAR(12) | 资产代码 | 如600519 | 否 | push2 |
| name | VARCHAR(100) | 资产名称 | -- | 否 | push2 |
| asset_type | VARCHAR(20) | 资产类型 | stock/index/bond | 是 | 系统 |
| market | CHAR(2) | 市场 | SH/SZ | 是 | push2 |
| updated_at | TIMESTAMPTZ | 更新时间 | -- | 否 | 系统 |


---

## 7. asset_daily - 资产日线(按月分区)

PK: (code, trade_date)

| 字段 | 类型 | 说明 | 取值范围 | NULL | 来源 |
|------|------|------|----------|------|------|
| code | VARCHAR(12) | 资产代码 | -- | 否 | asset_master |
| trade_date | DATE | 交易日期 | -- | 否 | trade_calendar |
| close | NUMERIC(12,4) | 收盘价 | >0 | 是 | push2 |
| change_pct | NUMERIC(10,4) | 涨跌幅(%) | -- | 是 | calculator |
| volume | BIGINT | 成交量 | >=0 | 是 | push2 |
| amount | NUMERIC(16,2) | 成交额 | >=0 | 是 | push2 |
| created_at | TIMESTAMPTZ | 创建时间 | -- | 否 | 系统 |


---

## 8. fund_asset_map - 基金-资产关联

PK: (fund_code, asset_code, report_date)

| 字段 | 类型 | 说明 | 取值范围 | NULL | 来源 |
|------|------|------|----------|------|------|
| fund_code | VARCHAR(6) | 基金代码 | -- | 否 | fund_info |
| asset_code | VARCHAR(12) | 资产代码 | -- | 否 | asset_master |
| report_date | DATE | 报告日期 | -- | 否 | fundf10 |
| weight | NUMERIC(8,4) | 持仓权重(%) | 0~100 | 是 | fundf10 |
| created_at | TIMESTAMPTZ | 创建时间 | -- | 否 | 系统 |


---

## 9. trade_calendar - 交易日历

PK: trade_date

| 字段 | 类型 | 说明 | 取值范围 | NULL | 来源 |
|------|------|------|----------|------|------|
| trade_date | DATE | 日期 | -- | 否 | 预置 |
| is_trading | BOOLEAN | 是否交易日 | true/false | 否 | 预置 |


---

## 10. fetch_progress - 分批采集进度

PK: task_name

| 字段 | 类型 | 说明 | 取值范围 | NULL | 来源 |
|------|------|------|----------|------|------|
| task_name | VARCHAR(50) | 任务名 | fetch_info/fetch_fee | 否 | 系统 |
| last_code | VARCHAR(12) | 上次处理代码 | -- | 是 | 系统 |
| completed | INTEGER | 已完成数 | >=0 | 否(默认0) | 系统 |
| total | INTEGER | 总数 | >=0 | 否(默认0) | 系统 |
| failed_codes | JSONB | 失败代码列表 | -- | 否(默认[]) | 系统 |
| updated_at | TIMESTAMPTZ | 更新时间 | -- | 否 | 系统 |


---

## 11. job_log - 定时任务执行记录

PK: id (auto)

| 字段 | 类型 | 说明 | 取值范围 | NULL | 来源 |
|------|------|------|----------|------|------|
| id | INTEGER | 主键 | auto | 否 | 系统 |
| job_name | VARCHAR(50) | 任务名 | fetch_realtime/daily_save等 | 否 | 系统 |
| status | VARCHAR(20) | 状态 | success/failed/running | 否 | 系统 |
| duration_ms | INTEGER | 耗时(ms) | >=0 | 是 | 系统 |
| detail | TEXT | 详情/错误信息 | -- | 是 | 系统 |
| started_at | TIMESTAMPTZ | 开始时间 | -- | 否 | 系统 |
| finished_at | TIMESTAMPTZ | 结束时间 | -- | 是 | 系统 |


---

## 12. admin_audit_log - 管理操作审计

PK: id (auto)

| 字段 | 类型 | 说明 | 取值范围 | NULL | 来源 |
|------|------|------|----------|------|------|
| id | INTEGER | 主键 | auto | 否 | 系统 |
| user_id | VARCHAR(64) | 操作者ID | -- | 否 | JWT |
| action | VARCHAR(100) | 操作类型 | cache_clear/refresh等 | 否 | 系统 |
| target | VARCHAR(200) | 操作目标 | -- | 是 | 系统 |
| detail | TEXT | 详情 | -- | 是 | 系统 |
| created_at | TIMESTAMPTZ | 操作时间 | -- | 否 | 系统 |


---

## 13. user_formula - 用户自定义公式(乐观锁)

PK: id (auto)

| 字段 | 类型 | 说明 | 取值范围 | NULL | 来源 |
|------|------|------|----------|------|------|
| id | INTEGER | 主键 | auto | 否 | 系统 |
| user_id | VARCHAR(64) | Supabase用户ID | UUID | 否 | JWT |
| group_id | INTEGER | 公式组FK | -- | 是(SET NULL) | user |
| name | VARCHAR(100) | 公式名称 | -- | 否 | 用户输入 |
| expression | TEXT | 公式表达式 | 如close/nav-1 | 否 | 用户输入 |
| description | VARCHAR(500) | 公式描述 | -- | 是 | 用户输入 |
| sort_order | INTEGER | 排序序号 | >=0 | 否(默认0) | 用户 |
| version | INTEGER | 版本号(乐观锁) | >=1 | 否(默认1) | 系统 |
| created_at | TIMESTAMPTZ | 创建时间 | -- | 否 | 系统 |
| updated_at | TIMESTAMPTZ | 更新时间 | -- | 否 | 系统 |


---

## 14. user_formula_group - 用户公式组

PK: id (auto)

| 字段 | 类型 | 说明 | 取值范围 | NULL | 来源 |
|------|------|------|----------|------|------|
| id | INTEGER | 主键 | auto | 否 | 系统 |
| user_id | VARCHAR(64) | Supabase用户ID | UUID | 否 | JWT |
| name | VARCHAR(100) | 组名称 | -- | 否 | 用户输入 |
| description | VARCHAR(500) | 组描述 | -- | 是 | 用户输入 |
| sort_order | INTEGER | 排序序号 | >=0 | 否(默认0) | 用户 |
| created_at | TIMESTAMPTZ | 创建时间 | -- | 否 | 系统 |
| updated_at | TIMESTAMPTZ | 更新时间 | -- | 否 | 系统 |


---

## 15. user_watchlist - 用户自选

PK: (user_id, fund_code)

| 字段 | 类型 | 说明 | 取值范围 | NULL | 来源 |
|------|------|------|----------|------|------|
| user_id | VARCHAR(64) | Supabase用户ID | UUID | 否 | JWT |
| fund_code | VARCHAR(6) | 基金代码 | 6位数字 | 否 | 用户输入 |
| sort_order | INTEGER | 排序序号 | >=0 | 否(默认0) | 用户 |
| created_at | TIMESTAMPTZ | 添加时间 | -- | 否 | 系统 |


---

## 16. user_alert - 用户预警规则

PK: id (auto)

| 字段 | 类型 | 说明 | 取值范围 | NULL | 来源 |
|------|------|------|----------|------|------|
| id | INTEGER | 主键 | auto | 否 | 系统 |
| user_id | VARCHAR(64) | Supabase用户ID | UUID | 否 | JWT |
| name | VARCHAR(100) | 预警名称 | -- | 否 | 用户输入 |
| fund_code | VARCHAR(6) | 基金代码 | 6位/NULL(全市场) | 是 | 用户输入 |
| condition | JSONB | 结构化条件 | 见下方 | 否 | 用户输入 |
| is_active | BOOLEAN | 是否启用 | true/false | 否(默认true) | 系统 |
| last_triggered_at | TIMESTAMPTZ | 最后触发时间 | -- | 是 | 系统 |
| created_at | TIMESTAMPTZ | 创建时间 | -- | 否 | 系统 |
| updated_at | TIMESTAMPTZ | 更新时间 | -- | 否 | 系统 |


---

## 物化视图 fund_snapshot

daily_save后REFRESH CONCURRENTLY。合并fund_daily+fund_info+fund_fee最新一天数据。
索引: idx_snapshot_code(code) UNIQUE

---

## 派生字段公式

| 字段 | 公式 | 说明 |
|------|------|------|
| premium_rate | (close-nav)/nav*100 | 收盘溢价率 |
| intraday_premium | (price-est_nav)/est_nav*100 | 盘中溢价率 |
| three_day_avg_premium | AVG(premium_rate)近3日 | 三日均溢 |
| turnover_rate | volume*100/float_share*100 | 换手率 |
| change_pct | (close-prev)/prev*100 | 涨跌幅 |
| estimated_yield | 用户参数化(佣金+费率折扣) | 预计收益率 |
