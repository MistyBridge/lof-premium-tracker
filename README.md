# LOF 基金折溢价监控系统

<div align="center">

![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.9+-green.svg)
![License](https://img.shields.io/badge/license-MIT-orange.svg)

**实时监控 A 股场内 LOF 基金溢价率，发现套利机会**

[在线演示](https://lof-fund-monitor.pages.dev) · [API 文档](#api-接口) · [部署指南](#快速部署)

</div>

---

## 📖 目录

- [项目简介](#项目简介)
- [功能特性](#功能特性)
- [技术架构](#技术架构)
- [在线演示](#在线演示)
- [快速部署](#快速部署)
- [本地运行](#本地运行)
- [API 接口](#api-接口)
- [项目结构](#项目结构)
- [核心算法](#核心算法)
- [数据说明](#数据说明)
- [常见问题](#常见问题)
- [更新日志](#更新日志)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

---

## 项目简介

LOF（Listed Open-Ended Fund，上市型开放式基金）同时在场内（股票账户）和场外（天天基金等渠道）交易。由于两个市场的定价机制不同，经常出现**价格偏离净值**的情况，这为套利提供了机会：

- **溢价套利**：场内价格 > 场外净值 → 卖出场内 + 申购场外
- **折价套利**：场内价格 < 场外净值 → 买入场内 + 赎回场外

本项目实时监控沪深两市全部 LOF 基金的折溢价情况，帮助投资者快速发现套利机会。

### 核心数据

| 指标 | 说明 |
|------|------|
| 实时价格 | 场内交易价格（东方财富/腾讯行情） |
| 估算净值 | 天天基金盘中估算净值 |
| 正式净值 | 天天基金盘后正式净值 |
| 溢价率 | `(现价 - 净值) / 净值 × 100%` |
| 三日均溢 | 最近 3 个交易日成交量加权平均溢价率 |
| 成交额 | 当日场内成交金额（万元） |

---

## 功能特性

### ✨ 核心功能

- 📊 **全量监控** - 覆盖沪深两市全部场内 LOF 基金（约 550+ 只）
- 🔄 **实时更新** - 每 5 分钟自动刷新，支持手动刷新
- 📈 **溢价排行** - TOP10 溢价/折价基金实时排行
- 🎯 **智能筛选** - 支持溢价率阈值、成交额阈值、三日均值筛选
- 📱 **移动适配** - 完美支持手机端，卡片式布局
- 🔍 **快速搜索** - 按基金代码/名称实时搜索

### 🎨 界面特性

- **溢价率标色**：红色溢价、绿色折价、黑色平价
- **多维度排序**：按溢价率、三日均价、成交额、涨跌幅排序
- **分页浏览**：支持 20/50/100/200 条每页
- **状态指示**：实时显示数据来源（估算净值/正式净值）

### ⚙️ 高级功能

- **三日平均溢价率**：成交量加权平均，过滤低成交噪音
- **种子数据预加载**：休市期间降级返回历史数据
- **Cloudflare 代理**：国内访问优化，隐藏后端地址

---

## 技术架构

### 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                     用户浏览器                              │
│              https://lof-fund-monitor.pages.dev            │
└─────────────────────┬───────────────────────────────────────┘
                      │ HTTPS (CF Pages Functions Proxy)
                      │
┌─────────────────────▼───────────────────────────────────────┐
│               Cloudflare Pages (静态资源)                    │
│              - index.html / css / js                        │
│              - Functions: /api/* 代理到 Railway             │
└─────────────────────┬───────────────────────────────────────┘
                      │ 内部代理
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                    Railway 后端                             │
│              Python Flask + Gunicorn                        │
│              - 内存缓存 (5分钟刷新)                          │
│              - SQLite 历史数据库 (7天滚动)                    │
│              - history_seed.json 种子数据                    │
└─────────────────────┬───────────────────────────────────────┘
                      │ HTTP (信任代理: 无 VPN)
        ┌─────────────┼──────────────┐
        ▼             ▼              ▼
  东方财富API     腾讯行情API    天天基金API
 (沪市LOF价格)   (深市LOF价格)   (净值/估算净值)
```

### 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **前端** | 纯 HTML/CSS/JS | 无框架依赖，轻量快速 |
| **前端部署** | Cloudflare Pages | 全球 CDN，Functions 代理 |
| **后端** | Python Flask | RESTful API 服务 |
| **后端部署** | Railway | 美国节点，免费额度 |
| **数据源** | 东方财富/腾讯/天天基金 | 免费，无需 API Key |

### 数据流

```
启动 → 加载种子数据 → 初始化缓存 → 
  ↓
后台线程 → 每 5 分钟全量抓取 → 计算溢价率 → 保存历史快照 → 更新缓存
  ↓
API 请求 → 读取缓存 → 格式化输出 → 返回 JSON
```

---

## 在线演示

🌐 **生产环境**: https://lof-fund-monitor.pages.dev

> ⚠️ Railway 免费版冷启动约 30 秒，首次访问可能稍慢。Railway 部署在美国，从中国访问可能需要等待。

---

## 快速部署

### 方式一：Railway + Cloudflare Pages（推荐）

#### Step 1: Fork 仓库

点击 GitHub 页面右上角 **Fork** 按钮。

#### Step 2: 部署后端到 Railway

1. 访问 [Railway.app](https://railway.app) 并登录
2. 点击 **New Project** → **Deploy from GitHub repo**
3. 选择你 Fork 的仓库
4. Railway 自动检测 Python，等待构建完成
5. 获得后端 URL（形如 `https://xxx.railway.app`）

#### Step 3: 配置环境变量（可选）

在 Railway Dashboard 中添加环境变量：

```
REQUEST_TIMEOUT=30      # API 请求超时（秒）
REFRESH_INTERVAL=300    # 数据刷新间隔（秒）
```

#### Step 4: 部署前端到 Cloudflare Pages

1. 访问 [Cloudflare Pages](https://pages.cloudflare.com) 并登录
2. 点击 **Create a project** → **Connect to Git**
3. 选择你 Fork 的仓库
4. **Build settings** 留空（纯静态）
5. **Output directory** 填 `/`
6. 部署完成，获得前端 URL

#### Step 5: 更新 API 地址

修改 `js/config.js`：

```javascript
const API_BASE_URL = 'https://你的railway域名.railway.app';
```

提交并推送，Cloudflare Pages 会自动重新部署。

---

### 方式二：Render.com（亚太节点，国内更快）

1. 访问 [Render.com](https://render.com) 并登录
2. 点击 **New** → **Web Service**
3. 连接 GitHub 仓库
4. **Region** 选择 `Singapore` 或 `Oregon`
5. **Build Command**: `pip install -r requirements.txt`
6. **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4`
7. 部署完成

---

## 本地运行

### 环境要求

- Python 3.9+
- pip

### 安装依赖

```bash
pip install -r requirements.txt
```

### 启动服务

```bash
python app.py
```

或使用 Gunicorn（生产模式）：

```bash
gunicorn app:app --bind 0.0.0.0:5000 --workers 1 --threads 4
```

### 访问应用

打开浏览器访问 http://localhost:5000

---

## API 接口

### 基础接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/api/funds` | GET | 全量基金列表 |
| `/api/funds/<code>` | GET | 单只基金详情 |
| `/api/refresh` | POST | 手动刷新数据 |
| `/api/init-history` | POST | 初始化历史数据 |

### `/api/funds` 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|-------|------|
| `page` | int | 1 | 页码 |
| `page_size` | int | 50 | 每页条数 |
| `sort` | string | `premium_rate` | 排序字段 |
| `order` | string | `desc` | 排序方向 |
| `min_premium` | float | - | 最小溢价率（%） |
| `max_premium` | float | - | 最大溢价率（%） |
| `min_amount` | float | - | 最小成交额（万元） |

### 响应示例

```json
{
  "data": [
    {
      "code": "501001",
      "name": "华夏磐晟LOF",
      "price": 1.234,
      "nav": 1.100,
      "premium_rate": 12.18,
      "avg_premium_3d": 10.52,
      "change_pct": 2.35,
      "amount": 1234.56,
      "nav_source": "estimate",
      "data_date": "2026-05-01"
    }
  ],
  "total": 553,
  "page": 1,
  "page_size": 50,
  "last_fetch": "2026-05-01T18:19:00"
}
```

### 字段说明

| 字段 | 说明 |
|------|------|
| `code` | 基金代码 |
| `name` | 基金名称 |
| `price` | 场内现价 |
| `nav` | 净值（估算净值或正式净值） |
| `premium_rate` | 实时溢价率（%） |
| `avg_premium_3d` | 三日成交量加权平均溢价率（%） |
| `change_pct` | 当日涨跌幅（%） |
| `amount` | 当日成交额（万元） |
| `nav_source` | 净值来源：`estimate`=估算净值，`formal`=正式净值 |
| `data_date` | 数据日期 |

---

## 项目结构

```
lof-fund-monitor/
├── app.py                    # Flask 应用入口
├── config.py                 # 配置管理
├── data_fetcher.py           # 数据采集模块
├── history_db.py             # SQLite 历史数据管理
├── history_fetcher.py        # 历史数据抓取（本地用）
├── requirements.txt          # Python 依赖
├── railway.json              # Railway 部署配置
├── Procfile                  # Railway 启动命令
├── history_seed.json         # 种子数据（7天历史）
├── current_snapshot.json     # 当前快照
├── sz_lof_codes.json         # 深市 LOF 代码列表
│
├── index.html                # 前端页面
├── css/
│   └── style.css             # 样式表
├── js/
│   ├── config.js             # API 配置
│   ├── api.js                # API 请求封装
│   └── app.js                # 前端业务逻辑
│
├── functions/                # Cloudflare Pages Functions
│   ├── api/
│   │   └── [[path]].js       # API 代理
│   └── health.js             # 健康检查端点
│
├── _routes.json              # CF Pages 路由配置
│
└── README.md                 # 本文档
```

---

## 核心算法

### 三日平均溢价率计算

采用**成交量加权平均**算法，让交易活跃日期的溢价率权重更高：

```
三日均价 = Σ(premium_rate × amount) / Σ(amount)
```

| 数据天数 | 计算方式 |
|---------|---------|
| 1 天 | 直接使用当日溢价率 |
| 2 天 | 两天的成交量加权平均 |
| 3 天 | 三天的成交量加权平均 |

**特殊处理**：
- 成交额为 0 时：退化为简单算术平均
- 无历史数据时：返回 `null`（前端显示 `--`）

### 数据存储

- **内存缓存**：全量基金数据，5 分钟刷新
- **SQLite 数据库**：每日溢价率快照，保留 7 天
- **种子数据**：预置 12 天历史数据，冷启动降级用

---

## 数据说明

### 数据来源

| 数据 | 来源 | 更新时间 |
|------|------|---------|
| 沪市 LOF 价格 | 东方财富 push2delay API | 盘中实时 |
| 深市 LOF 价格 | 腾讯 qt.gtimg.cn API | 盘中实时 |
| 估算净值 | 天天基金 fundgz API | 盘中估算 |
| 正式净值 | 天天基金 fundgz API | 15:30-20:00 更新 |

### 覆盖范围

- **沪市 LOF**：东方财富 API 自动覆盖（约 280 只）
- **深市 LOF**：预置代码列表（约 270 只）
- **总计**：约 550+ 只场内 LOF 基金

### 数据缺失

部分基金天天基金网不提供净值数据：
- QDII 原油基金（501018、501300 等）
- 期货类基金
- 海外资产基金

这些基金溢价率显示为 `--`。

---

## 常见问题

### Q: Railway 冷启动很慢怎么办？

**A**: Railway 免费版闲置 30 分钟自动休眠，冷启动约 30-60 秒。解决方案：

1. **付费版**：$5/月，无休眠限制
2. **Cron 唤醒**：每 20 分钟 ping 一次 `/health` 端点
3. **迁移到 Render**：亚太节点，国内访问更快

### Q: 溢价率数据为什么不准确？

**A**: 估算净值是天天基金根据持仓估算的，盘中可能与实际净值有偏差。盘后正式净值通常在 15:30-20:00 更新，套利操作请以正式净值为准。

### Q: 如何添加新的 LOF 基金？

**A**: 
- 沪市 LOF：东方财富 API 自动覆盖新基金
- 深市 LOF：手动更新 `sz_lof_codes.json`

### Q: 三日均价有什么用？

**A**: 过滤单日低成交噪音。如果某天成交额极低但溢价率异常，加权平均会降低其权重，三日均价更能反映真实套利空间。

### Q: 为什么中国访问慢？

**A**: Railway 服务器在美国，跨太平洋网络延迟较高。解决方案：
- 使用 Cloudflare Pages Functions 代理（已配置）
- 迁移到 Render.com 亚太节点

---

## 更新日志

### v1.1.0 (2026-05-01)

**新增功能**
- ✨ 三日平均溢价率（成交量加权）
- ✨ Cloudflare Pages Functions 代理（国内访问优化）
- ✨ 种子数据预加载（休市降级）
- ✨ 移动端卡片布局
- ✨ 溢价/折价 TOP10 排行条

**优化改进**
- 🚀 超时时间 15s → 30s
- 🚀 重试次数 2 → 3 次
- 🐛 修复 NAV null 覆盖 bug
- 🐛 修复折价排行无数据 bug
- 💄 移动端文案统一："三日均" → "三日均溢"

### v1.0.0 (2026-04-23)

- 🎉 初始版本发布
- ✨ 全量 LOF 基金监控
- ✨ 实时溢价率计算
- ✨ PC/移动端自适应

---

## 贡献指南

欢迎提交 Issue 和 Pull Request！

### 开发环境

```bash
# 克隆仓库
git clone https://github.com/woredasdnmv/lof-premium-tracker.git
cd lof-premium-tracker

# 安装依赖
pip install -r requirements.txt

# 启动开发服务器
python app.py
```

### 代码规范

- Python: 遵循 PEP 8
- JavaScript: 使用 ES6+ 语法
- 提交信息: 使用约定式提交（Conventional Commits）

---

## 许可证

[MIT License](LICENSE) © 柯涵 2026

---

## 致谢

- 数据来源：[东方财富](https://www.eastmoney.com)、[天天基金](https://fund.eastmoney.com)、腾讯行情
- 部署平台：[Railway](https://railway.app)、[Cloudflare Pages](https://pages.cloudflare.com)
- 灵感来源：LOF 套利社区

---

<div align="center">

**如果觉得有用，请给个 ⭐ Star 支持一下！**

</div>
