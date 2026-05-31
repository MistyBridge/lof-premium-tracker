#!/bin/bash
# verify.sh - 金快查v2标准验证脚本
# 用法: bash verify.sh [--benchmark]
# 从 backend-v2/ 目录运行

set -euo pipefail

PASS=0
FAIL=0
WARN=0

pass()  { echo "  + $1"; PASS=$((PASS+1)); }
fail()  { echo "  X $1"; FAIL=$((FAIL+1)); }
warn()  { echo "  ! $1"; WARN=$((WARN+1)); }

echo "========================================"
echo " 金快查 v2 验证"
echo " $(date)"
echo "========================================"

# 1. 测试
echo ""
echo "=== 1. 测试 ==="
if command -v pytest &>/dev/null; then
    if pytest tests/ --tb=short -q 2>/dev/null; then
        pass "pytest 通过"
    else
        fail "pytest 失败"
    fi
else
    warn "pytest 未安装，跳过"
fi

# 2. 类型检查
echo ""
echo "=== 2. 类型检查 ==="
if command -v pyright &>/dev/null; then
    if pyright --outputjson > /dev/null 2>&1; then
        pass "pyright 通过"
    else
        warn "pyright 有警告"
    fi
else
    warn "pyright 未安装，跳过"
fi

# 3. 覆盖率
echo ""
echo "=== 3. 覆盖率 ==="
if command -v pytest &>/dev/null; then
    if pytest tests/ --cov=. --cov-report=term-missing --cov-fail-under=60 -q 2>/dev/null; then
        pass "覆盖率 >= 60%"
    else
        warn "覆盖率 < 60% 或 pytest-cov 未安装"
    fi
else
    warn "pytest 未安装，跳过"
fi

# 4. 数据库迁移
echo ""
echo "=== 4. 数据库迁移 ==="
if [ -f migration.py ]; then
    if py migration.py check 2>/dev/null; then
        pass "迁移检查通过"
    else
        warn "需要执行迁移"
    fi
else
    warn "migration.py 不存在"
fi

# 5. 文件完整性
echo ""
echo "=== 5. 文件完整性 ==="
REQUIRED=(
    app.py config.py database.py models.py constants.py exceptions.py
    fetchers/__init__.py processors/__init__.py routers/__init__.py
    services/__init__.py hub/__init__.py auth/__init__.py
    formula_engine/__init__.py schemas/__init__.py tests/__init__.py
)
for f in "${REQUIRED[@]}"; do
    [ -f "$f" ] && pass "$f" || fail "$f 缺失"
done

# 6. .ai 文件完整性
echo ""
echo "=== 6. .ai 文件完整性 ==="
AI_FILES=(
    .ai/context.md .ai/file_index.md .ai/impact_matrix.json
    .ai/benchmarks.json .ai/module_health.json .ai/api_contract.json
    .ai/knowledge_base.md .ai/review_checklist.md .ai/conventions.md
    .ai/prompts/fix_bug.md .ai/prompts/add_feature.md .ai/prompts/ops_diagnose.md
    .ai/scripts/assess_change.sh
)
for f in "${AI_FILES[@]}"; do
    [ -f "$f" ] && pass "$f" || fail "$f 缺失"
done

# 7. 健康检查
echo ""
echo "=== 7. 健康检查 ==="
if curl -sf http://127.0.0.1:8000/api/v1/health > /dev/null 2>&1; then
    pass "服务健康"
else
    warn "服务未运行（本地开发时正常）"
fi

# 汇总
echo ""
echo "========================================"
echo " 结果: + ${PASS} 通过  X ${FAIL} 失败  ! ${WARN} 警告"
echo "========================================"

[ "$FAIL" -gt 0 ] && exit 1 || exit 0
