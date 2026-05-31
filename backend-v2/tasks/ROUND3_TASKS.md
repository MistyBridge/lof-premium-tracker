# 第三轮任务分配

---

## 柯1 — M6 业务服务层

创建以下8个文件：

1. **services/fund_service.py** — 基金查询服务
   - get_fund_list(page, size, sort, order, filter_type, search, db) → dict
   - get_fund_detail(code, db) → dict
   - get_fund_batch(codes, db) → list
   - merge_realtime(db_data, redis_data) → list（合并DB历史+Redis实时）
   - 缓存击穿保护: Redis SET NX 锁
   - 降级: Redis不可用→只返回DB数据, realtime_available=False

2. **services/asset_service.py** — 资产查询服务
   - get_asset_list(db) → list
   - get_asset_detail(code, db) → dict
   - get_asset_daily(code, start, end, db) → list

3. **services/data_service.py** — 日线数据查询
   - get_daily_data(codes, start, end, fields, db) → list
   - 字段白名单校验
   - 日期范围校验（最大365天）

4. **services/formula_service.py** — 公式CRUD
   - create_formula(user_id, name, expression, db) → dict
   - update_formula(user_id, formula_id, data, db) → dict（乐观锁version）
   - delete_formula(user_id, formula_id, db)
   - list_formulas(user_id, db) → list
   - 并发限制: 每用户最多10个公式

5. **services/alert_service.py** — 预警CRUD（P1）
   - create_alert(user_id, condition, db) → dict
   - update_alert / delete_alert / list_alerts
   - check_alerts(fund_data) → list[triggered]

6. **services/system_service.py** — 系统管理
   - get_health(db, redis) → dict
   - get_monitor() → dict（metrics数据）
   - get_diagnose(component) → dict（redis/db/fetcher/queue诊断）
   - refresh_cache(type) → dict
   - 物化视图并发锁: 第2个请求返回"进行中"

7. **services/sse_service.py** — SSE实时推送（P2）
   - subscribe(user_id) → AsyncGenerator
   - publish_update(data) → None
   - 心跳: 30秒间隔
   - 连接清理: 超时断开

8. **hub/service.py** — 中台编排器
   - ServiceHub类: 编排各Service + 缓存失效协调
   - get_fund_list_hub() → 调fund_service + 公式计算 + 排行
   - get_fund_detail_hub(code) → 调fund_service + asset_service + data_service

参考: docs/plan/M6_业务服务层.md
【红线】仅操作 backend-v2/

---

## 柯3 — M7 调度层

创建以下2个文件：

1. **scheduler.py** — APScheduler 定时任务
   - 9个定时任务:
     - scan_codes: 周一08:30
     - fetch_info: 周一~五09:00
     - fetch_realtime: 交易时段每5分钟
     - fetch_nav: 20:00
     - fetch_kline: 20:30
     - fetch_nav_qdii: 23:00
     - daily_save: 23:30
     - check_partitions: 每月1日
     - check_calendar: 每年12月1日
   - job_defaults: max_instances=1, coalesce=True, misfire_grace_time=300
   - 重启补执行: check_and_catchup()
   - 交易日检查: 非交易日跳过采集任务
   - QDII延迟处理: 23:30检查→有净值入库→无净值延迟重试3次
   - fetch_info分批: 先重试失败codes，再取新批次

2. **tests/test_scheduler.py** — 调度层测试
   - test_job_count: 9个job注册
   - test_trading_day_skip: 非交易日跳过
   - test_catchup_logic: 重启补执行
   - test_qdii_delay: QDII延迟重试

参考: docs/plan/M7_调度层.md
【红线】仅操作 backend-v2/