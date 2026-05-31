# 金快查 - AI 上下文

## 项目简介
金快查 - 全市场 LOF 基金实时折溢价监控系统（jinkuaicha.com）
技术栈: FastAPI + SQLAlchemy async + asyncpg + PostgreSQL 14 + Redis 7 + APScheduler
部署: 阿里云 2C2G（华北2北京），Nginx + systemd
前端: Cloudflare Pages（静态托管，前端不在 v2 重写范围内）
用户系统: Supabase Auth（JWT 验证，保留现有 Supabase）

## 当前状态
最新版本: v2.0.0-dev
架构阶段: 阶段 0 完成（项目脚手架），阶段 1-12 待实施
待处理: M1 基础设施层 → M2 认证层 → M3 采集层 → M4 处理层 → M5 公式引擎 → M6 服务层 → M7 调度层 → M8 路由层 → M9 前端对接

## 已知问题
- v2 处于开发初期，大部分模块为骨架代码
- v1 后端仍在 Railway 运行，v2 上线前需并行维护
- push2 字段码 f204（盘中估值）在部分基金上返回 0
- fundf10 持仓页偶发超时，需要重试
- 换手率/场内份额: push2his 不可用时备源无此字段

## 代码规范
- 异常用 exceptions.py 中的异常类，不用 HTTPException
- 日志用 logging 不用 print
- 配置用 config.py / .env，不硬编码
- 所有 Redis 操作有降级逻辑（try-except，不抛异常到调用方）
- 所有 DB 操作用 async session，异常时自动 rollback
- datetime 用 timezone-aware（datetime.now(timezone.utc)）
- Decimal 值入库前 round 到 4 位小数
- 单文件不超过 300 行，超过则拆分

## 关键文件
- app.py: FastAPI 入口 + lifespan（初始化 DB/Redis/调度器/消费者）
- hub/service.py: 中台编排器（调 Service + 缓存失效协调）
- processors/pipeline.py: 数据处理 Stream 消费者主循环
- scheduler.py: APScheduler 定时任务（9 个 job）
- formula_engine/: 公式引擎（AST 解析 + 安全求值）
- fetchers/: 数据采集层（push2/腾讯/lsjz/fundf10/AkShare）
- services/: 业务服务层（fund/asset/data/formula/alert/system/sse）
- routers/: API 路由层（funds/assets/data/formulas/watchlist/alerts/admin/stream）

## 数据源
- 实时行情: push2（主） + 腾讯 QT（备）
- 盘中估值: 天天基金 fundgz
- 收盘净值: 天天基金 lsjz
- 日线K线: push2his（主） + AkShare（备，8 级降级）
- 费率/持仓: fundf10 HTML 爬取
- 代码列表: push2delay（沪市） + 本地缓存（深市）

## 服务器信息
- ECS IP: 101.200.129.61（公网） / 172.19.96.182（内网）
- 系统: Ubuntu 22.04, 2C2G, 40GB ESSD
- PostgreSQL: 14.23, deploy 用户, jinkuaicha 数据库
- Redis: 6.0.16, 128MB maxmemory
- Python: 3.11.15 venv at /opt/jinkuaicha/venv
- Nginx: 1.18.0, 反代 8000, gzip + SSL
- 管理员邮箱: 1464629063@qq.com

## 红线约束
- **禁止修改前端代码**: index.html / js/ / css/ / pages/ / assets/ / functions/ 不得改动
- **禁止修改 v1 后端**: backend/ 目录保持现有 Railway 运行状态
- **仅操作 backend-v2/**: 所有新代码写入 backend-v2/ 目录
- **API 兼容性**: v2 API 字段名和结构要考虑将来前端切换的兼容性
- **前端切换方式**: 将来通过 Cloudflare DNS 或 URL 参数 ?api=https://api.jinkuaicha.com 切换到 v2
- **并行运行**: v1 后端（Railway）和 v2 后端（阿里云）并行运行，v2 验证通过后再切换