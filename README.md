# 金快查 — 全市场 LOF 基金实时折溢价监控系统 | LOF 套利助手

<div align="center">

![Version](https://img.shields.io/badge/version-1.2.0-blue.svg)
![Platform](https://img.shields.io/badge/platform-Web%20%7C%20API-green.svg)
![License](https://img.shields.io/badge/license-AGPLv3-red.svg)
![Status](https://img.shields.io/badge/status-active-brightgreen.svg)
![DB](https://img.shields.io/badge/data-538%20funds%20%7C%2091K%20rows-orange.svg)
![Website](https://img.shields.io/badge/www-jinkuaicha.com-1890ff.svg)

**全市场 ~540 只深沪 LOF 实时折溢价监控 · 365天日线图表 · 套利模拟回测 · 溢价率排行 · PC + 移动端**

[在线使用](https://jinkuaicha.com) · [更新日志](CHANGELOG_USER.md) · [技术文档](docs/TECH.md) · [开发指南](docs/DEVELOPMENT.md)

</div>

---

## 这是什么？

金快查是一款专注 **LOF 基金折溢价监控** 的开源工具，面向个人投资者与量化爱好者，提供全市场 LOF 基金的 **实时溢价率、折价率、成交额、预计套利收益** 等核心指标。支持 PC 网页和移动端 H5 两种访问方式，覆盖 **LOF 套利全流程** 从数据发现到收益测算。

> **LOF 基金**（Listed Open-Ended Fund，上市型开放式基金）同时存在场内交易价格和场外基金净值，二者偏差即为折溢价。当溢价率足够覆盖交易成本时，投资者可通过 **申购→卖出** 或 **买入→赎回** 进行套利操作。

---

## 核心功能

### 数据监控
| 功能 | 说明 |
|------|------|
| 全市场覆盖 | 深沪两市全部 LOF 基金（~540 只），深市代码每周自动扫描更新 |
| 实时溢价率 | 场内价格 vs 场外净值实时对比，溢价/折价一目了然 |
| 三日均溢 | 近 3 个交易日平均溢价率，过滤短期噪音，发现稳定套利标的 |
| 涨跌幅 & 成交额 | 当日涨跌幅 + 实时成交额，辅助判断流动性与市场情绪 |
| 净值类型标注 | 区分「正式净值」（盘后公布）与「估算净值」（盘中实时），明确数据可靠程度 |

### 套利分析
| 功能 | 说明 |
|------|------|
| 预计收益率 | 自动扣除申购费率 + 赎回费率 + 券商佣金，输出净收益率 |
| 预计收益额 | 结合投入金额上限与基金申购限额，计算实际预期收益 |
| 费率明细拆解 | 溢价/折价套利各环节费用逐项展示，识别最低佣金门槛 |
| 套利流程引导 | 内置溢价套利（申购→卖出）与折价套利（买入→赎回）全流程说明 |

### 体验设计
| 功能 | 说明 |
|------|------|
| 暗色模式 | 手动切换，偏好自动持久化 |
| 响应式布局 | PC 端表格式数据看板 + 移动端卡片式信息流 |
| 多端支持 | Web 网页 + 移动端 H5，响应式设计自适应屏幕 |
| 基金详情弹窗 | 12 项 KPI 指标 + 7 交易日价格/净值双线 Chart.js 图表 |
| 个性化筛选 | 自定义溢价率阈值、三日均溢阈值、成交额门槛、佣金参数 |

---

## 项目结构

```
lof-premium-tracker/
├── index.html                 # Web 前端入口（单页 SPA）
├── css/style.css              # 全局样式（暗色模式 + 响应式）
├── js/
│   ├── config.js              # 环境配置（API 地址、刷新间隔等）
│   ├── api.js                 # 网络层（请求封装、自动重试、超时处理）
│   └── app.js                 # 业务逻辑（排序、筛选、弹窗、Chart.js 图表）
├── assets/icon.jpg            # 品牌图标
├── pages/
│   ├── agreement.html         # 用户协议
│   └── privacy.html           # 隐私政策
├── functions/                 # Cloudflare Functions 代理层
│   ├── api/[[path]].js        # /api/* → Railway 后端代理
│   └── health.js              # /health 健康检查代理
├── backend/                   # Flask 后端服务
│   ├── app.py                 # API 路由（6 个 REST 端点）
│   ├── config.py              # 配置常量
│   ├── data_fetcher.py        # 多数据源聚合引擎
│   ├── fee_fetcher.py         # 基金费率爬虫（申购/赎回费率）
│   ├── history_fetcher.py     # 历史 K 线 + 净值数据抓取
│   ├── history_db.py          # PostgreSQL 历史数据读写 + 自动清理
│   ├── datasource/            # 分级数据源适配层（AKShare 主源 + 东方财富/天天基金/腾讯后备）
│   ├── sz_lof_codes.json      # 深市 LOF 代码缓存（每周自动刷新）
│   └── requirements.txt       # Python 后端依赖

│   ├── pages/index/           # 列表页（基金列表 + 排行榜）
│   ├── pages/detail/          # 详情页
│   └── utils/                 # 工具函数
├── docs/
│   ├── TECH.md                # 技术架构文档
│   └── DEVELOPMENT.md         # 本地开发指南
├── railway.json               # Railway 部署配置
├── wrangler.toml              # Cloudflare Pages 配置
├── requirements.txt           # Railway 构建依赖
└── LICENSE                    # GNU AGPL v3.0
```

---

## 部署架构

```
用户浏览器 ──→ Cloudflare Pages (静态资源 CDN 分发)
                   │
                   └──→ CF Functions (/api/* 反向代理)
                            │
                            └──→ Railway (Flask + Gunicorn)
                                     │
                                     ├──→ PostgreSQL (历史快照存储)
                                     └──→ 15 个数据源 (详见下方「全部数据源」章节)
                                           ├── AKShare（主）: fund_lof_spot_em / fund_lof_hist_em / fund_open_fund_info_em
                                           └── Legacy（备）: 东方财富 push2delay/push2his + 腾讯 qt + 天天基金 fundgz + lsjz
                                                              + 新浪 + 网易 + Baostock + OpenBB + TuShare
```

| 层级 | 平台 | 技术栈 | 职责 |
|------|------|--------|------|
| 前端 | Cloudflare Pages | HTML5 + CSS3 + Vanilla JS + Chart.js | 页面渲染、数据可视化、用户交互 |
| 代理 | Cloudflare Functions | JavaScript (Service Worker) | 同源 API 代理，解决跨境网络访问 |
| 后端 | Railway | Python Flask + Gunicorn | 数据聚合、缓存、API 服务 |
| 数据库 | Railway PostgreSQL | PostgreSQL | 历史净值/价格日线，365 天滚动保留，91,697 行 |
| 数据源(主) | AKShare | akshare Python 库 | 全量 LOF 行情、日K线、历史净值 |
| 数据源(备) | 东方财富 / 腾讯 / 新浪 / 网易 / 天天基金 等 | push2delay/push2his / qt / fundgz / lsjz 等 | 主源故障时整体降级，NAV 缺失时逐基金补缺，K线 8 级串行降级 |
| 数据源(爬虫) | 东方财富 fundf10 | fundf10.eastmoney.com | 申购/赎回费率、申购限额 |

### 分级数据源策略

系统采用 **主备双源 + 逐基金降级** 的数据获取策略，保障数据可用性：

```
AKShare (主数据源)
  ├── fund_lof_spot_em()     → 全市场 LOF 实时行情（价格/涨跌幅/成交额）
  ├── fund_lof_hist_em()     → 日K线历史数据
  ├── fund_open_fund_info_em() → 历史单位净值走势
  └── fundgz API (天天基金)    → 盘中估算净值 & 盘后正式净值

         ↓ 主源整体失败 / 返回空 ↓

Legacy (后备数据源)
  ├── 东方财富 push2delay     → SSE 沪市 LOF 行情 + SZ 深市代码扫描
  ├── 腾讯 qt.gtimg.cn        → SZ 深市 LOF 实时行情
  ├── 天天基金 fundgz         → 估算净值（逐基金补缺）
  └── 东方财富 lsjz           → 历史净值兜底
```

| 降级策略 | 触发条件 | 行为 |
|----------|----------|------|
| 价格行情整体降级 | AKShare 抛异常或返回空 DataFrame | 全量切换至 Legacy，沪市走 push2delay + 深市走腾讯 QT |
| NAV 逐基金降级 | AKShare 的 fundgz 对某只基金返回空 | 对缺失 NAV 的基金逐个调用后备源 fundgz → lsjz 补缺 |
| K线/历史净值整体降级 | AKShare 对应接口失败 | 整体切换至 Legacy 的东方财富 push2his / lsjz |

> **设计意图**：AKShare 提供一站式全量数据，简化日常抓取流程；Legacy 直连东方财富/腾讯/天天基金 API，在主源不可用时保障核心数据不中断。NAV 采用逐基金降级而非整体切换，最大化保留主源有效数据，仅对缺失项精准补缺。

---

## 全部数据源

本项目对接 **13 个数据源**，按用途分为行情价格、K线历史、净值、费率四类：

### 行情价格（实时）

| # | 数据源 | API / 库 | 覆盖 | 用途 |
|---|--------|----------|------|------|
| 1 | **东方财富 push2delay** | `push2delay.eastmoney.com` | 沪市 LOF | 实时价格、涨跌幅、成交额 |
| 2 | **腾讯 QT** | `web.ifzq.gtimg.cn` | 深市 LOF | 实时价格、涨跌幅、成交额 |
| 3 | **AkShare** | `akshare.fund_lof_spot_em()` | 全市场 | 一站式 LOF 实时行情（主源） |

### K线历史（日线）

| # | 数据源 | API / 库 | 优先级 | 说明 |
|---|--------|----------|--------|------|
| 4 | **东方财富 push2his** | `push2his.eastmoney.com` | 第1顺位 | 日K线 OHLC + 成交量额，官方数据 |
| 5 | **新浪财经** | `money.finance.sina.com.cn` | 第2顺位 | JSONP 日K线，240日历史 |
| 6 | **网易财经** | `img1.money.126.net` | 第3顺位 | JSON 日K线，按年分文件 |
| 7 | **腾讯 QT K线** | `web.ifzq.gtimg.cn` | 第4顺位 | 前复权日K线，400日历史 |
| 8 | **Baostock** | `baostock` Python 库 | 第5顺位 | 证券宝，需登录 session |
| 9 | **OpenBB / Yahoo** | `openbb` / `yfinance` | 第6顺位 | 海外数据源备选 |
| 10 | **TuShare** | `tushare` Python 库 | 第7顺位 | 需 token，宽度覆盖 |
| 11 | **AkShare K线** | `akshare.fund_lof_hist_em()` | 第8顺位 | 全量日K线（主源） |

> K线数据采用 **多源串行降级**：9 个数据源按优先级依次尝试，首个返回有效数据的源即被采用，其余跳过。单只基金最多被 1 个源命中，避免重复拉取。

### 净值数据

| # | 数据源 | API / 库 | 说明 |
|---|--------|----------|------|
| 12 | **天天基金 fundgz** | `fundgz.1234567.com.cn` | 盘中估算净值 + 盘后正式净值（实时） |
| 13 | **东方财富 lsjz** | `api.fund.eastmoney.com/f10/lsjz` | 历史单位净值（分页拉取，每页 20 条） |

> 实时净值优先取 fundgz（区分 jzrq 净值日期与 gsz 估算值），历史净值回填走 lsjz。NAV 缺失时逐基金降级补缺，不整体切换。

### 费率数据

| # | 数据源 | API | 说明 |
|---|--------|-----|------|
| 14 | **东方财富 fundf10** | `fundf10.eastmoney.com` | 申购费率、赎回费率、申购限额 |

### 基金代码

| # | 数据源 | API | 说明 |
|---|--------|-----|------|
| 15 | **东方财富 push2delay** | `push2delay.eastmoney.com` | 沪市 LOF 代码扫描（全量分页） |
| — | **本地缓存** | `sz_lof_codes.json` | 深市 LOF 代码缓存（每周刷新） |

### 数据源优先级总览

```
实时行情:  AkShare (主) → 东方财富 push2delay + 腾讯 QT (备)
K线日线:  东方财富 push2his → 新浪 → 网易 → 腾讯 QT → Baostock
           → OpenBB/Yahoo → TuShare → AkShare (8级降级)
净值:     天天基金 fundgz (主) → 东方财富 lsjz (备)
费率:     东方财富 fundf10 (缓存 80%命中率以上跳过爬虫)
代码:     本地缓存 sz_lof_codes.json + 东方财富 SSE 扫描
```

---

## 快速开始

### 在线使用（无需部署）

访问 **[lof-fund-monitor.pages.dev](https://lof-fund-monitor.pages.dev)** 即可直接使用。

### 本地开发

```bash
# 克隆仓库
git clone https://github.com/MistyBridge/lof-premium-tracker.git
cd lof-premium-tracker

# 启动前端（端口 8080）
py -m http.server 8080

# 启动后端（端口 5000，需新开终端）
cd backend
pip install -r requirements.txt
flask run --port 5000

# 浏览器访问
# http://localhost:8080?api=http://localhost:5000
```

### 生产部署

```bash
# 前端 — Cloudflare Pages
npx wrangler pages deploy . --project-name lof-fund-monitor --branch main

# 后端 — 推送 GitHub 后 Railway 自动部署
git push origin main
```

---

## API 端点

| 方法 | 路径 | 参数 | 说明 |
|------|------|------|------|
| `GET` | `/api/funds` | `page`, `page_size`, `sort`, `order`, `keyword`, `min_premium`, `min_amount` | 全量基金列表（分页 + 排序 + 搜索 + 多条件筛选） |
| `GET` | `/api/funds/<code>` | — | 单只基金详情（含申购/赎回费率） |
| `GET` | `/api/funds/<code>/chart` | `days` (7/30/90/180/365) | 价格/净值双线 + 溢价率曲线，支持 5 种时间范围 |
| `GET` | `/health` | — | 服务健康检查（缓存状态、最后更新时间） |
| `POST` | `/refresh` | — | 手动触发全量数据刷新 |
| `POST` | `/init-history` | — | 手动补填历史快照数据 |

---

## 数据更新频率

| 数据类型 | 更新频率 | 触发方式 |
|----------|----------|----------|
| 场内实时价格 / 净值 / 溢价率 | 每 5 分钟 | 用户访问时懒更新 |
| 基金申购/赎回费率 | 按需 | 首次查看某基金时抓取并缓存 |
| 深市 LOF 代码列表 | 每周 | 自动扫描 push2delay 全表 |
| 历史 K 线 / 历史净值 | 每日 | 懒更新时自动保存当日快照，周末触发器拦截 |
| 历史数据保留期 | 365 天 | 超期数据自动清理 |

---

## 常见问题 (FAQ)

<details>
<summary><strong>LOF 基金溢价率怎么算？</strong></summary>
溢价率 = (场内交易价格 − 场外基金净值) / 场外基金净值 × 100%。正值表示溢价（市价高于净值），负值表示折价（市价低于净值）。金快查自动拉取实时价格与最新净值，即时计算并展示。
</details>

<details>
<summary><strong>LOF 套利怎么操作？风险是什么？</strong></summary>
溢价套利：场内申购（按净值）→ T+2 到账 → 场内卖出（按市价），赚取溢价差价。折价套利：场内买入（按市价）→ T+1 赎回（按净值），赚取折价差价。主要风险在于 T+N 期间价格波动可能侵蚀套利空间，需确保溢价率覆盖申购费 + 佣金等交易成本。
</details>

<details>
<summary><strong>什么是三日平均溢价率？有什么用？</strong></summary>
三日均溢是近 3 个交易日溢价率的算术平均值。单日溢价率可能因短期波动失真，三日均溢可过滤噪音，帮助发现持续性折溢价机会，是判断套利标的稳定性的重要参考。
</details>

<details>
<summary><strong>正式净值和估算净值有什么区别？</strong></summary>
正式净值是基金公司每日收盘后公布的官方单位净值，准确但滞后；估算净值是盘中根据基金持仓实时推算的参考净值，及时但可能存在偏差。金快查在页面中明确标注净值类型，供用户判断数据可靠程度。
</details>

---

## 相关项目

| 项目 | 说明 |
|------|------|
| [在线 Demo](https://lof-fund-monitor.pages.dev) | 生产环境在线实例 |

---

## 技术文档

完整的架构设计、数据流说明、模块详解、配置参数等详见：

- **[技术文档 (TECH.md)](docs/TECH.md)** — 系统架构、数据源适配、数据库设计
- **[开发指南 (DEVELOPMENT.md)](docs/DEVELOPMENT.md)** — 本地环境搭建、调试技巧、贡献指南

---

## License

本项目基于 **GNU Affero General Public License v3.0 (AGPL-3.0)** 开源。

> 仅供个人学习与非商业场景免费使用。任何企业、组织机构及个人用于商业运营、私有化部署、二次修改后集成至商业产品及服务，均须提前获得作者书面授权许可。

Copyright © 2026 [MistyBridge](https://github.com/MistyBridge)
