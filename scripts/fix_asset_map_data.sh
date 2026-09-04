#!/bin/bash
# 数据修复 - 清理 fund_asset_map 中的异常权重
export PGPASSWORD=jk_deploy_2026

echo "=== 修复前: 异常数据统计 ==="
psql -h 101.200.129.61 -U deploy -d jinkuaicha -c "SELECT COUNT(*) AS bad_count FROM fund_asset_map WHERE weight > 100 OR weight IS NULL OR weight < 0;"

echo ""
echo "=== 删除 weight > 100 的异常数据 ==="
psql -h 101.200.129.61 -U deploy -d jinkuaicha -c "DELETE FROM fund_asset_map WHERE weight > 100;"

echo ""
echo "=== 删除 weight IS NULL 的数据 ==="
psql -h 101.200.129.61 -U deploy -d jinkuaicha -c "DELETE FROM fund_asset_map WHERE weight IS NULL;"

echo ""
echo "=== 更新 report_date 为合理默认值（2026Q2）==="
psql -h 101.200.129.61 -U deploy -d jinkuaicha -c "UPDATE fund_asset_map SET report_date = '2026-06-30' WHERE report_date IN ('2025-12-31', '2000-01-01');"

echo ""
echo "=== 修复后: 统计 ==="
psql -h 101.200.129.61 -U deploy -d jinkuaicha -c "SELECT report_date, COUNT(*) FROM fund_asset_map GROUP BY report_date ORDER BY report_date DESC LIMIT 5;"

echo ""
echo "=== 688525 修复后 ==="
psql -h 101.200.129.61 -U deploy -d jinkuaicha -c "SELECT fund_code, asset_code, weight FROM fund_asset_map WHERE asset_code='688525' ORDER BY weight DESC LIMIT 10;"
