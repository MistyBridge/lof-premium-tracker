# 金快查 开发交接文档

> 生成时间：2026-05-28 会话结束时

## 一、项目概览

**金快查** — LOF 基金实时折溢价监控 SPA 网站。
- 前端：CF Pages (`jinkuaicha.com`)
- 后端：Railway + Flask (`lof-premium-tracker-production.up.railway.app`)
- 数据库：Supabase (PostgreSQL, `dwlvonyixwmyrekvxzgx.supabase.co`)
- 邮件：Resend SMTP
- DNS：Cloudflare（`jinkuaicha.com`）

## 二、部署架构关键点

### Railway 部署注意事项
- **根目录必须有 `Procfile`**：`web: cd backend && gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120`
- **根目录必须有 `requirements.txt`**：Railway 的 Railpack 构建器需要根目录的 `requirements.txt` 来识别 Python 项目，否则会误判为静态站点
- **`_headers` 文件会触发误判**：Railpack 看到 `_headers` 会误判为 Staticfile。目前靠 Procfile + 根 requirements.txt 强制识别 Python
- **main 分支有保护**：必须通过 PR 合并，不能直接 push
- **部署触发**：GitHub PR 合并 → Railway 自动构建 → 约 3-5 分钟生效
- **Railway API Token**：`50aae961-b8de-4f33-b8b5-a73200cb4c02`（credentials.md）
- **项目 ID 映射**：project=`c0e26d00-bd99-4fde-bf69-36e585443881`, service=`502a61a6-1a59-4d16-a907-9ba2e6035f69`, env=`f8c432d7-47e4-4ec3-bdc3-4ce87c99cd52`

### 手工部署命令
```bash
# 前端（CF Pages）
npx wrangler pages deploy . --project-name lof-premium-tracker --branch main

# 后端（Railway）— 通过 GraphQL API 触发重启
# 或直接在 Railway Dashboard 点 Deploy 按钮
```

## 三、当前 Bug 状态

### ✅ 已修复
| Bug | 修复方式 | 文件 |
|-----|---------|------|
| 申购限额万元格式不解析(73%缺失) | 正则扩展 `万?元` | `backend/fee_fetcher.py` |
| 赎回费率缺失(12%) | 默认值 1.5% | `backend/fee_fetcher.py` |
| 详情弹窗限额显示"0万" | <10万显示元 | `js/app.js` |
| fee cache 新鲜度检查跳过抓取 | 删除 80% 检查，每次强制重抓 | `backend/data_fetcher.py` |
| app.js ES6 class 方法间多余逗号 | 删除逗号 | `js/app.js`（多次修复） |
| 脚本重复加载 | `_loadedScripts` 去重 | `index.html` |
| 旧缓存覆盖新数据 | `_loadingFunds` 锁 + 只在空时用缓存 | `js/app.js` |
| SZ enrichment `matched` 变量作用域 | 移到 try 块外 | `backend/datasource/legacy.py` |

### ⚠️ 进行中 — SZ LOF 换手率/场内份额
SSE LOF（50xxxx）已有换手率和场内份额数据，SZ LOF（16xxxx）补丁刚合入。
**需等 Railway 部署 + 5 分钟数据刷新周期后验证。**
关键文件：`backend/datasource/legacy.py` → `_enrich_sz_turnover()` 方法。
日志关键字：`SZ turnover enriched: X matched of Y funds`

## 四、基金数据字段概览

表头和 KPI 卡片共 20 个字段（统一注册表）：

| 字段 ID | 标签 | 数据源 |
|---------|------|--------|
| code | 代码 | push2 |
| name | 名称 | push2 |
| price | 现价 | push2 |
| nav | 净值 | 天天基金 |
| change_pct | 涨跌幅 | push2 |
| premium_rate | 溢价率 | 计算 |
| avg_premium_3d | 三日均溢 | history DB |
| amount | 成交额 | push2 |
| est_profit_rate | 预计收益率 | 前端计算 |
| est_profit_amount | 预计收益额 | 前端计算 |
| purchase_status | 状态 | ak_share + jjfl |
| purchase_limit | 申购限额 | jjfl |
| nav_date | 净值日期 | 天天基金 |
| volume | 成交量 | push2/计算 |
| change_amount | 涨跌额 | push2 |
| is_suspended | 停牌状态 | 后端判定 |
| purchase_fee_rate | 申购费率 | jjfl |
| data_date | 数据日期 | history DB |
| turnover_rate | 换手率 | push2 f18 ⚠️ |
| on_exchange_shares | 场内份额 | 计算 ⚠️ |

⚠️ = SZ LOF 数据待验证

## 五、用户系统

- Supabase 建表：`profiles`, `fund_favorites`, `user_settings`
- Auth 流程：邮箱注册 → 激活邮件 → 登录。`mailer_autoconfirm=False`
- 用户中心：`/#/account`，头像上传、昵称、改密、注销
- 管理员面板：`/#/admin`，需 `role='admin'`。RLS 策略已配
- 收藏同步：登录自动合并 localStorage ↔ Supabase
- 设置同步：登录自动推拉 localStorage ↔ Supabase
- 管理员邮箱：`1464629063@qq.com`

## 六、卡片/表头管理系统

### 表头编辑器（`js/columns.js`）
- 18+ 列注册表 `COLUMN_REGISTRY`
- 三视图：Active（拖拽+序号+垃圾桶）、Library（双面板）、Presets（存档）
- localStorage：`lof_column_prefs_v1`、`lof_column_presets_v1`

### KPI 卡片编辑器（`js/kpi-cards.js`）
- 20 卡片注册表 `KPI_CARD_REGISTRY`
- 与表头编辑器完全相同的三视图功能
- localStorage：`lof_kpi_card_prefs_v1`、`lof_kpi_card_presets_v1`
- 齿轮按钮在基金详情弹窗标题右侧

## 七、本地开发环境

```bash
# 启动本地文件服务器
cd D:\开发\金快查\repo-lof-premium-tracker
python -m http.server 5000

# 访问（API 走生产）
http://localhost:5000/?api=https://jinkuaicha.com#/lof
```

- Flask 后端需要 PostgreSQL，本地无法直接启动
- 测试用 API 走 `?api=https://jinkuaicha.com` 参数连生产

## 八、关键文件速查

| 文件 | 作用 |
|------|------|
| `index.html` | SPA 入口，4 个视图 + 路由 + 脚本加载器 |
| `js/app.js` | 主应用逻辑（~2300行） |
| `js/columns.js` | 表头注册表（20 列） |
| `js/kpi-cards.js` | KPI 卡片注册表 + 存档系统 |
| `js/auth.js` | 登录/注册/密码重置 |
| `js/account.js` | 用户中心页面 |
| `js/admin.js` | 管理员面板 |
| `js/favorites-sync.js` | 收藏云端同步 |
| `js/settings-sync.js` | 设置云端同步 |
| `js/supabase.js` | Supabase 客户端封装 |
| `js/cache.js` | localStorage 缓存模块 |
| `backend/app.py` | Flask API（~830行） |
| `backend/fee_fetcher.py` | jjfl 费率抓取 |
| `backend/data_fetcher.py` | 数据刷新主流程 |
| `backend/datasource/legacy.py` | push2/腾讯数据源 |
| `backend/holdings_cache.py` | 十大持仓缓存 |
| `backend/history_db.py` | PostgreSQL 历史数据库 |
| `backend/holdings_cache.py` | 十大持仓缓存模块 |
| `css/style.css` | 主样式 |
| `css/landing.css` | 导航页样式 |
| `css/account.css` | 用户中心样式 |
| `css/admin.css` | 管理员面板样式 |
| `Procfile` | Railway 启动命令 |
| `requirements.txt` | 根目录 Python 依赖（Railway 构建识别） |
| `_headers` | CF Pages 缓存策略 |
| `credentials.md` | 所有密钥（已 .gitignore） |

## 九、下一步建议

1. **验证 SZ LOF 换手率** — 等 Railway 部署后查 `160644` 的 `turnover_rate` 是否为非 None
2. **PWA 化（M2.8）** — `manifest.json` + `sw.js`，ROADMAP 已有详细方案
3. **flask-limiter 验证** — 已恢复依赖，确认限流生效
4. **fd-profit-section 清理** — 预计收益额区域在 HTML 中还存在，可删除
5. **M5 扩展** — ETF、历史回测等远期功能

## 十、数据库备份
Supabase 数据已备份到 `supabase/data_backup.json`（4 profiles, 0 favorites, 0 settings）。
