# 系统架构

## 技术栈
- 后端: FastAPI 0.115 + Uvicorn (async)
- ORM: SQLAlchemy 2.0 async + asyncpg
- 数据库: PostgreSQL 14（shared_buffers=192MB, statement_timeout=5s）
- 缓存 + 队列: Redis 7（maxmemory=128MB, allkeys-lru）
- 定时任务: APScheduler 3.10（进程内，和 FastAPI 共享事件循环）
- HTTP 客户端: httpx（async，连接池）
- 公式解析: Python ast 模块（白名单 AST，不用 eval）
- 反代: Nginx（gzip + SSL + 限流 + 静态文件）
- 前端: Cloudflare Pages（jinkuaicha.com，静态托管，不在 v2 重写范围内）
- 用户系统: Supabase Auth（JWT 验证）
- 部署: 阿里云 ECS 2C2G（华北2北京），systemd 管理进程

## 分层架构

```
用户浏览器
  ↓
Cloudflare Pages（静态前端 CDN）
  ↓
CF Functions（/api/* 反向代理）
  ↓
Nginx（阿里云 ECS，gzip + SSL + 限流）
  ↓
FastAPI（Uvicorn，async）
  ├→ 认证中间件（JWT 验证 + 身份注入）
  ├→ 路由层（routers/）
  ├→ Hub 编排器（hub/service.py）
  │    ├→ Service 层（services/）
  │    │    ├→ 数据库（PostgreSQL via SQLAlchemy async）
  │    │    └→ 缓存（Redis via cache.py）
  │    └→ 公式引擎（formula_engine/）
  └→ 全局异常处理器
```

## 数据流

### 交易时段（9:30-15:00，每 5 分钟）
```
APScheduler → fetchers/realtime.py
  → push2.eastmoney.com（主）
  → qt.gtimg.cn（备）
  ↓
Redis Stream (stream:events, type=realtime)
  ↓
processors/pipeline.py 消费
  → normalize → validator → 写 Redis rt:all (TTL 60s)
  → 写 Redis rt:close:{date}
```

### 盘中估值（交易时段，和实时行情同步）
```
fetchers/fundamental.py
  → fundgz.1234567.com.cn（估算净值）
  ↓
Redis Stream (type=nav)
  ↓
pipeline 消费 → 写 Redis nav:all (TTL 300s)
```

### 日终（20:00-23:30）
```
20:00  scheduler → fetchers/fundamental.py → lsjz 净值
20:30  scheduler → fetchers/historical.py → push2his 日线K线
23:00  scheduler → fetchers/fundamental.py → QDII 补充净值
23:30  scheduler → daily_save 任务
       → 合并 rt:close + nav + kline
       → calculator 计算派生字段（溢价率/换手率/涨跌幅/三日均溢）
       → saver 写 DB fund_daily（分批 100 条/事务）
       → 刷新物化视图 fund_snapshot
```

### 每周（工作日）
```
周一  scheduler → push2delay 全量扫描 → 更新 fund_code_list
工作日 scheduler → fetchers/info.py → fundf10 分批爬取
       → 更新 fund_info + fund_fee + fund_holdings
```

### API 请求流
```
GET /api/v1/funds
  ↓
auth/middleware.py（可选认证）
  ↓
routers/funds.py（参数校验 + Pydantic）
  ↓
hub/service.py（编排）
  ↓
services/fund_service.py
  ├→ cache_get("rt:all") → Redis 实时数据
  ├→ DB 查询 fund_snapshot 物化视图
  ├→ 合并实时 + 历史数据
  ├→ cache_set() 写缓存（带击穿保护）
  └→ 返回响应
```

## 模块依赖关系

```
config.py ←── database.py ←── models.py ←── 所有 service
    ↑
cache.py ←── mq.py ←── 所有 fetcher ←── scheduler.py
    ↑
formula_engine/ ←── formula_service.py ←── hub/service.py
    ↑
auth/middleware.py ←── auth/dependencies.py ←── 所有 router
    ↑
processors/normalize.py
processors/validator.py
processors/calculator.py ←── formula_engine/fields.py
processors/saver.py
processors/pipeline.py ←── mq.py + cache.py + 以上所有 processor
```

## Redis Key 命名规范

| Key | 格式 | TTL | 写入方 | 用途 |
|-----|------|-----|--------|------|
| rt:all | 全量实时行情 JSON | 60s | 消费者 | 基金列表实时数据 |
| rt:close:{date} | 当日收盘快照 | 次日凌晨 | 消费者 | daily_save 读收盘价 |
| nav:all | 全量净值 JSON | 300s | 消费者 | 净值缓存 |
| kline:fund:{date} | 基金日线 | 次日凌晨 | 消费者 | daily_save 读日线 |
| kline:asset:{date} | 资产日线 | 次日凌晨 | 消费者 | daily_save 读资产日线 |
| fee:{code} | 单基金费率 | 3600s | 消费者 | 详情页费率 |
| info:{code} | 单基金基础信息 | 86400s | 消费者 | 详情页基础信息 |
| lock:cache:{key} | 缓存击穿锁 | 3s | fund_service | SET NX 锁 |
| stream:events | Redis Stream | 无 | fetcher | 事件队列 |

日期格式: `{date}` = YYYYMMDD（如 20260530）

## 数据库物化视图

```sql
CREATE MATERIALIZED VIEW fund_snapshot AS
SELECT
    fd.code, fi.name, fi.fund_type, fi.market,
    fd.trade_date, fd.close, fd.nav, fd.premium_rate,
    fd.turnover_rate, fd.change_pct, fd.amount, fd.float_share,
    ff.purchase_fee_rate, ff.redemption_fee_rate, ff.purchase_status, ff.redeem_status,
    fd.nav_type, fd.nav_date
FROM fund_daily fd
JOIN fund_info fi ON fd.code = fi.code
LEFT JOIN fund_fee ff ON fd.code = ff.code
WHERE fd.trade_date = (SELECT MAX(trade_date) FROM fund_daily)
WITH DATA;

CREATE UNIQUE INDEX idx_snapshot_code ON fund_snapshot(code);
```

物化视图在 daily_save 完成后 REFRESH CONCURRENTLY。

## 设计决策（ADR）

### ADR-1: SQLAlchemy async 而不是 asyncpg 直连
- ORM 查询可读性好，适合 API 层
- 批量写入用原生 SQL（executemany），性能不受影响
- 2C2G 不需要 ORM 的额外开销担忧（查询量小）

### ADR-2: Redis Streams 而不是 asyncio.Queue
- 进程崩溃后 Stream 数据不丢失
- 单进程下 asyncio.Queue 也够用，但 Stream 更利于后续扩展
- 技术锻炼目的

### ADR-3: 公式结果不存后端
- 后端零计算开销
- 用户隐私（公式策略不经过服务器）
- 离线可用（前端缓存后可断网计算）

### ADR-4: 物化视图而不是实时 JOIN
- 基金列表是最高频 API，物化视图避免每次 JOIN 5 张表
- daily_save 完成后 REFRESH CONCURRENTLY（不阻塞读）
- 1500 行的物化视图查询 < 5ms

### ADR-5: Supabase Auth 保留
- 已有用户数据在 Supabase，迁移成本高
- JWT 验证在后端独立完成，不依赖 Supabase 服务可用性
- 后续如需迁移，只需更换 JWT Secret 和用户表

## 已知限制
- 单机架构，无水平扩展能力
- 2C2G 内存有限，Redis maxmemory=128MB
- push2 字段码是硬编码，可能随 API 变化
- fundf10 爬取依赖 HTML 结构，改版时需更新解析
- QDII 净值延迟 T+1~T+2，盘中用估算值
