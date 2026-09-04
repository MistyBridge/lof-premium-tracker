#!/bin/bash
DBH="101.200.129.61"
DBU="deploy"
DBN="jinkuaicha"
export PGPASSWORD="jk_deploy_2026"

echo "=== fund_holdings for 162216 ==="
psql -h "$DBH" -U "$DBU" -d "$DBN" -c "SELECT code, quarter, report_date, holdings FROM fund_holdings WHERE code='162216';"

echo ""
echo "=== fund_asset_map for 162216 ==="
psql -h "$DBH" -U "$DBU" -d "$DBN" -c "SELECT fund_code, asset_code, report_date, weight FROM fund_asset_map WHERE fund_code='162216' ORDER BY report_date DESC, weight DESC LIMIT 20;"

echo ""
echo "=== 688525 in fund_asset_map ==="
psql -h "$DBH" -U "$DBU" -d "$DBN" -c "SELECT fund_code, asset_code, report_date, weight FROM fund_asset_map WHERE asset_code='688525' ORDER BY report_date DESC LIMIT 20;"

echo ""
echo "=== holdings JSON detail ==="
psql -h "$DBH" -U "$DBU" -d "$DBN" -c "SELECT jsonb_array_elements(holdings) FROM fund_holdings WHERE code='162216';"

echo ""
echo "=== asset_master for 688525 ==="
psql -h "$DBH" -U "$DBU" -d "$DBN" -c "SELECT * FROM asset_master WHERE code='688525';"
