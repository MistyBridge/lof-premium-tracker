/**
 * LOF基金监控系统 - 配置文件
 * 支持多种部署方式的环境配置
 */

(function() {
    // 自动检测当前部署环境
    const hostname = window.location.hostname;
    
    // 本地开发环境
    const isLocalDev = hostname === 'localhost' || hostname === '127.0.0.1';
    
    // 默认配置
    //
    // 生产环境改为**直连源站**（api.jinkuaicha.com → 阿里云 ECS）。
    //
    // 不要改回 ''（同源相对路径）。那条路是"浏览器 → CF Pages → Pages Function
    // → CF 再转一手 → 源站"，实测代价：
    //   · 绕经 Cloudflare 美西边缘（CF-RAY 显示 LAX/SJC）两趟，而不是就近直连；
    //   · 切换板块要 6.9~25s，直连只要 1.2~4.0s（见 scripts/perf_board_switch.mjs）；
    //   · 而且 CF 边缘到源站的 TLS 走不通（实测 525），这条路现在已经不可用。
    // 直连需要源站给 jinkuaicha.com 开 CORS，已在 /opt/jinkuaicha/backend-v2/.env
    // 的 CORS_ORIGINS 里配置。
    //
    // 可通过URL参数临时切换：?api=https://xxx
    const DEFAULT_CONFIG = {
        // 后端API地址
        API_BASE_URL: isLocalDev
            ? 'http://localhost:8000'          // 本地：v2 后端端口
            : 'https://api.jinkuaicha.com',    // 生产：直连阿里云源站
        
        // 数据刷新间隔（毫秒）- 前端1.5分钟轮询
        REFRESH_INTERVAL: 90 * 1000,

        // 分页配置
        DEFAULT_PAGE_SIZE: 600,     // 一次拉全量（LOF 全集约 410 只，装得下）
        // ETF 全集约 1700 只，600 条装不下：前端是"一次拉全量 + 本地排序/筛选"
        // 的架构，拉不全就会出现静默漏基金、且"溢价率降序"只在拉回来的那
        // 一部分里排序（榜单失真）。后端 size 上限已放到 3000。
        ETF_PAGE_SIZE: 2400,
        RANKING_LIMIT: 20,

        // 溢价率异常值过滤阈值
        PREMIUM_THRESHOLD: 50,      // 溢价率>50%视为异常
        DISCOUNT_THRESHOLD: -30,   // 折价率<-30%视为异常

        // 数字格式化
        PRICE_DECIMALS: 3,
        PREMIUM_DECIMALS: 2,

        // 请求配置
        REQUEST_TIMEOUT: 30000,    // 30秒超时
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
    console.log('[LOF配置] API地址:', CONFIG.API_BASE_URL, '| 环境:', isLocalDev ? '本地开发' : '生产部署(直连源站)');
})();
