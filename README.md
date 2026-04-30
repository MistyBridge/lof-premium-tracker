# LOF 基金溢价监控系统

> A股场内LOF基金实时行情 + 净值/估值 + 溢价率分析 Web 平台

**仓库**: https://github.com/woredasdnmv/lof-premium-tracker

---

## 一、项目概述

本项目旨在帮助投资者监控 A股场内LOF基金的**溢价率**，发现折溢价套利机会。

### 什么是 LOF 基金溢价率？

LOF（Listed Open-Ended Fund，上市型开放式基金）同时在场内（股票账户）和场外（天天基金等渠道）交易。

- **溢价**：场内价格 > 场外净值 → 可卖出场内 + 申购场外套利
- **折价**：场内价格 < 场外净值 → 可买入场内 + 赎回场外套利

### 核心数据

| 指标 | 说明 |
|------|------|
| 基金代码 + 名称 | 沪深两市全部场内LOF |
| 实时价格 | 东方财富/腾讯行情推送 |
| 估算净值 | 天天基金盘后估算（15:30前）/ 正式净值（15:30后） |
| 溢价率 | `(现价 - 净值) / 净值 × 100%` |
| 成交额 | 当日场内成交金额 |

---

## 二、技术架构

### 当前架构（本地开发模式）

```
┌─────────────────────────────────────────────────────────┐
│                     用户浏览器                          │
│              https://xxx.railway.app                    │
└─────────────────────┬───────────────────────────────────┘
                      │ HTTPS
┌─────────────────────▼───────────────────────────────────┐
│                    Railway 后端                         │
│              Python Flask + Gunicorn                    │
│                  端口: $PORT                            │
└─────────────────────┬───────────────────────────────────┘
                      │ HTTP
        ┌─────────────┼──────────────┐
        ▼             ▼              ▼
  东方财富API   腾讯行情API   天天基金API
   (价格)        (价格)       (净值)
```

**懒更新逻辑**：Railway 免费版闲置30分钟休眠，首次访问时自动唤醒并刷新全量数据（~30-60秒），后续访问直接返回缓存，5分钟内不重复刷新。

### 部署目标架构（待完成）

| 层级 | 平台 | 状态 |
|------|------|------|
| 前端（Web界面） | Cloudflare Pages | 待部署 |
| 后端（API服务） | Railway | 待部署 |
| 数据源 | 天天基金/东方财富/腾讯 | ✅ 稳定 |

---

## 三、项目结构

```
lof-premium-tracker/
├── app.py              # Flask 后端入口（懒更新逻辑）
├── config.py           # 环境变量配置
├── data_fetcher.py     # 数据采集模块（东方财富/腾讯/天天基金）
├── requirements.txt    # Python 依赖
├── railway.json        # Railway 部署配置
├── sz_lof_codes.json   # 深市LOF代码缓存（自动生成）
├── index.html          # Web 前端页面
├── css/
│   └── style.css       # 页面样式
├── js/
│   ├── config.js       # API 地址配置
│   ├── api.js          # API 请求封装
│   └── app.js          # 前端业务逻辑（表格渲染/筛选/轮询）
├── _run.bat            # Windows 一键启动脚本
└── miniprogram/        # 微信小程序源码（独立项目）
    ├── app.js / app.json / app.wxss
    ├── pages/
    │   ├── index/       # 基金列表页（首页）
    │   └── detail/      # 单只基金详情页
    └── utils/
        ├── config.js    # 小程序配置
        ├── request.js   # 请求封装
        └── format.js    # 格式化工具
```

---

## 四、API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/funds` | GET | 全量基金列表，支持分页、排序、筛选 |
| `/api/funds/<code>` | GET | 单只基金详情 |
| `/api/rankings` | GET | 溢价率排行榜 |
| `/api/stats` | GET | 全局统计（总数、有NAV数、有溢价率数） |
| `/api/refresh` | POST | 手动触发数据刷新（Railway冷启动用） |
| `/api/health` | GET | 健康检查 |

### 请求参数示例

```
GET /api/funds?page=1&page_size=20&sort=premium_rate&order=desc&has_nav=1&exchange=sh
```

---

## 五、快速部署

### 方式一：Railway + Cloudflare Pages（推荐）

**Step 1: 部署后端**
1. 访问 https://railway.app 并登录
2. 点击 **New Project** → **Deploy from GitHub repo**
3. 选择仓库 `woredasdnmv/lof-premium-tracker`
4. Railway 自动检测 Python，构建完成后给出 URL（形如 `xxx.railway.app`）

**Step 2: 更新前端 API 地址**
1. 拿到 Railway URL 后，修改 `js/config.js`：
   ```js
   const API_BASE_URL = 'https://xxx.railway.app';
   ```
2. 提交并推送到 GitHub

**Step 3: 部署前端**
1. 访问 https://pages.cloudflare.com 并登录
2. 点击 **Create a project** → **Connect to Git**
3. 选择仓库 `woredasdnmv/lof-premium-tracker`
4. **Build settings** 留空（纯静态），**Output directory** 填 `/`
5. 部署完成，获得 Cloudflare Pages URL

---

### 方式二：本地运行

**环境要求**
- Python 3.9+
- Windows/macOS/Linux

**安装依赖**
```bash
pip install flask flask-cors requests apscheduler gunicorn
```

**启动服务**
```bash
python app.py
```

或双击运行：
```bash
_run.bat
```

然后浏览器打开 http://localhost:5000

---

## 六、微信小程序

`miniprogram/` 目录下是配套的微信小程序源码，可导入微信开发者工具独立调试。

**主要页面：**
- **首页**：基金列表，支持按溢价率/成交额排序、关键词搜索
- **详情页**：单只基金的完整数据（价格/净值/溢价率/换手率）

> ⚠️ 小程序上线需在 `utils/config.js` 中将 `ENV` 改为 `prod` 并配置真实后端地址。

---

## 七、数据说明

- **数据来源**：东方财富（沪市价格）、腾讯行情（深市价格）、天天基金网（净值/估算净值）
- **全部免费**：无 API Key 要求，无频率限制
- **更新频率**：懒更新模式，首次访问时刷新，5分钟内不重复刷新
- **覆盖范围**：沪深两市全部场内LOF基金（约550只）
- **净值缺失**：QDII原油/期货类基金（如501018、501300等）天天基金网不提供净值数据

---

## 八、技术细节

### 数据采集流程

```
1. 读取 sz_lof_codes.json（深市LOF代码列表，缓存）
2. 从东方财富获取沪市LOF全量数据（push2delay.eastmoney.com）
3. 从腾讯行情获取深市LOF全量数据（qt.gtimg.cn）
4. 并发抓取天天基金网净值数据（fundgz.1234567.com.cn，含重试）
5. 合并计算溢价率，存入内存缓存
```

### 懒更新实现

Railway 免费版闲置30分钟会自动休眠，冷启动时：
1. Railway 唤醒进程 → 首次 API 请求触发懒更新
2. 后台全量刷新数据（30-60秒）
3. 返回最新数据给用户
4. 后续请求直接读缓存，5分钟内不重复刷新

---

## 九、常见问题

**Q: Railway 冷启动慢怎么办？**
A: 懒更新模式下冷启动约30-60秒属正常现象。Railway 付费版无休眠，可解决此问题。

**Q: 溢价率数据为什么不准确？**
A: 估算净值是天天基金根据持仓估算，盘后正式净值通常在15:30-20:00更新。套利操作请以正式净值为准。

**Q: 如何添加新的LOF基金？**
A: 深市LOF代码需手动更新 `sz_lof_codes.json`（腾讯API返回全量），沪市由东方财富自动覆盖。

---

## 十、License

MIT License · 柯涵 · 2026
