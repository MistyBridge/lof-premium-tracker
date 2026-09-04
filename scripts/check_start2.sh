#!/bin/bash
echo "=== 09:51:00 - 09:52:00 完整日志 ==="
journalctl -u jinkuaicha --since '2026-08-03 09:51:00' --until '2026-08-03 09:52:00' --no-pager 2>&1 | grep '\[3462\]' | tail -30

echo ""
echo "=== 09:52 之后 apscheduler 活动 ==="
journalctl -u jinkuaicha --since '2026-08-03 09:52:00' --no-pager 2>&1 | grep '\[3462\]' | grep -iE 'apscheduler|Scheduler|job ' | head -15

echo ""
echo "=== create_scheduler 实现 (scheduler.py 45-70) ==="
sed -n '45,70p' /opt/jinkuaicha/backend-v2/scheduler.py
