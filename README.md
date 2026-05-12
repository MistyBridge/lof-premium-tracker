# 金快查 — 全市场 LOF 基金实时折溢价监控系统

<div align="center">

![Version](https://img.shields.io/badge/version-3.0.0-blue.svg)
![Platform](https://img.shields.io/badge/platform-Web%20%7C%20MiniProgram-green.svg)
![License](https://img.shields.io/badge/license-AGPLv3-red.svg)

**全市场 ~540 只深沪 LOF 实时折溢价监控，套利收益一键计算**

[在线使用](https://lof-fund-monitor.pages.dev) · [技术文档](docs/TECH.md)

</div>

> 本项目基于 GNU AGPLv3 开源协议开放源码，仅供个人学习、非商业场景免费使用。
> 任何企业、组织机构及个人，凡用于商业运营、私有化部署、二次修改后集成至商业产品及服务，均须提前获得作者书面授权许可，未经授权禁止使用、分发与商用。

---

## 功能特性

- **全市场覆盖** — 深沪两市全部 LOF 基金（~540 只），含深市代码每周自动扫描更新
- **实时溢价监控** — 溢价率、三日均溢、涨跌幅、成交额一目了然
- **套利收益计算** — 自动扣除申购/赎回/佣金费率，计算预计收益率与收益额
- **基金详情弹窗** — 12 项 KPI 指标 + 7 交易日价格/净值双线图表（Chart.js）
- **费率明细** — 溢价/折价套利费用拆解，含最低佣金识别
- **双模式切换** — 移动端溢价模式（高→低）与折价模式（低→高）一键切换
- **套利流程引导** — 内置溢价/折价套利全流程说明与风险提示
- **暗色模式** — 自适应系统偏好，手动切换持久化
- **响应式设计** — PC 表格布局 + 移动端卡片布局，适配所有屏幕
- **多端支持** — Web 端（PC + 移动）+ 微信小程序

---

## 项目结构

```
lof-premium-tracker/
├── index.html                 # Web 前端入口（单页应用）
├── css/style.css              # 全局样式（暗色模式 + 响应式）
├── js/
│   ├── config.js              # 运行配置（API 地址、分页等）
│   ├── api.js                 # 网络层（请求封装、重试、健康检查）
│   └── app.js                 # 业务逻辑（渲染、排序、筛选、弹窗、Chart）
├── assets/icon.jpg            # 品牌图标
├── pages/
│   ├── agreement.html         # 用户协议
│   └── privacy.html           # 隐私政策
├── functions/                 # Cloudflare Functions 代理层
│   ├── api/[[path]].js        # /api/* → Railway 代理
│   └── health.js              # /health 健康检查代理
├── backend/                   # Flask 后端
│   ├── app.py                 # API 路由（6 个端点）
│   ├── config.py              # 配置常量
│   ├── data_fetcher.py        # 多数据源抓取引擎（~800 行）
│   ├── fee_fetcher.py         # 费率爬虫
│   ├── history_fetcher.py     # 历史 K 线 + 净值抓取
│   ├── history_db.py          # PostgreSQL 读写 + 清理
│   ├── sz_lof_codes.json      # 深市 LOF 代码缓存（每周自刷新）
│   └── requirements.txt       # Python 依赖
├── miniprogram/               # 微信小程序
├── docs/
│   ├── TECH.md                # 详细技术文档
│   └── DEVELOPMENT.md         # 开发指南
├── railway.json               # Railway 部署配置
├── wrangler.toml              # Cloudflare Pages 配置
└── requirements.txt           # Railway 构建依赖
```

---

## 部署架构

```
浏览器 ──→ Cloudflare Pages (静态文件)
         ──→ CF Functions (/api/* 代理)
                └──→ Railway (Flask + Gunicorn)
                       └──→ PostgreSQL (premium_snapshots)
```

| 层 | 平台 | 技术 |
|---|------|------|
| 前端 | Cloudflare Pages | HTML5 + CSS3 + Vanilla JS + Chart.js |
| 代理 | Cloudflare Functions | JavaScript |
| 后端 | Railway | Python Flask + Gunicorn |
| 数据库 | Railway PostgreSQL | PostgreSQL |
| 数据源 | 东方财富 / 天天基金 / Tencent | push2delay / fundgz / qt |

---

## 快速开始

### 在线使用
访问 **[lof-fund-monitor.pages.dev](https://lof-fund-monitor.pages.dev)**

### 本地开发

```bash
# 克隆
git clone https://github.com/MistyBridge/lof-premium-tracker.git
cd lof-premium-tracker

# 前端（端口 8080）
py -m http.server 8080
# 访问 http://localhost:8080?api=http://localhost:5000

# 后端（端口 5000）
cd backend
pip install -r requirements.txt
flask run --port 5000
```

### 部署

```bash
# 前端
npx wrangler pages deploy . --project-name lof-fund-monitor --branch main

# 后端 — 推送 GitHub 后 Railway 自动部署
git push origin main
```

---

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/funds` | 全量基金列表（分页 + 排序 + 搜索 + 筛选） |
| `GET` | `/api/funds/<code>` | 单只基金详情 |
| `GET` | `/api/funds/<code>/chart` | 近 7 交易日价格/净值曲线 |
| `GET` | `/health` | 服务健康状态 |
| `POST` | `/refresh` | 手动触发全量刷新 |
| `POST` | `/init-history` | 手动补填历史数据 |

---

## 数据更新频率

| 数据 | 频率 | 说明 |
|------|------|------|
| 场内价格 / 净值 / 溢价率 | 每 5 分钟 | 懒更新（用户访问触发） |
| 深市 LOF 代码列表 | 每周 | 自动扫描 push2delay |
| 历史 K 线 / 净值 | 每日 | 懒更新时自动保存快照 |
| 历史数据保留 | 21 天 | 超期自动清理 |

---

## 技术文档

完整的架构设计、数据流、模块说明、配置常量等详见 **[技术文档 (TECH.md)](docs/TECH.md)**。

---

## License

GNU AGPLv3 © 2026
