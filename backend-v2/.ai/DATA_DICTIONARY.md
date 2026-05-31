# 数据字典

## fund_info — 基金基础信息

每只基金一条记录，由 fetch_info (fundf10) 采集更新。
主键: code

| 字段 | 类型 | 说明 | 允许NULL | 来源 |
|------|------|------|----------|------|
| code | VARCHAR(6) | 基金代码 | 否 | fund_code_list |
| name | VARCHAR(100) | 基金全称 | 否 | fundf10 基金全称 |
| fund_type | VARCHAR(20) | LOF/ETF/QDII | 是 | fundf10+名称推断 |
| index_code | VARCHAR(20) | 跟踪标的 | 是 | fundf10 跟踪标的 |
| market | CHAR(2) | SH/SZ | 否 | 代码前缀推断 |
| aum | NUMERIC(16,2) | 净资产规模(亿) | 是 | fundf10 净资产规模 |
| listing_date | DATE | 成立日期 | 是 | fundf10 成立日期/规模 |
| redeem_days | INTEGER | 赎回到账天数 | 否(默认2) | fundf10 卖出确认日 T+N |
| qdii_quota_status | VARCHAR(20) | QDII额度状态 | 否(默认open) | fundf10 |
| updated_at | TIMESTAMPTZ | 更新时间 | 否(默认NOW) | 自动 |

---

## fund_daily — 日线数据

每只基金每个交易日一条记录。保留 365 天。
主键: (code, trade_date)
索引: idx_daily_code_date(code, trade_date DESC), idx_daily_date(trade_date DESC)

| 字段 | 类型 | 说明 | 允许NULL | 来源 |
|------|------|------|----------|------|
| code | VARCHAR(6) | 基金代码 | 否 | - |
| trade_date | DATE | 交易日期 | 否 | - |
| open | NUMERIC(12,4) | 开盘价 | 是 | 腾讯K线 |
| high | NUMERIC(12,4) | 最高价 | 是 | 腾讯K线 |
| low | NUMERIC(12,4) | 最低价 | 是 | 腾讯K线 |
| close | NUMERIC(12,4) | 收盘价 | 否 | 腾讯K线 |
| volume | BIGINT | 成交量(手) | 是 | 腾讯K线 |
| amount | NUMERIC(16,2) | 成交额(元) | 是 | 腾讯K线估算(close*volume) |
| nav | NUMERIC(12,4) | 单位净值 | 是 | lsjz |
| nav_date | DATE | 净值日期 | 是 | lsjz |
| nav_type | VARCHAR(20) | confirmed/estimated | 否(默认confirmed) | calculator |
| nav_source | VARCHAR(20) | lsjz/estimated | 是 | pipeline |
| data_source | VARCHAR(20) | push2/akshare/tencent/manual | 是 | fetcher |
| float_share | NUMERIC(16,2) | 场内流通份额(万份) | 是 | 推算(f21/price/10000) |
| total_share | NUMERIC(16,2) | 总份额(万份) | 是 | push2 |
| premium_rate | NUMERIC(10,4) | 溢价率% | 是 | calculator: (close-nav)/nav*100 |
| turnover_rate | NUMERIC(10,4) | 换手率% | 是 | push2his/推算 |
| change_pct | NUMERIC(10,4) | 涨跌幅% | 是 | 腾讯K线计算 |
| fetch_batch_id | VARCHAR(36) | 采集批次UUID | 是 | pipeline |
| created_at | TIMESTAMPTZ | 创建时间 | 否(默认NOW) | 自动 |
| updated_at | TIMESTAMPTZ | 更新时间 | 否(默认NOW) | 自动 |

---

## fund_fee — 费率数据

每只基金一条记录，由 fetch_info (fundf10) 采集。
主键: code

| 字段 | 类型 | 说明 | 允许NULL | 来源 |
|------|------|------|----------|------|
| code | VARCHAR(6) | 基金代码 | 否 | - |
| purchase_fee_rate | NUMERIC(10,4) | 申购费率% | 是 | fundf10 <strike>标签 |
| redemption_fee_rate | NUMERIC(10,4) | 赎回费率% | 是 | fundf10 tbody第一行 |
| purchase_limit | NUMERIC(16,2) | 申购限额(元) | 是(NULL=无限额) | fundf10 日累计申购限额 |
| purchase_status | VARCHAR(20) | open/suspended/restricted | 是 | fundf10 申购状态 |
| redeem_status | VARCHAR(20) | open/suspended | 是 | fundf10 赎回状态 |
| fetched_at | TIMESTAMPTZ | 采集时间 | 否(默认NOW) | 自动 |

---

## fund_holdings — 十大持仓

每只基金一条记录，持仓列表存 JSONB。
主键: code

| 字段 | 类型 | 说明 | 允许NULL | 来源 |
|------|------|------|----------|------|
| code | VARCHAR(6) | 基金代码 | 否 | - |
| quarter | VARCHAR(10) | 报告期(2026Q1) | 是 | fundf10 持仓页标题 |
| report_date | DATE | 报告日期 | 是 | - |
| holdings | JSONB | 持仓列表 | 否(默认[]) | fundf10 持仓表 |
| updated_at | TIMESTAMPTZ | 更新时间 | 否(默认NOW) | 自动 |

holdings JSONB 格式:
```json
[
  {"rank": 1, "code": "600519", "name": "贵州茅台", "pct": 9.5, "shares": 10000},
  {"rank": 2, "code": "300750", "name": "宁德时代", "pct": 8.2, "shares": 5000}
]
```

---

## fund_code_list — LOF 代码列表

主键: code

| 字段 | 类型 | 说明 | 允许NULL | 来源 |
|------|------|------|----------|------|
| code | VARCHAR(6) | 基金代码 | 否 | push2 扫描 |
| name | VARCHAR(100) | 基金简称 | 是 | push2 |
| market | CHAR(2) | SH/SZ | 否 | 代码前缀 |
| last_seen | DATE | 最后出现日期 | 否 | 扫描日期 |
| updated_at | TIMESTAMPTZ | 更新时间 | 否(默认NOW) | 自动 |

---

## fund_category — 基金品类

每只基金可属于一个品类。由 fetch_info 自动写入。
主键: (code, category)

| 字段 | 类型 | 说明 | 允许NULL | 来源 |
|------|------|------|----------|------|
| code | VARCHAR(6) | 基金代码 | 否 | - |
| category | VARCHAR(20) | LOF/ETF/QDII/REITs | 否 | fund_info.fund_type |

---

## trade_calendar — 交易日历

主键: trade_date

| 字段 | 类型 | 说明 | 允许NULL | 来源 |
|------|------|------|----------|------|
| trade_date | DATE | 日期 | 否 | 预置数据 |
| is_trading | BOOLEAN | 是否交易日 | 否 | 预置数据 |

---

## fund_snapshot — 物化视图

由 daily_save 完成后刷新（CONCURRENTLY 不锁读）。
包含 fund_info + fund_daily 最新一条的 JOIN。

```sql
CREATE MATERIALIZED VIEW fund_snapshot AS
SELECT fi.code, fi.name, fi.fund_type, fi.market,
       fd.trade_date, fd.close, fd.nav, fd.premium_rate,
       fd.turnover_rate, fd.change_pct, fd.amount, fd.volume
FROM fund_info fi
LEFT JOIN LATERAL (
    SELECT * FROM fund_daily WHERE code = fi.code
    ORDER BY trade_date DESC LIMIT 1
) fd ON TRUE;
```

---

## 常见查询

```sql
-- 最新交易日全部基金（API 列表接口）
SELECT * FROM fund_snapshot ORDER BY amount DESC NULLS LAST;

-- 单只基金历史 60 天
SELECT trade_date, close, nav, premium_rate, amount
FROM fund_daily WHERE code = '161725'
ORDER BY trade_date DESC LIMIT 60;

-- 高溢价基金
SELECT code, name, premium_rate FROM fund_snapshot
WHERE premium_rate > 10 ORDER BY premium_rate DESC;

-- 检查数据完整性
SELECT fi.code, fi.fund_type, fi.aum,
       ff.purchase_fee_rate, fh.quarter
FROM fund_info fi
LEFT JOIN fund_fee ff ON fi.code = ff.code
LEFT JOIN fund_holdings fh ON fi.code = fh.code
WHERE fi.code IN ('160644','161725','161005');
```
