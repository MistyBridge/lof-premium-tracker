#!/bin/bash
echo "=== job_log: save_est_nav 最近记录 ==="
PGPASSWORD=jk_deploy_2026 psql -h 101.200.129.61 -U deploy -d jinkuaicha -c "SELECT job_name, status, started_at, finished_at, duration_ms FROM job_log WHERE job_name LIKE '%est%' ORDER BY started_at DESC LIMIT 15;" 2>&1

echo ""
echo "=== job_log: 最近所有任务 (今天) ==="
PGPASSWORD=jk_deploy_2026 psql -h 101.200.129.61 -U deploy -d jinkuaicha -c "SELECT job_name, status, started_at, duration_ms FROM job_log WHERE started_at > NOW() - INTERVAL '1 day' ORDER BY started_at DESC LIMIT 25;" 2>&1

echo ""
echo "=== 07-28 ~ 08-02 所有 save_est_nav 记录 ==="
PGPASSWORD=jk_deploy_2026 psql -h 101.200.129.61 -U deploy -d jinkuaicha -c "SELECT job_name, status, started_at, duration_ms FROM job_log WHERE job_name = 'save_est_nav' AND started_at BETWEEN '2026-07-26' AND '2026-08-03' ORDER BY started_at;" 2>&1
