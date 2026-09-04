#!/bin/bash
echo "=== 09:50 之后完整启动日志 ==="
journalctl -u jinkuaicha --since '2026-08-03 09:50:00' --no-pager 2>&1 | head -40

echo ""
echo "=== 当前时间 ==="
date '+%Y-%m-%d %H:%M:%S %A'

echo ""
echo "=== 今天 09:51 后 est_nav 任务运行? ==="
journalctl -u jinkuaicha --since '2026-08-03 09:51:00' --no-pager 2>&1 | grep -iE 'est_nav|apscheduler' | head -10
echo "(以上为空则调度器未运行)"

echo ""
echo "=== job_est_nav 函数体 (scheduler.py 477-500) ==="
sed -n '477,500p' /opt/jinkuaicha/backend-v2/scheduler.py
