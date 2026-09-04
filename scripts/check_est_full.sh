#!/bin/bash
# 检查估算净值快照 + 调度器状态
echo "=== fund_est_nav 表 ==="
PGPASSWORD=jk_deploy_2026 psql -h 101.200.129.61 -U deploy -d jinkuaicha -c "SELECT COUNT(*) AS cnt, MIN(trade_date) AS min_date, MAX(trade_date) AS max_date FROM fund_est_nav;" 2>&1

echo ""
echo "=== 最近5天快照行数 ==="
PGPASSWORD=jk_deploy_2026 psql -h 101.200.129.61 -U deploy -d jinkuaicha -c "SELECT trade_date, COUNT(*) FROM fund_est_nav GROUP BY trade_date ORDER BY trade_date DESC LIMIT 7;" 2>&1

echo ""
echo "=== 调度器日志 (1小时) ==="
journalctl -u jinkuaicha --since '1 hour ago' --no-pager 2>&1 | grep -iE 'est_nav|scheduler|APScheduler|snapshot' | tail -25

echo ""
echo "=== 最近错误 ==="
journalctl -u jinkuaicha --since '6 hours ago' --no-pager 2>&1 | grep -iE 'ERROR|Traceback|Exception' | tail -15
