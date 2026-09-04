#!/bin/bash
echo "=== 07-29 16:00 前后 EST_NAV 日志 ==="
journalctl -u jinkuaicha --since '2026-07-29 15:50:00' --until '2026-07-29 16:15:00' --no-pager 2>&1 | grep -iE 'EST_NAV|save_est|batch .* fail|无数据' | head -20

echo ""
echo "=== 07-30 16:00 前后 ==="
journalctl -u jinkuaicha --since '2026-07-30 15:50:00' --until '2026-07-30 16:15:00' --no-pager 2>&1 | grep -iE 'EST_NAV|save_est|batch .* fail|无数据' | head -20

echo ""
echo "=== 07-29 ~ 08-02 服务重启记录 ==="
journalctl -u jinkuaicha --since '2026-07-28' --until '2026-08-03 09:00' --no-pager 2>&1 | grep -iE 'Started|Stopping|Stopped|Main process exited|Failed to start' | head -20
