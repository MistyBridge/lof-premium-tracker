/**
 * LOF基金监控系统 - 配置文件
 * 支持多种部署方式的环境配置
 */

(function() {
    // 自动检测当前部署环境
    const hostname = window.location.hostname;
    
    // 本地开发环境
    const isLocalDev = hostname === 'localhost' || hostname === '127.0.0.1';
    
    // 默认配置 - 使用已部署的Railway后端
    // 如需更换后端地址，可通过URL参数：index.html?api=https://your-api.com
    const DEFAULT_CONFIG = {
        // 后端API地址 - Railway部署（正确域名：lof-premium-tracker）
        API_BASE_URL: isLocalDev 
            ? 'http://localhost:5000' 
            : 'https://lof-premium-tracker-production.up.railway.app',
        
        // 数据刷新间隔（毫秒）- 前端1.5分钟轮询
        REFRESH_INTERVAL: 90 * 1000,

        // 分页配置
        DEFAULT_PAGE_SIZE: 600,     // 一次拉全量
        RANKING_LIMIT: 20,

        // 溢价率异常值过滤阈值
        PREMIUM_THRESHOLD: 50,      // 溢价率>50%视为异常
        DISCOUNT_THRESHOLD: -30,   // 折价率<-30%视为异常

        // 数字格式化
        PRICE_DECIMALS: 3,
        PREMIUM_DECIMALS: 2,

        // 请求配置（加大超时和重试，应对Railway冷启动）
        REQUEST_TIMEOUT: 30000,    // 30秒超时（Railway冷启动可能需要20秒+）
        RETRY_COUNT: 3,            // 重试3次
        RETRY_INTERVAL: 3000,     // 重试间隔3秒
    };

    // 从URL参数读取自定义配置（优先级最高）
    function getUrlParams() {
        const params = {};
        const urlParams = new URLSearchParams(window.location.search);
        const apiUrl = urlParams.get('api');
        if (apiUrl) {
            params.API_BASE_URL = apiUrl;
        }
        return params;
    }

    // 合并配置
    const urlParams = getUrlParams();
    const CONFIG = { ...DEFAULT_CONFIG, ...urlParams };

    // 导出全局配置
    window.LOF_CONFIG = CONFIG;
    
    // 调试信息
    console.log('[LOF配置] API地址:', CONFIG.API_BASE_URL, '| 环境:', isLocalDev ? '本地开发' : '生产部署');
})();
