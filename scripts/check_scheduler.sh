#!/bin/bash
echo "=== 启动日志 (调度器相关) ==="
journalctl -u jinkuaicha --since 'today' --no-pager 2>&1 | grep -iE 'scheduler|Scheduler|APScheduler|add_job|job.*added|Started' | head -20

echo ""
echo "=== app.py 调度器引用 ==="
grep -n 'scheduler\|create_scheduler' /opt/jinkuaicha/backend-v2/app.py | head -10

echo ""
echo "=== scheduler.py 关键段 ==="
grep -n 'est_nav\|CronTrigger\|def create_scheduler\|def job_' /opt/jinkuaicha/backend-v2/scheduler.py | head -30

echo ""
echo "=== 是否有 est_nav 相关进程/任务日志 (今天) ==="
journalctl -u jinkuaicha --since 'today' --no-pager 2>&1 | grep -iE 'est_nav|calc_all' | head -10
