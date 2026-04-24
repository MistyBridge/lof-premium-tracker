/**
 * LOF基金监控系统 - 配置文件
 * 根据后端 API 文档（lof-fund-service/API文档-前端对接.md）配置
 */

const CONFIG = {
    // 后端API基础地址 - 部署后替换为实际服务器地址
    API_BASE_URL: 'http://localhost:5000',

    // 数据刷新间隔（毫秒）- 后端每5分钟自动刷新，前端1.5分钟轮询排行榜
    REFRESH_INTERVAL: 90 * 1000,

    // 分页配置
    DEFAULT_PAGE_SIZE: 600,     // 默认每页条数（一次拉全量）
    RANKING_LIMIT: 20,          // 排行榜条数

    // 溢价率异常值过滤阈值
    PREMIUM_THRESHOLD: 50,      // 溢价率超过50%视为异常
    DISCOUNT_THRESHOLD: -30,    // 折价率低于-30%视为异常

    // 数字格式化
    PRICE_DECIMALS: 3,          // 价格保留3位小数
    PREMIUM_DECIMALS: 2,        // 溢价率保留2位小数

    // 请求配置
    REQUEST_TIMEOUT: 15000,     // 请求超时（毫秒）
    RETRY_COUNT: 2,             // 失败重试次数
    RETRY_INTERVAL: 2000,       // 重试间隔（毫秒）
};
