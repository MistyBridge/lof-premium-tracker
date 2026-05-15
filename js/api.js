/**
 * LOF基金监控系统 - API服务封装
 * 严格对接后端 API
 */

class LofApiService {
    constructor() {
        // 使用全局配置
        this.config = window.LOF_CONFIG || { 
            API_BASE_URL: 'http://localhost:5000',
            REQUEST_TIMEOUT: 30000,
            RETRY_COUNT: 3,
            RETRY_INTERVAL: 3000,
            DEFAULT_PAGE_SIZE: 50,
            RANKING_LIMIT: 20,
            PREMIUM_THRESHOLD: 50,
            DISCOUNT_THRESHOLD: -30
        };
    }

    get baseUrl() {
        return this.config.API_BASE_URL;
    }

    /**
     * 通用请求方法
     */
    async request(path, options = {}) {
        const url = `${this.baseUrl}${path}`;
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), this.config.REQUEST_TIMEOUT);

        try {
            const response = await fetch(url, {
                ...options,
                signal: controller.signal,
                mode: 'cors',
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
    async requestWithRetry(path, options = {}, retries) {
        retries = retries !== undefined ? retries : this.config.RETRY_COUNT;
        try {
            return await this.request(path, options);
        } catch (error) {
            if (retries > 0) {
                console.warn(`[LOF API] 请求失败，${this.config.RETRY_INTERVAL/1000}秒后重试(剩余${retries}次):`, error.message);
                await new Promise(resolve => setTimeout(resolve, this.config.RETRY_INTERVAL));
                return this.requestWithRetry(path, options, retries - 1);
            }
            throw error;
        }
    }

    // 1. 健康检查
    async getHealth() {
        return this.requestWithRetry('/health');
    }

    // 2. 基金列表
    async getFunds(page, pageSize) {
        page = page || 1;
        pageSize = pageSize || this.config.DEFAULT_PAGE_SIZE;
        return this.requestWithRetry(`/api/funds?page=${page}&page_size=${pageSize}`);
    }

    // 3. 基金详情
    async getFundDetail(code) {
        return this.requestWithRetry(`/api/funds/${code}`);
    }

    // 4. 排行榜
    async getRankings(type, limit) {
        type = type || 'premium';
        limit = limit || this.config.RANKING_LIMIT;
        return this.requestWithRetry(`/api/rankings?type=${type}&limit=${limit}`);
    }


    // 6. 基金图表数据（支持 7/30/365 日）
    async getFundChart(code, days = 7) {
        return this.requestWithRetry(`/api/funds/${code}/chart?days=${days}`);
    }

    // 5. 刷新数据
    async refreshData() {
        return this.requestWithRetry('/refresh', { method: 'POST' });
    }

    // 过滤异常数据
    filterSafeFunds(funds) {
        const cfg = this.config;
        return funds.filter(fund => {
            if (fund.premium_rate === null || fund.premium_rate === undefined) return false;
            return fund.premium_rate < cfg.PREMIUM_THRESHOLD 
                && fund.premium_rate > cfg.DISCOUNT_THRESHOLD;
        });
    }
}

// 全局API实例
window.api = new LofApiService();
console.log('[LOF API] 初始化完成，API地址:', window.api.baseUrl);
