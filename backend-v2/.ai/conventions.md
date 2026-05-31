# AI 协作约定

## 代码风格
- Python: PEP 8, black 格式化（line-length=100）
- 每行最大 100 字符
- 变量命名: snake_case
- 常量命名: UPPER_SNAKE_CASE
- 类名: PascalCase
- 私有属性/方法: _前缀

## Git 约定
- commit message: `type(scope): description`
  - type: feat / fix / refactor / docs / test / chore
  - scope: fetcher / processor / router / formula / cache / auth / hub / scheduler
  - 示例: `fix(fetcher): handle push2 timeout with retry`
- 不要在一个 commit 中做多件事
- 大功能用 feature branch，完成后 PR 到 main
- main 分支有保护，不能直接 push

## 沟通约定
- 不确定时问，不要猜
- 修改前先说计划，确认后再动手
- 每次修改说明"改了什么 + 为什么改"
- 涉及数据库 schema 变更必须说明迁移方案
- 多个方案时列出优劣，让用户选择

## 文件组织
- 新增文件前检查是否可以放在已有文件中
- 单文件不超过 300 行，超过则拆分
- 测试文件和源文件同目录或 tests/ 目录
- 配置相关放 config.py，不散落在各文件中
- 每个模块的 __init__.py 声明：依赖 / 被依赖 / 对外接口

## 错误处理约定
- 业务异常用 exceptions.py 中的类
- 不在 service 层直接 raise HTTPException
- 所有外部调用（API/Redis/DB）必须有超时和重试
- 错误日志包含足够上下文，能独立定位问题
- Redis 降级：所有操作 try-except，失败返回 None/默认值，不抛异常到调用方

## 日志约定
- 使用 Python logging 模块，不用 print
- 日志格式：`[%(asctime)s] [%(levelname)s] [%(module)s] %(message)s`
- ERROR 级别：影响用户体验的问题（API 返回 500、数据采集失败）
- WARNING 级别：不影响核心功能但需关注（降级触发、数据不完整）
- INFO 级别：关键业务节点（采集完成、定时任务触发、缓存刷新）
- DEBUG 级别：开发调试信息（生产环境关闭）
- 日志中不记录完整 token / 密码 / API Key

## 数据库约定
- 所有 TIMESTAMP 字段用 TIMESTAMPTZ（timezone-aware）
- 所有金额字段用 NUMERIC（不用 FLOAT，避免精度丢失）
- ORM 查询优先，批量写入用原生 SQL（executemany）
- 参数化查询，不拼接 SQL 字符串
- 每个新表必须有 updated_at 字段

## Redis 约定
- Key 命名: `{namespace}:{identifier}`，如 `rt:all`、`fee:160644`
- 日期格式: YYYYMMDD（如 20260530），不用 2026-05-30
- 所有写操作设置 TTL（缓存击穿锁 3s，实时数据 60s，净值 300s）
- 批量删除用 SCAN 而非 KEYS（避免阻塞）
- 所有操作必须有降级逻辑

## API 约定
- 响应格式: `{"code": 0, "data": {...}, "meta": {...}}`
- 错误格式: `{"code": 40100, "message": "未授权", "detail": "..."}`
- 错误码规则: HTTP 状态码 * 100 + 序号（40100 = 401 + 00）
- 分页: page 从 1 开始，size 最大 100
- 排序: sort 字段白名单，order 只允许 asc/desc
