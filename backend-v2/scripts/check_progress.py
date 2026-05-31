"""
进度检查脚本 - 主管用
运行: py scripts/check_progress.py
"""
import os
import sys

# Windows GBK fix
sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KE1_FILES = [
    # M1 基础设施
    "config.py", "constants.py", "exceptions.py", "database.py",
    "models.py", "migration.py", "trade_calendar.py",
    "cache.py", "mq.py", "metrics.py", "app.py",
    "tests/test_m1_smoke.py",
    # M4 处理层
    "processors/normalize.py", "processors/validator.py",
    "processors/calculator.py", "processors/saver.py",
    "processors/pipeline.py", "tests/test_processors.py",
    # M6 服务层
    "services/fund_service.py", "services/asset_service.py",
    "services/data_service.py", "services/formula_service.py",
    "services/alert_service.py", "services/system_service.py",
    "services/sse_service.py", "hub/service.py",
    # M7 调度层
    "scheduler.py", "tests/test_scheduler.py",
]

KE2_FILES = [
    ".ai/file_index.md", ".ai/impact_matrix.json", ".ai/benchmarks.json",
    ".ai/module_health.json", ".ai/api_contract.json", ".ai/knowledge_base.md",
    ".ai/review_checklist.md", ".ai/conventions.md",
    ".ai/prompts/fix_bug.md", ".ai/prompts/add_feature.md", ".ai/prompts/ops_diagnose.md",
    ".ai/scripts/assess_change.sh",
    "ARCHITECTURE.md", "DATA_DICTIONARY.md", "verify.sh",
    "constants.py",
    "sql/seed/seed_trade_calendar.sql", "sql/seed/seed_fund_code_list.sql",
]

KE3_FILES = [
    # M2 认证层
    "auth/middleware.py", "auth/dependencies.py", "auth/__init__.py",
    "tests/test_auth.py",
    # M5 公式引擎
    "formula_engine/fields.py", "formula_engine/parser.py",
    "formula_engine/evaluator.py", "tests/test_formula_engine.py",
    # M3 采集层
    "fetchers/__init__.py", "fetchers/realtime.py",
    "fetchers/fundamental.py", "fetchers/historical.py",
    "fetchers/info.py", "tests/test_fetchers.py",
]

def check(name, files):
    done = 0
    total_lines = 0
    results = []
    for f in files:
        path = os.path.join(BASE, f)
        if os.path.exists(path):
            lines = sum(1 for _ in open(path, encoding="utf-8", errors="ignore"))
            content = open(path, encoding="utf-8", errors="ignore").read()
            is_skeleton = lines < 20 and "TODO" in content
            if is_skeleton:
                results.append(f"  [~] {f} ({lines} lines, skeleton)")
            else:
                done += 1
                total_lines += lines
                results.append(f"  [OK] {f} ({lines} lines)")
        else:
            results.append(f"  [--] {f}")
    pct = done / len(files) * 100 if files else 0
    bar = "#" * int(pct / 5) + "." * (20 - int(pct / 5))
    print(f"\n{'='*55}")
    print(f"  {name}: {done}/{len(files)}  [{bar}]  {pct:.0f}%  ({total_lines} lines)")
    print(f"{'='*55}")
    for r in results:
        print(r)

if __name__ == "__main__":
    print("[CHECK] jinkuaicha v2 progress")
    check("Ke1 - M1 Infrastructure", KE1_FILES)
    check("Ke2 - AI Governance", KE2_FILES)
    check("Ke3 - Auth + Formula Engine", KE3_FILES)
    print(f"\n[DONE]")
