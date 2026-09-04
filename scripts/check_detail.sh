#!/bin/bash
# 凭证从根 .env 读取
set -a; source "$(dirname "$0")/../.env"; set +a
PGPASSWORD=$DB_PASSWORD
echo "=== save_est_nav 07-29~31 detail ==="
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "SELECT job_name, status, started_at, duration_ms, LEFT(detail::text, 300) AS detail FROM job_log WHERE job_name = 'save_est_nav' AND started_at BETWEEN '2026-07-28' AND '2026-08-01' ORDER BY started_at;" 2>&1

echo ""
echo "=== fund_est_nav 07-29 是否存在 501025 ==="
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "SELECT * FROM fund_est_nav WHERE code='501025' ORDER BY trade_date DESC LIMIT 5;" 2>&1

echo ""
echo "=== job_log 07-28 与 07-29 行对比 ==="
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "SELECT trade_date, COUNT(*) FROM fund_est_nav GROUP BY trade_date ORDER BY trade_date DESC LIMIT 10;" 2>&1
