"""检查估算净值全链路: Redis缓存 → 列表API → 详情API 的 est_nav 字段"""
import json
import urllib.request

BASE = "http://127.0.0.1:8000"

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read())

# 1. 列表 API
d = get("/api/v1/funds?page=1&size=5")
data = d.get("data", [])
print("=== 列表 API (5只) ===")
for row in data:
    print(f"  {row.get('code')} {row.get('name','')[:20]} est_nav={row.get('est_nav')} est_change_pct={row.get('est_change_pct')} nav={row.get('nav')}")

# 2. 详情 API
print("\n=== 详情 API 501025 ===")
try:
    detail = get("/api/v1/funds/501025")
    dd = detail.get("data", {})
    print(f"  est_nav={dd.get('est_nav')} est_change_pct={dd.get('est_change_pct')} nav={dd.get('nav')}")
except Exception as e:
    print(f"  详情API失败: {e}")

# 3. est_nav 单独接口
print("\n=== est_nav API 501025 ===")
try:
    en = get("/api/v1/funds/501025/est_nav")
    ed = en.get("data", {})
    print(f"  est_nav={ed.get('est_nav')} est_change_pct={ed.get('est_change_pct')}")
except Exception as e:
    print(f"  est_nav API失败: {e}")

# 4. 统计列表里 est_nav 为空的
print("\n=== 列表 est_nav 覆盖率 ===")
d2 = get("/api/v1/funds?page=1&size=100")
rows = d2.get("data", [])
with_est = [r for r in rows if r.get("est_nav") is not None]
print(f"  {len(with_est)}/{len(rows)} 有估算净值 ({len(with_est)/max(len(rows),1)*100:.1f}%)")
