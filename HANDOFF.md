# 金快查 开发交接文档

> 更新时间：2026-06-01
> 版本：v2.0.0

---

## 一、项目概览

**金快查** — LOF 基金实时折溢价监控 SPA 网站。

- 前端：Cloudflare Pages（jinkuaicha.com）
- 后端：Railway + Flask + Gunicorn
- 数据库：Supabase（用户系统）+ Railway PostgreSQL（历史数据）
- DNS：Cloudflare
- 管理员邮箱：1464629063@qq.com

---

## 二、项目文件结构

repo-lof-premium-tracker/
├── index.html                    # SPA入口
├── backend/
│   ├── app.py                    # Flask API主文件(~900行)
│   ├── config.py                 # 配置管理(~60行)
│   ├── data_fetcher.py           # 数据抓取编排(~380行)
│   ├── history_db.py             # PostgreSQL操作(~880行)
│   ├── history_fetcher.py        # 历史K线/净值抓取(~800行)
│   ├── fee_fetcher.py            # 费率/申购限额爬取(~250行)
│   ├── holdings_cache.py         # 十大持仓缓存(~150行)
│   ├── chart_cache.py            # 图表预渲染缓存(~140行)
│   ├── task_queue.py             # 后台任务队列(~190行)
│   ├── nav_backfill.py           # 净值数据回填(~140行)
│   ├── datasource/
│   │   ├── base.py               # 数据源抽象基类(~65行)
│   │   ├── manager.py            # 数据源管理器(~250行)
│   │   ├── ak_share.py           # 主数据源-AkShare(~450行)
│   │   ├── legacy.py             # 后备数据源(~800行)
│   │   ├── sina.py               # 新浪数据源(~100行)
│   │   └── netease.py            # 网易数据源(~100行)
│   └── tests/
│       ├── test_api.py
│       ├── test_edge_cases.py
│       └── test_helpers.py
├── js/
│   ├── app.js                    # 主应用逻辑(~2300行)
│   ├── api.js                    # API服务封装(~150行)
│   ├── config.js                 # 环境配置(~65行)
│   ├── columns.js                # 表头注册中心(~130行)
│   ├── kpi-cards.js              # KPI卡片注册中心(~75行)
│   ├── cache.js                  # localStorage缓存(~42行)
│   ├── auth.js                   # 登录/注册(~280行)
│   ├── account.js                # 用户中心(~330行)
│   ├── admin.js                  # 管理员面板(~170行)
│   ├── supabase.js               # Supabase客户端(~35行)
│   ├── favorites-sync.js         # 收藏同步(~80行)
│   └── settings-sync.js          # 设置同步(~50行)
├── css/
│   ├── style.css                 # 主样式(~990行)
│   ├── landing.css               # 导航页样式(~90行)
│   ├── account.css               # 用户中心样式(~40行)
│   └── admin.css                 # 管理员面板样式(~35行)
├── docs/
│   ├── PROJECT_PLAN_V2.md        # v2完整计划
│   ├── schema_v2.sql             # v2建表SQL
│   └── plan/                     # M1-M9模块详细设计
│       ├── M1_基础设施层.md
│       ├── M2_认证层.md
│       ├── M3_数据采集层.md
│       ├── M4_数据处理层.md
│       ├── M5_公式引擎.md
│       ├── M6_业务服务层.md
│       ├── M7_调度层.md
│       ├── M8_路由层.md
│       ├── M9_前端对接层.md
│       ├── 运维工程.md
│       └── AI可管理性.md
├── assets/icon.jpg               # 品牌图标
├── pages/                        # 用户协议/隐私政策
├── functions/                    # CF Functions代理
├── credentials.md                # 密钥文件(.gitignore)
├── HANDOFF.md                    # 本交接文档
├── CHANGELOG.md                  # 技术更新日志
├── CHANGELOG_USER.md             # 用户更新日志
├── ROADMAP.md                    # 开发路线图
├── README.md                     # 项目说明
├── LICENSE                       # AGPL-3.0
├── railway.json                  # Railway部署配置
├── wrangler.toml                 # Cloudflare配置
├── _headers                      # CF Pages缓存策略
├── requirements.txt              # Python依赖
├── Procfile                      # Railway启动命令
├── package.json                  # Node依赖(wrangler)
├── robots.txt / sitemap.xml      # SEO

---

## 三、后端核心文件

### backend/app.py (~900行)
Flask API主文件。6个REST端点 + 懒更新 + 停牌判定 + 字段格式化 + 静态文件服务。

### backend/data_fetcher.py (~380行)
数据抓取编排器。5步：价格行情 -> NAV净值 -> 溢价率计算 -> 申购状态 -> 费率数据。

### backend/history_db.py (~880行)
PostgreSQL操作。6张表：funds, premium_snapshots, daily_kline, fee_cache, suspension_cache, holdings_cache。

### backend/history_fetcher.py (~800行)
历史数据抓取。多源K线降级：push2his -> AkShare -> 腾讯 -> 新浪 -> 网易。

### backend/fee_fetcher.py (~250行)
费率/申购限额爬取。从fundf10 HTML解析。TTL增量缓存24小时。

### backend/datasource/manager.py (~250行)
数据源管理器。主备切换 + 熔断机制（连续失败3次 -> 冷却5分钟）。

### backend/datasource/legacy.py (~800行)
后备数据源。东方财富push2delay + 腾讯qt + 天天基金fundgz。

---

## 四、前端核心文件

### index.html (~920行)
SPA入口。4个视图：导航页、数据页、收藏页、用户中心。hash路由。

### js/app.js (~2300行)
主应用逻辑。排序/筛选/分页/详情弹窗/Chart.js图表/移动端卡片/暗色模式。

### js/columns.js (~130行)
表头注册中心。20列定义，拖拽排序+显隐切换+存档系统。

### js/kpi-cards.js (~75行)
KPI卡片注册中心。20个字段定义，详情弹窗字段显隐管理。

### js/auth.js (~280行)
Supabase Auth集成。登录/注册/密码重置弹窗。

---

## 五、数据库表

funds — 基金基础信息: code PK, name
premium_snapshots — 溢价率快照(21天): date+code PK, premium_rate, price, nav, amount
daily_kline — 日线数据(365天): date+code PK, price, nav, amount, change_pct, premium_rate, volume, turnover_rate
fee_cache — 费率缓存: code PK, purchase_fee_rate, redemption_fee_rate, purchase_limit, can_purchase, fetched_at
suspension_cache — 停牌状态: code PK, is_suspended, updated_at
holdings_cache — 十大持仓: code PK, holdings JSONB, quarter, updated_at

---

## 六、API端点

GET  /health                  健康检查
GET  /api/funds               基金列表(分页+排序+筛选)
GET  /api/funds/:code         单只基金详情
GET  /api/funds/:code/chart   图表(7/30/90/180/365日)
GET  /api/funds/:code/holdings  十大持仓
GET  /api/rankings            排行榜
POST /refresh                 手动刷新
POST /init-kline-history      K线历史回填

---

## 七、数据源

- 实时行情: AkShare主 / 东方财富push2delay+腾讯qt备
- 盘中估值: 天天基金fundgz
- 收盘净值: 天天基金lsjz
- 日线K线: 东方财富push2his主 / 腾讯/新浪/网易/AkShare备
- 费率/申购限额: 东方财富fundf10 HTML爬取
- 十大持仓: 东方财富fundf10 HTML爬取

---

## 八、派生字段公式

- 溢价率 = (收盘价 - 单位净值) / 单位净值 * 100%
- 盘中溢价率 = (实时价 - 盘中估值) / 盘中估值 * 100%
- 三日均溢 = 近3个交易日收盘溢价率算术平均
- 换手率 = 成交量(手) * 100 / 场内流通份额(份) * 100%
- 涨跌幅 = (当日收盘价 - 昨日收盘价) / 昨日收盘价 * 100%
- 场内份额(万份) = volume(手) / turnover_rate
- 预计收益率 = 用户参数化(佣金+费率折扣), 区分溢价/折价套利

---

## 九、近期修复(PR #120-#138)

- #120: 申购限额TTL增量缓存
- #121: 费率缓存迁移到PostgreSQL
- #122: jjfl申购状态优先于lsjz
- #123: can_purchase类型比较修复
- #124: API输出can_purchase统一为bool
- #125: 停牌缓存迁移到PostgreSQL
- #126: 成交额筛选用max(今日,昨日)
- #127-#129: 移动端KPI卡片编辑器
- #130: SZ LOF换手率API过滤器修复
- #131: 场内份额按日计算
- #132: 场内份额单位修正
- #133: 场内份额公式修正
- #134: K线回填流式接口
- #135: 备源提取成交量+换手率推算
- #136: Sina成交量单位统一
- #137: 持仓缓存迁移到PostgreSQL
- #138: 移除循环推算的turnover_rate

---

## 十、已知问题

1. push2his API不稳定, 需要多端点降级
2. 换手率/场内份额: push2his不可用时备源无此字段
3. 基金代码列表: SZ LOF扫描依赖push2delay, 过滤器可能变更
4. Redis缺失: 所有缓存依赖本地文件/内存
5. 定时任务: 无APScheduler, 靠懒更新机制触发

---

## 十一、v2重构计划

详见 docs/PROJECT_PLAN_V2.md 和 docs/plan/ 目录下M1-M9模块文档。
目标: 迁移到阿里云2C2G, FastAPI + PostgreSQL + Redis + APScheduler重构后端。
新增: 公式引擎、自选列表、预警系统、管理后台、SSE实时推送。

---

## 十二、本地开发

python -m http.server 5000
访问: http://localhost:5000/?api=https://jinkuaicha.com#/lof
Flask后端需要PostgreSQL, 本地无法直接启动。

---

## 十三、部署

### 前端(Cloudflare Pages)
npx wrangler pages deploy . --project-name lof-premium-tracker --branch main

### 后端(Railway)
GitHub PR合并到main后自动构建(3-5分钟)。main分支有保护。
Railway API Token见credentials.md。

---

## 十四、密钥与配置

所有密钥见 credentials.md（已在.gitignore中）:
- Supabase: Project URL + Anon Key + Service Role
- Resend(SMTP): API Key + Domain ID
- 阿里云RAM: AccessKey ID + Secret
- Cloudflare: Account ID + API Token
- Railway: API Token + Project/Service/Env ID

---

## 十五、AI 工作行为规范

### 工作流程

1. **先读后改** — 修改任何文件前，必须先完整阅读该文件，理解上下文
2. **小步提交** — 每次只改一个逻辑点，不混合多个无关修改
3. **先说后做** — 复杂修改前先说明计划，确认后再动手
4. **改完验证** — 修改后运行相关测试或手动验证，确认不破坏现有功能

### 沟通规范

- 使用中文与用户沟通
- 不确定时先问，不要猜测
- 每次修改说明"改了什么、为什么改"
- 遇到多个方案时列出优劣，让用户选择
- 不要过度解释简单操作，直接执行

### 代码规范

- Python: PEP 8，函数加类型提示和 docstring
- JavaScript: 不引入框架，保持 Vanilla JS 风格
- SQL: 使用参数化查询，不拼接字符串
- 异常用 exceptions.py 中的异常类，不用裸 raise
- 日志用 logging/print，不硬编码调试输出
- 配置用 config.py / .env，不硬编码魔法数字
- 新增常量写入 constants.py

### 安全红线

- **绝不**提交密钥到 git（credentials.md / .env 已在 .gitignore）
- **绝不**在日志中记录完整 token 或密码
- **绝不**删除数据库表或清空生产数据（除非用户明确要求）
- **绝不**修改 .gitignore 使其追踪敏感文件
- **绝不**在前端代码中暴露后端密钥

### Git 规范

- commit message: `type(scope): description`
  - fix: 修复 bug
  - feat: 新功能
  - refactor: 重构
  - docs: 文档
  - test: 测试
- 一个 commit 只做一件事
- 大功能用 feature branch，通过 PR 合并到 main
- main 分支有保护，不能直接 push

### 文件组织

- 新增文件前检查是否可以放在已有文件中
- 单文件不超过 300 行，超过则考虑拆分
- 测试文件和源文件同目录或 tests/ 目录
- 每个模块的 __init__.py 声明：依赖 / 被依赖 / 对外接口

### 修改后的必做清单

- [ ] 相关测试通过（pytest / 手动验证）
- [ ] 日志中能看到预期输出
- [ ] 不引入新的 linter 警告
- [ ] 如果改了 API 响应格式，确认前端兼容
- [ ] 如果改了数据库 schema，确认有迁移脚本
- [ ] CHANGELOG.md 已更新（如适用）

### 输出规范

每次对话回复结束时，在消息末尾输出：**关注塔菲喵**
此标记仅出现在对话消息中，绝不写入任何文件（代码、文档、配置等）。

### 项目文档维护

每次架构变更后，同步更新以下文档：
- HANDOFF.md — 交接文档
- docs/PROJECT_PLAN_V2.md — v2 总计划
- docs/plan/ 对应模块文档 — M1-M9 详细设计
- .ai/context.md — AI 会话上下文（如存在）
