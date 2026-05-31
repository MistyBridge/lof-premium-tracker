# 系统架构

## 技术栈

| 组件 | 选型 | 版本 | 说明 |
|------|------|------|------|
| Web 框架 | FastAPI + Uvicorn | 0.115 / 0.30 | async 原生，自动 OpenAPI |
| ORM | SQLAlchemy 2.0 async | 2.0.35 | 模型定义 + 查询可读性 |
| 数据库驱动 | asyncpg | 0.30 | 最快的 async PG 驱动 |
| 数据库 | PostgreSQL 14 | 14.23 | JSONB + 分区表 |
| 缓存 + 队列 | Redis 7 | 6.0.16 | TTL 缓存 + Streams 消息队列 |
| 定时任务 | APScheduler | 3.10.4 | 进程内调度 |
| HTTP 客户端 | httpx | 0.27 | async 原生，HTTP/2 |
| 公式解析 | Python ast | 内置 | 零依赖，安全白名单 |
| 认证 | Supabase Auth (JWT) | - | 前端登录，后端验签 |
| 前端 | Cloudflare Pages | - | 静态托管 |
| 部署 | 阿里云 2C2G | Ubuntu 22.04 | Nginx + systemd |

## 分层架构

```
[Cloudflare Pages 前端]
        ↓
[Cloudflare DNS] → [Nginx 反代 :80]
        ↓
[RequestId 中间件] → [CORS] → [Auth 中间件]
        ↓
[路由层 routers/] → [请求校验 schemas/]
        ↓
[Hub 编排器 hub/service.py]
        ↓
[Service 层 services/] → [公式引擎 formula_engine/]
        ↓
[存储层 database.py + cache.py]
        ↓
[PostgreSQL] + [Redis]

[APScheduler scheduler.py]
        ↓
[Fetcher 采集层 fetchers/] → publish_event → [Redis Streams]
        ↓
[Consumer 消费者 processors/pipeline.py]
        ↓
[Processor 处理层 processors/] → [DB/Redis 写入]
```

## 数据流

### 交易时段（9:30-15:00，每 5 分钟）

```
fetch_realtime → push2 clist(主) / 腾讯qt(备)
  → publish_event("realtime")
  → consumer → normalize → validate → safe_set_realtime → Redis rt:all (TTL 60s)
  → 末次覆盖 rt:close:{date} (TTL 24h)
```

### 日终（20:00-23:30）

```
20:00  fetch_fundamental → lsjz → publish_event("nav") → Redis nav:all (TTL 300s)
20:30  fetch_historical → push2his(主) / 腾讯K线(备) / AkShare(最终兜底)
       → publish_event("kline") → Redis kline:fund:{date}
23:30  scheduler → publish_event("daily_save")
       → consumer 合并 rt:close + nav:all → calculator → saver
       → DB fund_daily → 刷新物化视图 fund_snapshot
```

### 每周

```
周一 08:30  scan_codes → 扫描 LOF 代码列表 → DB fund_code_list
周一~五 09:00  fetch_info → fundf10 分批 300 只
       → publish_event("info") → DB fund_info/fund_fee/fund_holdings/fund_category
```

## 降级链

| 数据源 | 主源 | 备源1 | 备源2 |
|--------|------|-------|-------|
| 实时行情 | push2 clist | 腾讯 qt | - |
| 收盘净值 | lsjz | - | - |
| K线日线 | push2his | 腾讯K线 web.ifzq.gtimg.cn | AkShare |
| 费率/持仓 | fundf10 HTML | - | - |

所有外部请求需要 `Referer` 头（eastmoney 近期加强校验）。

## 模块依赖关系

```
app.py
  ├── routers/ → hub/service.py → services/ → database.py + cache.py
  │                                            ├── models.py
  │                                            ├── exceptions.py
  │                                            └── constants.py
  ├── processors/pipeline.py → processors/{normalize,validator,calculator,saver}
  │                         → cache.py + mq.py
  ├── fetchers/{realtime,fundamental,historical,info} → mq.py + metrics.py
  ├── scheduler.py → fetchers/ + processors/pipeline.py
  └── auth/middleware.py → config.py + exceptions.py
```

## 设计决策（ADR）

### ADR-1: SQLAlchemy async 而非 asyncpg 直连
- ORM 查询可读性好，适合 API 层
- 批量写入用原生 SQL（pg_insert），性能不受影响
- 2C2G 不需要 ORM 额外开销担忧

### ADR-2: Redis Streams 而非 asyncio.Queue
- 进程崩溃后 Stream 数据不丢失
- 单进程下 Queue 也够用，但 Stream 更利于后续扩展

### ADR-3: 公式引擎前后端双实现
- 后端零计算开销（前端求值）
- 用户隐私（公式策略不经过服务器）
- 离线可用

### ADR-4: Referer 头必须
- eastmoney 2026 年加强了 Referer 校验
- 无 Referer 的请求返回空数据或 ErrCode=-999
- 所有 fetcher 统一加 `Referer: https://fundf10.eastmoney.com/` 或 `https://quote.eastmoney.com/`

## 已知限制

- 单机架构，无水平扩展能力
- 2C2G 内存有限，Redis maxmemory=128MB
- push2 字段码硬编码，可能随 API 变化
- fundf10 HTML 解析依赖页面结构，改版需更新
- 腾讯 K 线不返回 amount/change_pct/turnover_rate，需估算
