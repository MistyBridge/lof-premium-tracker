/**
 * LOF基金监控系统 - API服务封装
 * 严格对接后端 API 文档（lof-fund-service/API文档-前端对接.md）
 */

class LofApiService {
    constructor() {
        this.baseUrl = CONFIG.API_BASE_URL;
    }

    /**
     * 通用请求方法
     */
    async request(path, options = {}) {
        const url = `${this.baseUrl}${path}`;
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), CONFIG.REQUEST_TIMEOUT);

        try {
            const response = await fetch(url, {
                ...options,
                signal: controller.signal,
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                }
            });

            clearTimeout(timeout);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();

            // 后端成功码为 0
            if (result.code !== 0) {
                throw new Error(result.message || '请求失败');
            }

            return result;
        } catch (error) {
            clearTimeout(timeout);
            if (error.name === 'AbortError') {
                throw new Error('请求超时，请检查网络连接');
            }
            throw error;
        }
    }

    /**
     * 带重试的请求
     */
    async requestWithRetry(path, options = {}, retries = CONFIG.RETRY_COUNT) {
        try {
            return await this.request(path, options);
        } catch (error) {
            if (retries > 0) {
                await new Promise(resolve => setTimeout(resolve, CONFIG.RETRY_INTERVAL));
                return this.requestWithRetry(path, options, retries - 1);
            }
            throw error;
        }
    }

    /**
     * 1. 健康检查
     * GET /health
     * 返回服务状态和缓存数据量
     */
    async getHealth() {
        return this.requestWithRetry('/health');
    }

    /**
     * 2. 获取基金列表（分页）
     * GET /api/funds?page=1&page_size=50
     */
    async getFunds(page = 1, pageSize = CONFIG.DEFAULT_PAGE_SIZE) {
        return this.requestWithRetry(`/api/funds?page=${page}&page_size=${pageSize}`);
    }

    /**
     * 3. 获取单只基金详情
     * GET /api/funds/{code}
     */
    async getFundDetail(code) {
        return this.requestWithRetry(`/api/funds/${code}`);
    }

    /**
     * 4. 获取溢价率排行榜
     * GET /api/rankings?type=premium&limit=20
     * type: 'premium'=溢价排行, 'discount'=折价排行
     */
    async getRankings(type = 'premium', limit = CONFIG.RANKING_LIMIT) {
        return this.requestWithRetry(`/api/rankings?type=${type}&limit=${limit}`);
    }

    /**
     * 5. 强制刷新数据（慎用）
     * POST /refresh
     * 首次加载约需30-40秒
     */
    async refreshData() {
        return this.requestWithRetry('/refresh', { method: 'POST' });
    }

    /**
     * 过滤异常基金数据
     * 溢价率 > 50% 或 < -30% 视为异常（停牌基金价格固定1.0等）
     */
    filterSafeFunds(funds) {
        return funds.filter(fund => {
            if (fund.premium_rate === null || fund.premium_rate === undefined) return false;
            return fund.premium_rate < CONFIG.PREMIUM_THRESHOLD 
                && fund.premium_rate > CONFIG.DISCOUNT_THRESHOLD;
        });
    }
}

// 全局API实例
const api = new LofApiService();
