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
                if (response.status === 429) {
                    var rateErr = new Error('请求过于频繁，请稍后重试');
                    rateErr.errorType = 'rate_limit';
                    rateErr.statusCode = 429;
                    throw rateErr;
                }
                var err = new Error(response.status >= 500 ? '服务器繁忙，请稍后重试' : '请求失败 (' + response.status + ')');
                err.errorType = response.status >= 500 ? 'server' : 'client';
                err.statusCode = response.status;
                throw err;
            }

            const result = await response.json();

            if (result.code !== 0) {
                var appErr = new Error(result.message || '请求失败');
                appErr.errorType = 'api';
                appErr.apiCode = result.code;
                throw appErr;
            }

            return result;
        } catch (error) {
            clearTimeout(timeout);
            if (error.errorType) throw error;
            if (error.name === 'AbortError') {
                var toErr = new Error('请求超时，请检查网络连接');
                toErr.errorType = 'timeout';
                throw toErr;
            }
            if (error.name === 'TypeError' && error.message.indexOf('fetch') >= 0) {
                var netErr = new Error('网络连接失败，请检查网络');
                netErr.errorType = 'network';
                throw netErr;
            }
            var unkErr = new Error(error.message || '未知错误');
            unkErr.errorType = 'unknown';
            throw unkErr;
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
    async getFunds(page, pageSize, showSuspended = false, showUnpurchasable = false) {
        page = page || 1;
        pageSize = pageSize || this.config.DEFAULT_PAGE_SIZE;
        return this.requestWithRetry(`/api/funds?page=${page}&page_size=${pageSize}&suspended=${showSuspended ? '1' : '0'}&unpurchasable=${showUnpurchasable ? '1' : '0'}`);
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
