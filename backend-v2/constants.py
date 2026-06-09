"""
业务常量集中定义
所有常量在此一处维护，代码中引用常量名，不写魔法数字。
"""

# === 数据校验阈值 ===
PREMIUM_RATE_WARN = 50          # 溢价率超50%标记警告
PREMIUM_RATE_MAX = 100          # 溢价率超100%标记异常
PRICE_CHANGE_WARN = 20          # 涨跌幅超20%标记警告
VOLUME_ANOMALY_RATIO = 500      # 成交额偏离20日均值>500%告警
PRICE_DEVIATION_WARN = 30       # 价格偏离20日均值>30%警告
NAV_DEVIATION_CRITICAL = 50     # 净值偏离>50%告警
NAV_JUMP_CRITICAL = 80          # 净值突变>80%告警
PARTIAL_DATA_THRESHOLD = 80     # 数据量<上次80%视为不完整

# === 采集参数 ===
FUNDINFO_BATCH_SIZE = 300       # fundf10 每批数量
FUNDINFO_BATCH_DELAY = 2.0      # fundf10 请求间隔(秒)
QDII_NAV_DELAY_HOURS = 3        # QDII 净值延迟小时数
PUSH2_RETRY_COUNT = 3           # push2 重试次数
PUSH2_RETRY_DELAY = 5           # push2 重试间隔(秒)
LSJZ_CONCURRENCY = 10           # lsjz 并发数(10并发)
LSJZ_INTERVAL = 0.2             # lsjz 请求间隔(秒)

# === 通用采集间隔 ===
FETCH_INTERVAL_MIN = 2.0        # 所有数据源最小请求间隔(秒)

# === 公式引擎 ===
FORMULA_MAX_NODES = 100         # 单公式 AST 节点上限
FORMULA_MAX_FUNDS = 200         # 批量求值基金上限
FORMULA_MAX_COUNT = 10          # 公式组公式数量上限
FORMULA_EVAL_TIMEOUT = 10       # 求值超时(秒)
FORMULA_LRU_SIZE = 256          # parse LRU 缓存大小

# === API ===
PAGE_SIZE_DEFAULT = 50          # 默认分页大小
PAGE_SIZE_MAX = 1500            # 最大分页大小（前端一次拉全量）
DAILY_QUERY_LIMIT_MAX = 1000    # 日线查询最大行数
BATCH_CODES_MAX = 50            # 批量查询最大代码数
BATCH_QUERY_CODES_MAX = 20      # 数据查询最大代码数
EXPORT_CODES_MAX = 1500         # 导出最大代码数

# === 预计收益（默认参数，与前端 v1 一致） ===
PROFIT_COMMISSION_RATE = 1.5    # 佣金费率: 万1.5 (commission_rate / 10000)
PROFIT_COMMISSION_MIN = 5.0     # 最低佣金(元)
PROFIT_MAX_CAPITAL = 1000.0     # 最大投入金额(元)
PROFIT_DEFAULT_REDEMPTION_FEE = 1.5  # 赎回费率默认值(%)，最短档

# === 缓存 TTL（秒） ===
CACHE_RT_TTL = 360              # rt:all 实时行情（需 > 采集间隔 300s，避免两次采集间 miss）
CACHE_NAV_TTL = 86400           # nav:all 净值(24小时，确保daily_save能读到)
CACHE_FEE_TTL = 3600            # fee:{code} 费率
CACHE_INFO_TTL = 86400          # info:{code} 基金基础信息
CACHE_KLINE_TTL = 86400         # kline 日线（次日凌晨过期）
CACHE_FORMULA_TTL = 60          # formula 公式缓存
CACHE_HIT_THRESHOLD = 80        # 部分数据防护阈值(%)
CACHE_STAMPEDE_LOCK_TTL = 3     # 缓存击穿锁 TTL(秒)
CACHE_STAMPEDE_WAIT_MAX = 2     # 缓存击穿最大等待(秒)

# === SSE ===
SSE_HEARTBEAT_INTERVAL = 30     # SSE 心跳间隔(秒)
SSE_MAX_CONNECTIONS = 200       # SSE 最大并发连接

# === Redis Stream ===
STREAM_KEY = "stream:events"
STREAM_GROUP = "pipeline_processor"
STREAM_CONSUMER = "worker-1"
STREAM_MAX_LEN = 10000          # Stream 最大长度（自动裁剪）
STREAM_BLOCK_MS = 2000          # 消费者阻塞等待(毫秒)
STREAM_READ_COUNT = 10          # 每次读取条数
STREAM_POISON_MAX = 3           # 毒消息最大重试次数

# === 调度器 ===
SCHED_REALTIME_INTERVAL = 300   # 实时行情采集间隔(秒)，交易时段每5分钟
SCHED_NAV_INTERVAL = 300        # 净值采集间隔(秒)
SCHED_DAILY_SAVE_HOUR = 23     # 日终入库时间（23:00）
SCHED_DAILY_SAVE_MINUTE = 30   # 日终入库分钟（23:30）
SCHED_QDII_RETRY_HOUR = 23     # QDII 净值补充时间
SCHED_INFO_HOUR = 20            # fundf10 信息采集时间
SCHED_CODE_SCAN_DAY = 0         # 代码扫描星期几（0=周一）
SCHED_CODE_SCAN_HOUR = 9        # 代码扫描时间
SCHED_CLEANUP_DAY = 6           # 周清理星期几（6=周日）
SCHED_CLEANUP_HOUR = 3          # 周清理时间

# === 告警 ===
ALERT_CONSECUTIVE_FAIL = 3      # 连续失败N次触发告警
ALERT_WEBHOOK_TIMEOUT = 10      # webhook超时(秒)
ALERT_COOLDOWN = 300            # 同一告警冷却时间(秒)

# === 任务队列 ===
TASK_FETCH_INFO = "fetch_info"
TASK_FETCH_FEE = "fetch_fee"
TASK_FETCH_REALTIME = "fetch_realtime"
TASK_FETCH_FUNDAMENTAL = "fetch_fundamental"
TASK_FETCH_HISTORICAL = "fetch_historical"
TASK_DAILY_SAVE = "daily_save"
TASK_CODE_SCAN = "code_scan"

# === 日期格式 ===
DATE_FORMAT = "%Y%m%d"          # Redis key 中的日期格式
DATE_FORMAT_DB = "%Y-%m-%d"     # 数据库日期格式

# === 公式引擎（用户公式） ===
USER_FORMULA_MAX = 50           # 每用户最大公式数
FORMULA_MAX_NAME_LEN = 100      # 公式名称最大长度
FORMULA_MAX_EXPR_LEN = 500      # 公式表达式最大长度