#!/bin/bash
echo "=== journal 07-29 16:00 前后原始日志 (前20行) ==="
journalctl -u jinkuaicha --since '2026-07-29 15:59:30' --until '2026-07-29 16:02:00' --no-pager 2>&1 | head -20

echo ""
echo "=== journal 最早可用日志 ==="
journalctl -u jinkuaicha --no-pager 2>&1 | head -5

echo ""
echo "=== 07-28 16:00 前后 EST_NAV ==="
journalctl -u jinkuaicha --since '2026-07-28 15:50:00' --until '2026-07-28 16:20:00' --no-pager 2>&1 | grep -iE 'EST_NAV|save_est|batch .* fail' | head -10
