-- 002: 给 fund_daily 添加 suspension_status 字段
-- 执行: py migration.py apply 002

ALTER TABLE fund_daily 
ADD COLUMN IF NOT EXISTS suspension_status VARCHAR(20) DEFAULT 'unknown';

-- 给现有数据填充停牌状态
UPDATE fund_daily 
SET suspension_status = CASE
    WHEN close IS NULL THEN 'unknown'
    WHEN volume IS NOT NULL AND volume > 0 THEN 'trading'
    WHEN volume = 0 AND close IS NOT NULL THEN 'suspended'
    ELSE 'unknown'
END
WHERE suspension_status = 'unknown';

-- 索引（便于按停牌状态查询）
CREATE INDEX IF NOT EXISTS idx_daily_suspension 
ON fund_daily (suspension_status, trade_date) 
WHERE suspension_status = 'suspended';
