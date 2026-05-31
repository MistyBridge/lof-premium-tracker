#!/bin/bash
# assess_change.sh — AI 修改代码前，自动评估影响范围
# 用法: bash .ai/scripts/assess_change.sh fund_service.py calculator.py
# 依赖: .ai/impact_matrix.json

set -e
cd "$(dirname "$0")/../.."

PY="python3"
command -v python3 &>/dev/null || PY="python"

MATRIX=".ai/impact_matrix.json"

if [ ! -f "$MATRIX" ]; then
    echo "ERROR: $MATRIX 不存在"
    exit 1
fi

if [ $# -eq 0 ]; then
    echo "用法: bash .ai/scripts/assess_change.sh <file1> [file2] ..."
    echo "示例: bash .ai/scripts/assess_change.sh fetchers/info.py processors/calculator.py"
    exit 1
fi

echo "=== 变更影响评估 ==="
echo "修改文件: $@"
echo ""

for file in "$@"; do
    echo "--- $file ---"

    # 从 impact_matrix.json 提取信息
    $PY -c "
import json, sys
with open('$MATRIX') as f:
    matrix = json.load(f)
if '$file' in matrix:
    info = matrix['$file']
    print(f\"  风险等级: {info.get('risk', 'unknown')}\")
    print(f\"  依赖模块: {', '.join(info.get('depends_on', []))}\")
    print(f\"  被依赖方: {', '.join(info.get('depended_by', []))}\")
    notes = info.get('notes', '')
    if notes:
        print(f\"  注意事项: {notes}\")
    tests = info.get('tests', [])
    if tests:
        print(f\"  需要运行测试:\")
        for t in tests:
            print(f\"    pytest tests/{t} -v\")
    docs = info.get('affected_docs', [])
    if docs:
        print(f\"  需要更新文档:\")
        for d in docs:
            print(f\"    {d}\")
else:
    print('  未在 impact_matrix.json 中找到此文件')
    print('  建议: 新增文件后更新 .ai/impact_matrix.json')
" 2>/dev/null || echo "  ⚠ Python 不可用，跳过矩阵查询"

    # 检查文件行数
    if [ -f "$file" ]; then
        LINES=$(wc -l < "$file")
        if [ $LINES -gt 300 ]; then
            echo "  ⚠ 文件超过 300 行 ($LINES 行)，建议拆分"
        fi
    else
        echo "  ⚠ 文件不存在（可能是新增文件）"
    fi

    echo ""
done

echo "=== 评估完成 ==="
