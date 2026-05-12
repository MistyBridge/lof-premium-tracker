# 金快查 — 全市场 LOF 基金实时折溢价监控系统 - 项目开发日志

<div align="center">

**版本**: 2.1.0 | **更新日期**: 2026-05-06

![部署状态](https://img.shields.io/badge/前端-CF%20Pages%20Online-green)
![部署状态](https://img.shields.io/badge/后端-Railway%20Online-green)

</div>

---

## 📌 快速参考

| 项目 | 地址 |
|------|------|
| **前端（生产）** | https://lof-fund-monitor.pages.dev |
| **后端（生产）** | https://lof-premium-tracker-production.up.railway.app |
| **GitHub仓库** | https://github.com/MistyBridge/lof-premium-tracker |
| **Railway项目** | empowering-wonder / 服务: lof-premium-tracker |

---

## 📂 目录结构

```
lof-premium-tracker/
├── index.html                   # Web前端入口
├── css/
│   └── style.css              # 全局样式（深色模式 + 响应式）
├── js/
│   ├── config.js            # 环境配置（自动检测本地/生产）
│   ├── api.js             # API服务层（重试、超时、异常过滤）
│   └── app.js             # 主应用逻辑（LofFundMonitor类）
├── assets/
│   └── icon.jpg            # 品牌图标
├── agreement.html          # 用户协议
├── privacy.html            # 隐私政策
├── functions/               # Cloudflare Pages Functions
│   ├── _lib.js            # 共享模块（Railway URL等）
│   ├── api/[path].js      # API代理（/api/* → Railway）
│   └── health.js           # 健康检查代理
├── backend/                # 后端代码（Flask）
│   ├── app.py             # API服务入口
│   ├── config.py          # 应用配置
│   ├── data_fetcher.py    # 数据抓取（东方财富+天天基金）
│   ├── fee_fetcher.py     # 费率抓取
│   ├── history_db.py      # 历史数据库（PostgreSQL）
│   ├── history_fetcher.py # 历史数据补填
│   ├── history_seed.json  # 种子数据（冷启动降级）
│   ├── sz_lof_codes.json  # 深交所LOF代码缓存
│   └── requirements.txt   # Python依赖
├── miniprogram/            # 微信小程序（独立项目）
├── wrangler.toml           # CF Pages配置
└── .github/workflows/      # GitHub Actions
```

---

## 🌐 部署架构

```
用户浏览器 → CF Pages（静态 + Functions 代理）→ Railway（Flask 后端）
```

- **CF Pages代理**: 解决中国用户访问Railway美国节点被阻断的问题
- **缓存机制**: 后端启动时用历史数据初始化缓存，休市期间降级返回缓存数据
- **懒更新**: 用户访问API时按需触发后台数据刷新

---

## 🚀 部署方法

### 前端部署（Cloudflare Pages）

```bash
cd lof-premium-tracker/
npx wrangler pages deploy . --project-name lof-fund-monitor --branch main --commit-dirty=true
```

### 后端部署（Railway）

Railway 通过 GitHub 仓库自动部署：
- **仓库**: MistyBridge/lof-premium-tracker
- **项目**: empowering-wonder / 服务: lof-premium-tracker
- **启动命令**: `cd backend && gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120`

---

## 🛠️ 本地开发

### 前端开发

```bash
git clone https://github.com/MistyBridge/lof-premium-tracker.git
cd lof-premium-tracker
py -m http.server 8080
# 访问 http://localhost:8080
```

### 后端本地开发

```bash
cd backend
pip install -r requirements.txt
flask run --port 5000
```

---

## 📝 主要文件说明

### index.html
- 单页应用主结构
- 脚本加载顺序: `config.js` → Chart.js CDN → `api.js` → `app.js`

### js/config.js
- 环境自动检测：本地 `localhost` → `http://localhost:5000`，生产 → 同源代理

### js/api.js
- `api.getHealth()` / `api.getFunds(page, size)` / `api.getRankings()`

### js/app.js - LofFundMonitor 类
- `init()` - 5次重试初始化
- `loadFunds()` - 获取并过滤基金
- `calcEstimatedProfit(fund)` - 计算预期收益
- `showProfitDetail(code)` - 收益构成弹窗

### functions/
- `_lib.js` - 共享配置（Railway URL、代理函数）
- `api/[path].js` - API 路径代理
- `health.js` - 健康检查代理

---

## 📋 版本历史

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-05-06 | 2.1.0 | 项目架构标准化：模块化目录、死代码清理、前端工程化 |
| 2026-05-05 | 2.0.0 | 新UI：元宝刷新按钮、顶栏居中放大、模式切换修复 |
| 2026-05-04 | 1.2.0 | 部署到CF Pages + Railway |

---

## ⚠️ 注意事项

1. **Windows环境**: 使用 `py` 命令而非 `python`
2. **部署**: 必须用 wrangler CLI 部署前端（git push 不生效 Functions）
3. **文件编码**: UTF-8，无BOM
4. **换行符**: LF（Unix风格）

---

*本文档最后更新于 2026-05-06*
