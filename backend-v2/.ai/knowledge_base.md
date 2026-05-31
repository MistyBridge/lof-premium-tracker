# 已知问题知识库

## push2 超时
- 症状: fetcher/realtime 返回空列表
- 日志: `[ERROR] [external_api] push2 connection timeout`
- 原因: 东方财富偶尔限流或网络抖动
- 解决: 自动重试 3 次（tenacity），间隔 5 秒。仍失败切换腾讯备源
- 预防: 已有重试机制，通常自动恢复。连续 3 次失败触发告警
- 首次发现: 2026-05-15
- 出现频率: 每周 1-2 次

## push2 字段码变更
- 症状: push2 返回的某些字段值为 0 或 None
- 日志: `[WARNING] [fetcher] field f204 returns 0 for all funds`
- 原因: 东方财富可能修改字段码映射
- 解决: 用 push2 全字段 dump 确认新字段码，更新 realtime.py 中的字段映射
- 预防: 字段码抽查机制（每次采集随机抽 5 只基金校验关键字段非零）
- 首次发现: 2026-05-18
- 出现频率: 极少

## Redis 连接断开
- 症状: API 返回 `realtime_available: false`
- 日志: `[ERROR] [cache] Redis connection refused`
- 原因: Redis 进程被 OOM killer 杀死（内存超 128MB）或进程异常退出
- 解决: `systemctl restart redis`，检查 `redis-cli info memory`
- 预防: 已配置 maxmemory 128MB + allkeys-lru
- 首次发现: 2026-05-20
- 出现频率: 极少

## fundf10 HTML 解析失败
- 症状: info 采集返回空持仓/空费率
- 日志: `[WARNING] [info] fundf10 parse failed for {code}`
- 原因: 东方财富改版页面结构或网络超时
- 解决: 检查 fundf10.eastmoney.com 页面，更新解析逻辑
- 预防: 连续 3 只解析失败自动中断并告警
- 首次发现: 2026-05-18
- 出现频率: 每月 1 次

## QDII 净值延迟
- 症状: 23:30 入库时 QDII 基金无当日净值
- 日志: `[INFO] [daily_save] QDII nav not available for {code}, using estimated`
- 原因: QDII 净值通常 T+1 或 T+2 才出
- 解决: 使用昨日净值，标记 `nav_type='estimated'`
- 预防: 23:00 单独跑一次 QDII 净值获取
- 首次发现: 2026-05-22
- 出现频率: 每个交易日

## lsjz 并发限流
- 症状: lsjz 批量获取部分基金返回空
- 日志: `[WARNING] [fundamental] lsjz rate limit for {code}`
- 原因: 天天基金 API 限流，Semaphore(5) 不够
- 解决: 失败的基金延迟 1 秒重试，最多重试 3 次
- 预防: Semaphore 控制并发 + 0.3s 间隔
- 首次发现: 2026-05-20
- 出现频率: 每日采集时偶发

## 物化视图刷新慢
- 症状: 物化视图刷新耗时 > 5 秒
- 原因: fund_daily 数据量增长，JOIN 查询变慢
- 解决: 检查索引是否完整，VACUUM ANALYZE
- 预防: weekly_cleanup.sh 定期 VACUUM
- 首次发现: 待观察
- 出现频率: 待观察

## 深市 LOF 代码扫描失败
- 症状: 深市 LOF 基金数据缺失
- 日志: `[ERROR] [fetcher] SZ LOF scan failed`
- 原因: push2delay 过滤器参数变更
- 解决: 检查 push2delay API 参数，更新过滤条件
- 预防: 使用本地缓存 sz_lof_codes.json 作为兜底
- 首次发现: 待观察
- 出现频率: 待观察

## PostgreSQL 连接池耗尽
- 症状: API 返回 500 错误
- 日志: `[ERROR] [database] QueuePool limit of size 5 overflow 5 reached`
- 原因: 长时间运行的查询占用连接未释放
- 解决: 检查慢查询 `SELECT * FROM pg_stat_activity WHERE state = 'active'`
- 预防: statement_timeout = 5s，pool_pre_ping = True
- 首次发现: 待观察
- 出现频率: 待观察

## 磁盘空间不足
- 症状: 写入失败，服务异常
- 原因: fund_daily 数据增长 + 日志文件累积
- 解决: weekly_cleanup.sh 清理日志 + 旧分区数据
- 预防: 40GB ESSD + 监控告警（>80% 触发）
- 首次发现: 待观察
- 出现频率: 待观察
