# 金快查 — 全市场 LOF 基金实时折溢价监控系统

<div align="center">

![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)
![Platform](https://img.shields.io/badge/platform-Web%20%7C%20API-green.svg)
![License](https://img.shields.io/badge/license-AGPLv3-red.svg)
![Status](https://img.shields.io/badge/status-active-brightgreen.svg)
![Backend](https://img.shields.io/badge/backend-FastAPI-009688.svg)
![DB](https://img.shields.io/badge/db-PostgreSQL%2014-336791.svg)
![Website](https://img.shields.io/badge/www-jinkuaicha.com-1890ff.svg)

**全市场 ~540 只深沪 LOF 实时折溢价监控 · 365天日线图表 · 套利收益测算 · 溢价率排行 · PC + 移动端**

[在线使用](https://jinkuaicha.com) · [更新日志](CHANGELOG_USER.md) · [API 文档](https://api.jinkuaicha.com/docs) · [技术文档](docs/TECH.md)

</div>

---

## 这是什么？

金快查是一款专注 **LOF 基金折溢价监控** 的开源工具，面向个人投资者与量化爱好者，提供全市场 LOF 基金的 **实时溢价率、折价率、成交额、预计套利收益** 等核心指标。支持 PC 网页和移动端 H5，覆盖 LOF 套利全流程。

> **LOF 基金**（Listed Open-Ended Fund）同时存在场内交易价格和场外基金净值，二者偏差即为折溢价。当溢价率足够覆盖交易成本时，投资者可通过 **申购→卖出** 或 **买入→赎回** 进行套利。

---

## 核心功能

### 数据监控
| 功能 | 说明 |
|------|------|
| 全市场覆盖 | 深沪两市全部 LOF 基金（~540 只），代码自动扫描更新 |
| 实时溢价率 | 场内价格 vs 场外净值实时对比，每 5 分钟刷新 |
| 三日均溢 | 近 3 个交易日平均溢价率，过滤短期噪音 |
| 停牌检测 | 基于成交量自动判断停牌状态，支持筛选隐藏 |
| 溢价状态 | 自动标注溢价/折价/平价，辅助决策 |
| 净值类型 | 区分正式净值与估算净值，明确数据可靠程度 |

### 套利分析
| 功能 | 说明 |
|------|------|
| 预计收益率 | 自动扣除申购费率 + 赎回费率 + 券商佣金 |
| 预计收益额 | 结合投入金额与申购限额，计算实际预期收益 |
| 费率明细 | 溢价/折价套利各环节费用逐项展示 |
| 申购限额 | 显示具体限额金额，无限额显示"不限额" |

### 数据展示
| 功能 | 说明 |
|------|------|
| 自定义表头 | 34 列可选，显隐切换、拖拽排序、偏好持久化 |
| 金额分级 | >=10亿用亿，>=10万用万，否则用元 |
| 场内份额 | 每 5 分钟从成交量/换手率实时计算 |
| 成交额补算 | 低成交基金自动补算，不显示 0 |
| 基金详情 | 35+ 项指标 + 价格/净值双线图表 |
| 暗色模式 | 手动切换，偏好持久化 |
| 响应式布局 | PC 表格 + 移动端卡片 |

---

## 部署架构

```
用户浏览器 ──→ Cloudflare Pages (前端 CDN)
                   │
                   └──→ CF Functions (/api/* 代理)
                            │
                            └──→ 阿里云 ECS (FastAPI)
                                     │
                                     ├──→ PostgreSQL 14 (数据存储)
                                     ├──→ Redis 7 (缓存+消息队列)
                                     └──→ 15 个数据源
```

| 层级 | 平台 | 技术栈 | 职责 |
|------|------|--------|------|
| 前端 | Cloudflare Pages | Vanilla JS + Chart.js | 页面渲染、数据可视化 |
| 代理 | Cloudflare Functions | JavaScript | 同源 API 代理 |
| 后端 | 阿里云 ECS 2C2G | FastAPI + SQLAlchemy async | 数据聚合、API 服务、定时任务 |
| 数据库 | 阿里云 ECS | PostgreSQL 14 | 16 张表 + 物化视图 |
| 缓存 | 阿里云 ECS | Redis 7 | 实时数据缓存 + Streams 消息队列 |
| 调度 | 进程内 | APScheduler | 9 个定时任务 |
| 认证 | Supabase | JWT | 用户系统 |

### 分层架构

```
[前端] → [Nginx] → [认证中间件] → [路由层] → [Hub 编排器] → [Service 层] → [存储层]
                                                                         ↑
[定时任务] → [Fetcher] → [Redis Stream] → [Consumer/Processor] → [DB/Redis]
```

### 数据流

| 时段 | 流程 |
|------|------|
| 交易时段 (每5分钟) | push2 → Stream → Consumer → Redis rt:all + 停牌判断 |
| 日终 (23:30) | 合并收盘价+净值 → calculator → DB fund_daily → 刷新物化视图 |
| 每周 | fundf10 分批爬取 → fund_info/fund_fee/fund_holdings |

### 数据源

| 类型 | 主源 | 备源 |
|------|------|------|
| 实时行情 | 东方财富 push2 | 腾讯 QT |
| 日线K线 | 东方财富 push2his | AkShare (8级降级) |
| 净值 | 天天基金 fundgz/lsjz | — |
| 费率 | 东方财富 fundf10 | — |
| 代码 | push2delay 扫描 | 本地缓存 |

---

## 快速开始

### 在线使用

访问 **[jinkuaicha.com](https://jinkuaicha.com)**

### 本地开发

```bash
git clone https://github.com/MistyBridge/lof-premium-tracker.git
cd lof-premium-tracker

# 前端
py -m http.server 5001

# 后端（需 PostgreSQL + Redis）
cd backend-v2
pip install -r requirements.txt
uvicorn app:app --reload --port 8001

# 浏览器
# http://localhost:5001?api=http://localhost:8001#/lof
```

### 生产部署

```bash
# 前端 — Cloudflare Pages
npx wrangler pages deploy . --project-name lof-premium-tracker --branch main

# 后端 — 阿里云 ECS
scp backend-v2/ root@your-server:/opt/jinkuaicha/backend-v2/
ssh root@your-server "systemctl restart jinkuaicha"
```

---

## API 端点

### 公开端点
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/funds` | 基金列表（分页+排序+筛选） |
| GET | `/api/v1/funds/{code}` | 基金详情 |
| GET | `/api/v1/funds/{code}/chart` | 图表数据（7/30/90/180/365天） |
| GET | `/api/v1/funds/{code}/holdings` | 十大持仓 |
| GET | `/api/v1/funds/batch` | 批量查询 |
| GET | `/api/v1/funds/rankings` | 溢价率排行 |
| GET | `/api/v1/assets` | 资产列表 |
| GET | `/api/v1/data/fund/{code}` | 日线查询 |

### 需登录
| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST/PUT/DELETE | `/api/v1/formulas/*` | 公式 CRUD + 分组 |
| GET/POST/DELETE | `/api/v1/watchlist/*` | 自选列表 |
| GET/POST/DELETE | `/api/v1/alerts/*` | 预警规则 |

### 管理员
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/admin/monitor` | 系统监控 |
| GET | `/api/v1/admin/diagnose/*` | 诊断（redis/db/fetcher/queue） |
| POST | `/api/v1/admin/ops/*` | 操作（刷新缓存/物化视图） |
| GET | `/api/v1/admin/audit-log` | 审计日志 |

完整 API 文档：[api.jinkuaicha.com/docs](https://api.jinkuaicha.com/docs)

---

## 项目结构

```
lof-premium-tracker/
├── index.html                    # 前端 SPA 入口
├── js/
│   ├── app.js                    # 主业务逻辑（排序/筛选/弹窗/图表）
│   ├── api.js                    # API 请求封装
│   ├── columns.js                # 表头注册中心（34 列）
│   └── config.js                 # 环境配置
├── css/                          # 样式
├── backend-v2/                   # v2 后端（FastAPI）
│   ├── app.py                    # 入口 + lifespan
│   ├── config.py                 # Pydantic Settings
│   ├── database.py               # SQLAlchemy async engine
│   ├── models.py                 # 16 张 ORM 模型
│   ├── cache.py                  # Redis 缓存封装
│   ├── mq.py                     # Redis Streams
│   ├── scheduler.py              # APScheduler 定时任务
│   ├── fetchers/                 # 数据采集层
│   ├── processors/               # 数据处理层
│   ├── services/                 # 业务服务层
│   ├── hub/                      # 中台编排器
│   ├── routers/                  # API 路由层
│   ├── auth/                     # 认证中间件
│   ├── formula_engine/           # 公式引擎（AST）
│   ├── schemas/                  # Pydantic 模型
│   ├── tests/                    # 测试
│   ├── sql/                      # 种子数据 + 迁移
│   └── .ai/                      # AI 治理元数据
├── functions/                    # Cloudflare Functions
├── docs/                         # 文档
├── CHANGELOG.md                  # 技术更新日志
├── CHANGELOG_USER.md             # 用户更新日志
├── HANDOFF.md                    # 交接文档
└── LICENSE                       # AGPL-3.0
```

---

## 常见问题

<details>
<summary><strong>溢价率怎么算？</strong></summary>
溢价率 = (场内价格 - 场外净值) / 场外净值 × 100%。正值溢价，负值折价。
</details>

<details>
<summary><strong>LOF 套利怎么操作？</strong></summary>
溢价套利：申购(净值) → T+2到账 → 卖出(市价)。折价套利：买入(市价) → T+1赎回(净值)。需确保溢价率覆盖申购费+佣金。
</details>

<details>
<summary><strong>三日均溢有什么用？</strong></summary>
近3个交易日溢价率均值，过滤短期噪音，发现稳定套利机会。
</details>

<details>
<summary><strong>停牌状态怎么判断？</strong></summary>
基于最近交易日数据：成交量>0为交易中，收盘价为空或成交量为0为停牌。每5分钟更新。
</details>

---

## License

**GNU AGPL v3.0** — 仅供个人学习与非商业场景免费使用。商业用途须获得作者书面授权。

Copyright © 2026 [MistyBridge](https://github.com/MistyBridge)
