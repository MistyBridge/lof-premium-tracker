-- ============================================================
-- 金快查 后端 v2 数据库建表语句
-- 数据库: PostgreSQL 14+
-- ============================================================

-- 1. 基金基础信息（每日更新）
CREATE TABLE fund_info (
    code               VARCHAR(6) PRIMARY KEY,
    name               VARCHAR(100) NOT NULL,
    fund_type          VARCHAR(20),                -- LOF/ETF/QDII
    index_code         VARCHAR(20),                -- 跟踪指数
    market             CHAR(2) NOT NULL,           -- SH/SZ
    aum                NUMERIC(16,2),              -- 基金规模（亿元）
    listing_date       DATE,                       -- 上市日期
    redeem_days        INTEGER DEFAULT 2,          -- 赎回到账天数
    qdii_quota_status  VARCHAR(20) DEFAULT 'open', -- QDII额度(open/suspended/limited)
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

-- 2. 日线数据（24:00 永久写入，保留365天）
CREATE TABLE fund_daily (
    code               VARCHAR(6) NOT NULL,
    trade_date         DATE NOT NULL,
    open               NUMERIC(12,4),
    high               NUMERIC(12,4),
    low                NUMERIC(12,4),
    close              NUMERIC(12,4),
    volume             NUMERIC(16,2),              -- 成交量（手）
    amount             NUMERIC(16,2),              -- 成交额（元）
    nav                NUMERIC(12,4),              -- 单位净值
    nav_date           DATE,                       -- 净值日期
    float_share        NUMERIC(16,2),              -- 场内流通份额（万份）
    total_share        NUMERIC(16,2),              -- 基金总份额（万份）
    premium_rate       NUMERIC(10,4),              -- 溢价率(%), 计算得到
    turnover_rate      NUMERIC(10,4),              -- 换手率(%), 计算得到
    PRIMARY KEY (code, trade_date)
);
CREATE INDEX idx_daily_code_date ON fund_daily(code, trade_date DESC);

-- 3. 费率数据（随实时数据5分钟刷新）
CREATE TABLE fund_fee (
    code                VARCHAR(6) PRIMARY KEY,
    purchase_fee_rate   NUMERIC(10,4),
    redemption_fee_rate NUMERIC(10,4),
    purchase_limit      NUMERIC(16,2),
    purchase_status     VARCHAR(20),
    redeem_status       VARCHAR(20),
    fetched_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 4. 十大持仓（每日更新）
CREATE TABLE fund_holdings (
    code               VARCHAR(6) PRIMARY KEY,
    quarter            VARCHAR(10),                -- 2026Q1
    holdings           JSONB NOT NULL DEFAULT '[]',
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

-- 5. LOF代码列表（每日更新）
CREATE TABLE fund_code_list (
    code               VARCHAR(6) PRIMARY KEY,
    name               VARCHAR(100),
    market             CHAR(2) NOT NULL,
    last_seen          DATE NOT NULL,
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);
