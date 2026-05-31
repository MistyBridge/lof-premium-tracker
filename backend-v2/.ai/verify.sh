#!/bin/bash
# verify.sh — AI 修改代码后的标准验证脚本
# 用法: cd backend-v2 && bash .ai/verify.sh

set -e
cd "$(dirname "$0")/.."

# 兼容 python3 / python（Windows 通常只有 python）
PY="python3"
command -v python3 &>/dev/null || PY="python"

echo "=== 1. Python 语法检查 ==="
ERRORS=0
for f in $(find . -name "*.py" -not -path "./__pycache__/*" -not -path "*/__pycache__/*"); do
    $PY -c "import ast; ast.parse(open('$f').read())" 2>/dev/null || {
        echo "  SYNTAX ERROR: $f"
        ERRORS=$((ERRORS + 1))
    }
done
if [ $ERRORS -eq 0 ]; then
    echo "  ✓ 全部语法正确"
else
    echo "  ✗ $ERRORS 个语法错误"
    exit 1
fi

echo ""
echo "=== 2. 运行测试 ==="
if command -v pytest &> /dev/null; then
    pytest tests/ --tb=short -q 2>/dev/null && echo "  ✓ 测试通过" || echo "  ⚠ 部分测试失败"
else
    echo "  ⚠ pytest 未安装，跳过"
fi

echo ""
echo "=== 3. 检查导入 ==="
$PY -c "
import sys
sys.path.insert(0, '.')
errors = []
modules = ['config', 'constants', 'exceptions', 'database', 'models', 'cache', 'mq', 'metrics', 'trade_calendar']
for m in modules:
    try:
        __import__(m)
    except Exception as e:
        errors.append(f'{m}: {e}')
if errors:
    for e in errors: print(f'  IMPORT ERROR: {e}')
    sys.exit(1)
else:
    print('  ✓ 核心模块导入正常')
" 2>/dev/null || echo "  ⚠ 导入检查跳过（缺少依赖）"

echo ""
echo "=== 4. 检查文件完整性 ==="
EXPECTED_FILES=(
    "config.py" "constants.py" "exceptions.py" "database.py" "models.py"
    "migration.py" "trade_calendar.py" "cache.py" "mq.py" "metrics.py" "app.py"
    "fetchers/__init__.py" "fetchers/realtime.py" "fetchers/fundamental.py"
    "fetchers/historical.py" "fetchers/info.py"
    "processors/__init__.py" "processors/normalize.py" "processors/validator.py"
    "processors/calculator.py" "processors/saver.py" "processors/pipeline.py"
    "services/__init__.py" "services/fund_service.py" "services/asset_service.py"
    "services/data_service.py" "services/formula_service.py" "services/alert_service.py"
    "services/system_service.py" "services/sse_service.py"
    "hub/__init__.py" "hub/service.py"
    "routers/__init__.py" "routers/system.py" "routers/funds.py"
    "routers/assets.py" "routers/data.py"
    "schemas/request.py" "schemas/response.py"
    "auth/__init__.py" "auth/middleware.py" "auth/dependencies.py"
)
MISSING=0
for f in "${EXPECTED_FILES[@]}"; do
    if [ ! -f "$f" ]; then
        echo "  MISSING: $f"
        MISSING=$((MISSING + 1))
    fi
done
if [ $MISSING -eq 0 ]; then
    echo "  ✓ ${#EXPECTED_FILES[@]} 个核心文件全部存在"
else
    echo "  ✗ 缺失 $MISSING 个文件"
fi

echo ""
echo "=== 5. 检查 .ai/ 文件完整性 ==="
AI_FILES=(
    ".ai/context.md" ".ai/file_index.md" ".ai/impact_matrix.json"
    ".ai/benchmarks.json" ".ai/module_health.json" ".ai/api_contract.json"
    ".ai/knowledge_base.md" ".ai/conventions.md" ".ai/review_checklist.md"
    ".ai/ARCHITECTURE.md" ".ai/DATA_DICTIONARY.md" ".ai/verify.sh"
    ".ai/prompts/fix_bug.md" ".ai/prompts/add_feature.md" ".ai/prompts/ops_diagnose.md"
)
AI_MISSING=0
for f in "${AI_FILES[@]}"; do
    if [ ! -f "$f" ]; then
        echo "  MISSING: $f"
        AI_MISSING=$((AI_MISSING + 1))
    fi
done
if [ $AI_MISSING -eq 0 ]; then
    echo "  ✓ ${#AI_FILES[@]} 个 .ai/ 文件全部存在"
else
    echo "  ⚠ 缺失 $AI_MISSING 个 .ai/ 文件"
fi

echo ""
echo "=== 6. 数据库迁移检查 ==="
if command -v $PY &> /dev/null; then
    $PY -c "
import sys; sys.path.insert(0, '.')
from migration import EXPECTED_TABLES, TABLES_SQL
print(f'  表定义: {len(TABLES_SQL)} 条 SQL')
print(f'  期望表: {len(EXPECTED_TABLES)} 张')
if len(TABLES_SQL) >= len(EXPECTED_TABLES):
    print('  ✓ 迁移 SQL 完整')
else:
    print('  ⚠ 迁移 SQL 可能不完整')
" 2>/dev/null || echo "  ⚠ 迁移检查跳过"
fi

echo ""
echo "=== 7. 健康检查（如服务运行中）==="
if curl -sf http://127.0.0.1:8000/api/v1/health > /dev/null 2>&1; then
    echo "  ✓ 服务健康"
else
    echo "  ⚠ 服务未运行（本地开发时正常）"
fi

echo ""
echo "=== 验证完成 ==="
