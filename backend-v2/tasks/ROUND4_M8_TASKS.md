# 第四轮任务 — M8 路由层

---

## 柯1 — Schemas + 核心路由

创建6个文件：

1. **schemas/request.py** — 9个Pydantic请求模型
   - FundListRequest(page/size/sort/order/filter_type/search/fund_type/premium_min/premium_max)
   - FundDetailRequest(code: str)
   - FundBatchRequest(codes: list[str]) — 最多50个
   - ChartRequest(days: int) — 7/30/90/180/365
   - DataQueryRequest(codes/start/end/fields) — 字段白名单校验
   - FormulaCreateRequest(name/expression/description)
   - FormulaUpdateRequest(name/expression/description/version)
   - WatchlistRequest(fund_code: str)
   - AlertCreateRequest(fund_code/condition/is_active)
   - 所有请求模型: 排序字段白名单 + 代码清洗(clean_code) + 日期校验

2. **schemas/response.py** — 13个Pydantic响应模型
   - HealthResponse / FundListResponse / FundDetailResponse
   - ChartResponse / HoldingsResponse / DataQueryResponse
   - FormulaResponse / FormulaListResponse / WatchlistResponse
   - AlertResponse / SystemMonitorResponse / ErrorResponse / SSEEvent

3. **routers/system.py** — 系统端点
   - GET /api/v1/health — 公开，返回DB/Redis/版本状态

4. **routers/funds.py** — 基金端点(6个)
   - GET /api/v1/funds — 列表(分页+排序+筛选)
   - GET /api/v1/funds/{code} — 详情
   - POST /api/v1/funds/batch — 批量查询
   - GET /api/v1/funds/{code}/chart — 图表数据
   - GET /api/v1/funds/{code}/holdings — 十大持仓
   - GET /api/v1/rankings — 排行榜

5. **routers/assets.py** — 资产端点(4个)
   - GET /api/v1/assets — 资产列表
   - GET /api/v1/assets/{code} — 资产详情
   - GET /api/v1/assets/{code}/funds — 关联基金
   - GET /api/v1/assets/{code}/chart — 资产图表

6. **routers/data.py** — 数据端点(3个)
   - GET /api/v1/data/daily — 日线查询(字段白名单)
   - GET /api/v1/data/export — 导出CSV
   - POST /api/v1/data/batch-query — 批量查询

参考: docs/plan/M8_路由层.md
【红线】仅操作 backend-v2/

---

## 柯3 — 公式/自选/预警/Admin/Stream路由 + app.py集成

创建7个文件：

1. **routers/formulas.py** — 公式端点(11个)
   - POST /api/v1/formulas — 创建公式
   - GET /api/v1/formulas — 列表
   - GET /api/v1/formulas/{id} — 详情
   - PUT /api/v1/formulas/{id} — 更新(乐观锁)
   - DELETE /api/v1/formulas/{id} — 删除
   - POST /api/v1/formulas/{id}/evaluate — 求值
   - POST /api/v1/formulas/batch-evaluate — 批量求值
   - POST /api/v1/formula-groups — 创建公式组
   - GET /api/v1/formula-groups — 列表
   - PUT /api/v1/formula-groups/{id} — 更新
   - DELETE /api/v1/formula-groups/{id} — 删除

2. **routers/watchlist.py** — 自选端点(3个)
   - POST /api/v1/watchlist — 添加自选
   - GET /api/v1/watchlist — 自选列表
   - DELETE /api/v1/watchlist/{code} — 删除自选

3. **routers/alerts.py** — 预警端点(3个)
   - POST /api/v1/alerts — 创建预警
   - GET /api/v1/alerts — 预警列表
   - DELETE /api/v1/alerts/{id} — 删除预警

4. **routers/admin.py** — 管理端点(15个)
   - GET /api/v1/admin/monitor — 监控数据
   - GET /api/v1/admin/diagnose/{component} — 诊断(redis/db/fetcher/queue)
   - POST /api/v1/admin/ops/refresh — 手动刷新
   - POST /api/v1/admin/ops/materialized-view/refresh — 刷新物化视图
   - POST /api/v1/admin/ops/cache/clear — 清缓存
   - GET /api/v1/admin/logs — 查看日志
   - GET /api/v1/admin/audit-log — 审计日志
   - 以上全部需要 require_admin 权限

5. **routers/stream.py** — SSE端点(1个)
   - GET /api/v1/stream — SSE实时推送(30秒心跳)

6. **routers/__init__.py** — 更新，统一导出所有router

7. **app.py** — 集成所有路由注册
   - 从 routers/ 导入所有 router
   - app.include_router(prefix="/api/v1")
   - 更新 lifespan 加入 scheduler + consumer_task
   - 注: 只修改路由注册和lifespan部分，不动中间件和异常处理器

参考: docs/plan/M8_路由层.md
【红线】仅操作 backend-v2/

---

## 柯2 — M8 测试 + M9 前端对接准备

创建以下文件：

1. **tests/test_routers.py** — 路由层集成测试(20项)
   - health端点: 200 + 返回字段
   - funds端点: 列表/详情/批量/图表/持仓/排行榜
   - formulas端点: CRUD + 乐观锁409 + 求值
   - watchlist端点: 添加/列表/删除
   - alerts端点: 创建/列表/删除
   - admin端点: 权限校验(无token→401, 普通用户→403)
   - data端点: 日线查询 + 字段白名单校验
   - 错误响应: 404/400/401/403/500格式一致

2. **tests/test_integration.py** — 集成测试(10项)
   - 完整数据流: fetch→process→save→query
   - 缓存击穿保护: 并发请求只1个查DB
   - Redis降级: Redis不可用→返回DB数据+realtime_available:false
   - 公式求值: 创建公式→求值→结果正确
   - 乐观锁: 并发更新version冲突→409

3. 更新 **.ai/api_contract.json** — 反映实际路由端点

参考: docs/plan/M8_路由层.md + docs/plan/M9_前端对接层.md
【红线】仅操作 backend-v2/