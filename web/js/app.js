/**
 * LOF基金监控系统 - 主应用逻辑
 */

class LofFundMonitor {
    constructor() {
        this.funds = [];
        this.filteredFunds = [];
        this.currentPage = 1;
        this.pageSize = 50;
        this.sortField = 'premium_rate';
        this.sortOrder = 'desc';
        this.searchKeyword = '';
        this.refreshTimer = null;
        this.searchTimeout = null;
        this.isLoading = false;
        this.threshold = 0;
        this.avgThreshold = 0;
        this.minAmount = 0;
        this.bindEvents();
        this.init();
    }

    async init() {
        this.showLoading(true);
        this.updateStatus('正在连接服务...');
        let retries = 0;
        const maxRetries = 5;
        const retryDelay = 8000; // 8秒重试间隔（Railway冷启动需要时间）
        while (retries < maxRetries) {
            try {
                this.updateStatus(retries === 0 ? '正在连接服务...' : `连接失败，${retryDelay/1000}秒后重试(${retries}/${maxRetries})...`);
                const healthResult = await this.checkHealth();
                const data = healthResult.data;
                // data_ready 字段可能不存在（旧版后端兼容），用 cache_count > 0 兜底
                const isReady = data.data_ready !== undefined ? data.data_ready : (data.cache_count > 0);
                if (!isReady) {
                    throw new Error('数据未就绪，后端正在初始化中，请稍后重试');
                }
                await this.loadRankings();
                await this.loadFunds();
                this.startAutoRefresh();
                this.showError(false);
                this.showLoading(false);
                this.updateStatus('');
                return; // 成功则退出
            } catch (error) {
                retries++;
                console.error(`[LOF] 初始化失败(${retries}/${maxRetries}):`, error.message);
                if (retries < maxRetries) {
                    this.updateStatus(`服务初始化中，${retryDelay/1000}秒后重试(${retries}/${maxRetries})...`);
                    await new Promise(r => setTimeout(r, retryDelay));
                } else {
                    this.updateStatus('连接失败，请检查网络后刷新页面');
                    this.showError(true, '无法连接到数据服务：' + error.message + '\n\n可能原因：\n1. 服务正在冷启动，请等待1分钟后刷新\n2. 网络不稳定，请稍后重试');
                    this.showLoading(false);
                }
            }
        }
    }

    async checkHealth() {
        try {
            const result = await api.getHealth();
            const data = result.data;
            this.updateStatusInfo(data);
            return result;
        } catch (error) {
            throw new Error(`服务连接失败: ${error.message}`);
        }
    }

    async loadRankings() {
        try {
            const result = await api.getRankings('premium', 20);
            this.renderRankings(result.data);
        } catch (error) {
            console.warn('排行榜加载失败:', error.message);
        }
    }

    async loadFunds() {
        this.isLoading = true;
        try {
            const result = await api.getFunds(1, 600);
            // 保存原始数据总数（过滤前）
            const totalFromApi = result.data.length;
            // 过滤停牌和无溢价率数据的基金（不再过滤极端溢价率，全部显示）
            this.funds = result.data.filter(fund => {
                if (fund.is_suspended) return false;
                if (fund.premium_rate === null || fund.premium_rate === undefined) return false;
                return true;
            });
            this.applyFilters();
            this.renderTable();
            this.renderDiscountRankings();
            this.updatePaginationInfo();
            // 用 API 返回的原始总数更新基金总数
            if (document.getElementById('totalFunds')) document.getElementById('totalFunds').textContent = totalFromApi;
            // Check if data is from history (market closed)
            const firstFund = result.data[0];
            if (firstFund && firstFund.data_date) {
                this.updateStatus('');
            }
        } catch (error) {
            throw new Error(`基金列表加载失败: ${error.message}`);
        } finally {
            this.isLoading = false;
        }
        // Show empty only if loadFunds succeeded but returned 0 items
        if (this.funds.length === 0) {
            this.updateStatus('');
        }
    }

    // ===== 三日平均溢价率（从后端API获取，字段 avg_premium_3d）=====
    getAvgPremium3d(code) {
        // 从 this.funds 中查找
        const fund = this.funds.find(f => f.code === code);
        return fund?.avg_premium_3d ?? null;
    }

    applyFilters() {
        let filtered = [...this.funds];
        // 搜索关键词筛选
        if (this.searchKeyword) {
            const keyword = this.searchKeyword.toLowerCase();
            filtered = filtered.filter(fund => 
                fund.code.toLowerCase().includes(keyword) ||
                fund.name.toLowerCase().includes(keyword)
            );
        }
        // 溢价率/折价率绝对值阈值筛选
        if (this.threshold > 0) {
            filtered = filtered.filter(fund => {
                const absRate = Math.abs(fund.premium_rate ?? 0);
                return absRate >= this.threshold;
            });
        }
        // 最小成交额阈值筛选
        if (this.minAmount > 0) {
            filtered = filtered.filter(fund => {
                const amountWan = (fund.amount ?? 0) / 10000;
                return amountWan >= this.minAmount;
            });
        }
        // 三日平均溢价率绝对值阈值筛选
        if (this.avgThreshold > 0) {
            filtered = filtered.filter(fund => {
                const avg = this.getAvgPremium3d(fund.code);
                return avg !== null && Math.abs(avg) >= this.avgThreshold;
            });
        }
        filtered.sort((a, b) => {
            let valA, valB;
            if (this.sortField === 'amount_w') {
                valA = (a.amount ?? 0) / 10000;
                valB = (b.amount ?? 0) / 10000;
            } else {
                valA = a[this.sortField] ?? 0;
                valB = b[this.sortField] ?? 0;
            }
            return this.sortOrder === 'asc' ? valA - valB : valB - valA;
        });
        this.filteredFunds = filtered;
    }

    renderTable() {
        const tbody = document.getElementById('fundTableBody');
        const cardList = document.getElementById('mobileCardList');
        if (this.filteredFunds.length === 0) {
            if (tbody) tbody.innerHTML = `<tr><td colspan="10" class="empty-state"><i class="icon">📭</i><p>暂无数据</p></td></tr>`;
            if (cardList) cardList.innerHTML = `<div class="mobile-empty"><i class="icon">📭</i><p>暂无数据</p></div>`;
            return;
        }
        const start = (this.currentPage - 1) * this.pageSize;
        const end = start + this.pageSize;
        const pageData = this.filteredFunds.slice(start, end);
        if (tbody) tbody.innerHTML = pageData.map(fund => this.createFundRow(fund)).join('');
        if (cardList) cardList.innerHTML = pageData.map(fund => this.createMobileCard(fund)).join('');
    }

    createFundRow(fund) {
        const pr = fund.premium_rate;
        const premiumClass = pr > 0 ? 'premium-positive' : pr < 0 ? 'premium-negative' : 'premium-zero';
        const premiumSign = pr > 0 ? '+' : '';
        const premiumText = pr !== null && pr !== undefined ? premiumSign + pr.toFixed(2) + '%' : '--';
        // 三日平均溢价率
        const avg3d = fund.avg_premium_3d;
        const avgPremiumClass = avg3d > 0 ? 'premium-positive' : avg3d < 0 ? 'premium-negative' : 'premium-zero';
        const avgPremiumSign = avg3d > 0 ? '+' : '';
        const avgPremiumText = avg3d !== null && avg3d !== undefined ? avgPremiumSign + avg3d.toFixed(2) + '%' : '--';
        const changeClass = fund.change_pct >= 0 ? 'up' : 'down';
        const changeSign = fund.change_pct >= 0 ? '+' : '';
        const changeText = fund.change_pct !== null && fund.change_pct !== undefined ? changeSign + fund.change_pct.toFixed(2) + '%' : '--';
        const navType = fund.is_formal_nav ? '正式' : '估算';
        const navText = fund.nav !== null && fund.nav !== undefined ? fund.nav.toFixed(3) : '--';
        const priceText = fund.price !== null && fund.price !== undefined ? fund.price.toFixed(3) : '--';
        // amount 字段为元，转为万元/亿元显示
        let amountText = '--';
        if (fund.amount !== null && fund.amount !== undefined) {
            const amountWan = fund.amount / 10000;
            amountText = amountWan >= 10000 ? (amountWan / 10000).toFixed(2) + '亿' : amountWan.toFixed(2) + '万';
        }
        return `<tr class="fund-row" data-code="${fund.code}">
            <td class="col-code">${fund.code}</td>
            <td class="col-name" title="${fund.name}">${this.truncateName(fund.name)}</td>
            <td class="col-price">${priceText}</td>
            <td class="col-nav">${navText}${fund.nav ? '<span class="nav-badge">' + navType + '</span>' : ''}</td>
            <td class="col-change ${changeClass}">${changeText}</td>
            <td class="col-premium ${premiumClass}">${premiumText}</td>
            <td class="col-avg-premium ${avgPremiumClass}">${avgPremiumText}</td>
            <td class="col-amount">${amountText}</td>
            <td class="col-status"><span class="status-badge ${fund.premium_status || ''}">${fund.premium_status || '未知'}</span></td>
            <td class="col-time">${fund.nav_date || '-'}</td>
        </tr>`;
    }

    renderRankings(funds) {
        const container = document.getElementById('rankingsContainer');
        if (container) {
            container.innerHTML = funds.slice(0, 5).map((fund, index) => `
                <div class="ranking-item">
                    <span class="rank-num rank-${index + 1}">${index + 1}</span>
                    <div class="rank-card">
                        <span class="rank-code">${fund.code}</span>
                        <span class="rank-premium premium-high">${fund.premium_rate != null ? '+' + fund.premium_rate.toFixed(2) + '%' : '--'}</span>
                    </div>
                </div>
            `).join('');
        }
        // 移动端溢价排行条
        const mobileScroll = document.getElementById('mobileRankingScroll');
        if (mobileScroll) {
            mobileScroll.innerHTML = funds.slice(0, 10).map(fund => `
                <div class="strip-item">
                    <span class="si-code">${fund.code}</span>
                    <span class="si-rate">${fund.premium_rate != null ? '+' + fund.premium_rate.toFixed(2) + '%' : '--'}</span>
                </div>
            `).join('');
        }
    }

    renderDiscountRankings() {
        if (!this.funds.length) return;
        const sorted = [...this.funds].sort((a, b) => (a.premium_rate ?? 0) - (b.premium_rate ?? 0));
        // PC端折价排行榜
        const discountContainer = document.getElementById('discountContainer');
        if (discountContainer) {
            discountContainer.innerHTML = sorted.slice(0, 5).map((fund, index) => `
                <div class="ranking-item">
                    <span class="rank-num rank-${index + 1}">${index + 1}</span>
                    <div class="rank-card">
                        <span class="rank-code">${fund.code}</span>
                        <span class="rank-premium rank-discount">${fund.premium_rate != null ? fund.premium_rate.toFixed(2) + '%' : '--'}</span>
                    </div>
                </div>
            `).join('');
        }
        // 移动端折价排行条
        const mobileDiscountScroll = document.getElementById('mobileDiscountScroll');
        if (mobileDiscountScroll) {
            mobileDiscountScroll.innerHTML = sorted.slice(0, 10).map(fund => `
                <div class="strip-item">
                    <span class="si-code">${fund.code}</span>
                    <span class="si-rate">${fund.premium_rate != null ? fund.premium_rate.toFixed(2) + '%' : '--'}</span>
                </div>
            `).join('');
        }
    }

    createMobileCard(fund) {
        const pr = fund.premium_rate;
        const premiumClass = pr > 0 ? 'mc-pos' : pr < 0 ? 'mc-neg' : 'mc-zero';
        const premiumSign = pr > 0 ? '+' : '';
        const premiumText = pr !== null && pr !== undefined ? premiumSign + pr.toFixed(2) + '%' : '--';
        const avg3d = fund.avg_premium_3d;
        const avgPremiumClass = avg3d > 0 ? 'mc-pos' : avg3d < 0 ? 'mc-neg' : 'mc-zero';
        const avgPremiumSign = avg3d > 0 ? '+' : '';
        const avgPremiumText = avg3d !== null && avg3d !== undefined ? avgPremiumSign + avg3d.toFixed(2) + '%' : '--';
        const changeSign = fund.change_pct >= 0 ? '+' : '';
        const changeClass = fund.change_pct >= 0 ? 'up' : 'down';
        const changeText = fund.change_pct !== null && fund.change_pct !== undefined ? changeSign + fund.change_pct.toFixed(2) + '%' : '--';
        const navType = fund.is_formal_nav ? '正式' : '估算';
        const navText = fund.nav !== null && fund.nav !== undefined ? navType + ' ' + fund.nav.toFixed(3) : '--';
        const priceText = fund.price !== null && fund.price !== undefined ? fund.price.toFixed(3) : '--';
        let amountText = '--';
        if (fund.amount !== null && fund.amount !== undefined) {
            const amountWan = fund.amount / 10000;
            amountText = amountWan >= 10000 ? (amountWan / 10000).toFixed(1) + '亿' : amountWan.toFixed(0) + '万';
        }
        const statusHtml = fund.premium_status ? `<span class="mc-status-badge status-badge ${fund.premium_status}">${fund.premium_status}</span>` : '';
        return `<div class="mobile-card" data-code="${fund.code}">
            <div class="mc-left"><span class="mc-code">${fund.code}</span><span class="mc-name">${fund.name}</span>${statusHtml}</div>
            <div class="mc-right"><span class="mc-premium ${premiumClass}">${premiumText}</span></div>
            <div class="mc-bottom">
                <span class="mb-item"><span class="mb-label">现价</span><span class="mb-val">${priceText}</span></span>
                <span class="mb-item"><span class="mb-label">净值</span><span class="mb-val">${navText}</span></span>
                <span class="mb-item"><span class="mb-label">涨跌</span><span class="mb-val ${changeClass}">${changeText}</span></span>
                <span class="mb-item"><span class="mb-label">三日均溢</span><span class="mb-val ${avgPremiumClass}">${avgPremiumText}</span></span>
                <span class="mb-item"><span class="mb-label">成交</span><span class="mb-val">${amountText}</span></span>
            </div>
        </div>`;
    }

    truncateName(name, maxLen = 12) {
        return name.length <= maxLen ? name : name.substring(0, maxLen) + '...';
    }

    bindEvents() {
        document.querySelectorAll('.sortable').forEach(th => {
            th.addEventListener('click', () => this.handleSort(th.dataset.field));
        });
        const searchInput = document.getElementById('searchInput');
        if (searchInput) searchInput.addEventListener('input', e => this.handleSearch(e.target.value));
        const retryBtn = document.getElementById('retryBtn');
        if (retryBtn) retryBtn.addEventListener('click', () => this.init());
        const manualRefreshBtn = document.getElementById('manualRefreshBtn');
        if (manualRefreshBtn) manualRefreshBtn.addEventListener('click', () => this.handleManualRefresh());
        // 设置弹窗事件
        const settingsBtn = document.getElementById('settingsBtn');
        const closeSettingsBtn = document.getElementById('closeSettingsBtn');
        const settingsModal = document.getElementById('settingsModal');
        const applySettingsBtn = document.getElementById('applySettingsBtn');
        const resetSettingsBtn = document.getElementById('resetSettingsBtn');
        if (settingsBtn) settingsBtn.addEventListener('click', () => this.openSettingsModal());
        if (closeSettingsBtn) closeSettingsBtn.addEventListener('click', () => this.closeSettingsModal());
        if (settingsModal) settingsModal.addEventListener('click', e => { if (e.target === settingsModal) this.closeSettingsModal(); });
        if (applySettingsBtn) applySettingsBtn.addEventListener('click', () => this.applySettings());
        if (resetSettingsBtn) resetSettingsBtn.addEventListener('click', () => this.resetSettings());
    }

    openSettingsModal() {
        const modal = document.getElementById('settingsModal');
        const thresholdInput = document.getElementById('thresholdInput');
        const avgThresholdInput = document.getElementById('avgThresholdInput');
        const minAmountInput = document.getElementById('minAmountInput');
        if (thresholdInput) thresholdInput.value = this.threshold || 0;
        if (avgThresholdInput) avgThresholdInput.value = this.avgThreshold || 0;
        if (minAmountInput) minAmountInput.value = this.minAmount || 0;
        if (modal) modal.style.display = 'flex';
    }

    closeSettingsModal() {
        const modal = document.getElementById('settingsModal');
        if (modal) modal.style.display = 'none';
    }

    applySettings() {
        const thresholdInput = document.getElementById('thresholdInput');
        const avgThresholdInput = document.getElementById('avgThresholdInput');
        const minAmountInput = document.getElementById('minAmountInput');
        this.threshold = parseFloat(thresholdInput?.value) || 0;
        this.avgThreshold = parseFloat(avgThresholdInput?.value) || 0;
        this.minAmount = parseFloat(minAmountInput?.value) || 0;
        this.currentPage = 1;
        this.applyFilters();
        this.renderTable();
        this.updatePaginationInfo();
        this.closeSettingsModal();
        const parts = [];
        if (this.threshold > 0) parts.push(`溢价率≥${this.threshold}%`);
        if (this.avgThreshold > 0) parts.push(`三日均溢≥${this.avgThreshold}%`);
        if (this.minAmount > 0) parts.push(`成交额≥${this.minAmount}万`);
        this.showToast(parts.length ? '筛选已应用：' + parts.join('，') : '筛选已重置');
    }

    resetSettings() {
        const thresholdInput = document.getElementById('thresholdInput');
        const avgThresholdInput = document.getElementById('avgThresholdInput');
        const minAmountInput = document.getElementById('minAmountInput');
        if (thresholdInput) thresholdInput.value = 0;
        if (avgThresholdInput) avgThresholdInput.value = 0;
        if (minAmountInput) minAmountInput.value = 0;
    }

    handleSort(field) {
        if (this.sortField === field) {
            this.sortOrder = this.sortOrder === 'asc' ? 'desc' : 'asc';
        } else {
            this.sortField = field;
            this.sortOrder = 'desc';
        }
        document.querySelectorAll('.sortable').forEach(th => {
            th.classList.remove('sort-asc', 'sort-desc');
            if (th.dataset.field === field) th.classList.add(`sort-${this.sortOrder}`);
        });
        this.applyFilters();
        this.renderTable();
    }

    handleSearch(keyword) {
        clearTimeout(this.searchTimeout);
        this.searchTimeout = setTimeout(() => {
            this.searchKeyword = keyword.trim();
            this.currentPage = 1;
            this.applyFilters();
            this.renderTable();
            this.updatePaginationInfo();
        }, 300);
    }


    startAutoRefresh() {
        this.stopAutoRefresh();
        this.refreshTimer = setInterval(async () => {
            if (!this.isLoading) {
                try {
                    await this.checkHealth();
                    await this.loadRankings();
                    await this.loadFunds();
                    this.showError(false);
                } catch (error) {
                    console.warn('自动刷新失败:', error.message);
                }
            }
        }, window.LOF_CONFIG?.REFRESH_INTERVAL || 90000);
    }

    stopAutoRefresh() {
        if (this.refreshTimer) { clearInterval(this.refreshTimer); this.refreshTimer = null; }
    }

    updateStatus(message) {
        // 状态文字现在只用于初始加载等场景，刷新状态由 refreshStatus 元素单独显示
        const el = document.getElementById('statusText');
        if (el && el.textContent !== message) {
            el.textContent = message;
        }
    }

    updateStatusInfo(data) {
        if (document.getElementById('cacheCount')) document.getElementById('cacheCount').textContent = data.cache_count ?? '-';
        if (document.getElementById('lastFetch')) document.getElementById('lastFetch').textContent = this.formatTime(data.last_fetch);
        if (document.getElementById('refreshInterval')) document.getElementById('refreshInterval').textContent = (data.refresh_interval_sec || 300) / 60 + '分钟';
        // 基金总数优先使用 API 返回的总数字段，否则用缓存数
        const total = data.total ?? data.cache_count ?? this.funds.length;
        if (document.getElementById('totalFunds')) document.getElementById('totalFunds').textContent = total;
    }

    updatePaginationInfo() {
        const totalPages = Math.max(1, Math.ceil(this.filteredFunds.length / this.pageSize));
        if (document.getElementById('totalRecords')) document.getElementById('totalRecords').textContent = this.filteredFunds.length;
        if (document.getElementById('shownRecords')) {
            const start = (this.currentPage - 1) * this.pageSize + 1;
            const end = Math.min(this.currentPage * this.pageSize, this.filteredFunds.length);
            document.getElementById('shownRecords').textContent = `${start}-${end}`;
        }
        if (document.getElementById('pageInfo')) {
            document.getElementById('pageInfo').textContent = `第 ${this.currentPage} 页 / 共 ${totalPages} 页`;
        }
        const prevBtn = document.getElementById('prevPageBtn');
        const nextBtn = document.getElementById('nextPageBtn');
        const firstBtn = document.getElementById('firstPageBtn');
        const lastBtn = document.getElementById('lastPageBtn');
        if (prevBtn) prevBtn.disabled = this.currentPage <= 1;
        if (nextBtn) nextBtn.disabled = this.currentPage >= totalPages;
        if (firstBtn) firstBtn.disabled = this.currentPage <= 1;
        if (lastBtn) lastBtn.disabled = this.currentPage >= totalPages;
    }

    changePage(delta) {
        const totalPages = Math.max(1, Math.ceil(this.filteredFunds.length / this.pageSize));
        const newPage = this.currentPage + delta;
        if (newPage < 1 || newPage > totalPages) return;
        this.currentPage = newPage;
        this.renderTable();
        this.updatePaginationInfo();
        document.querySelector('.table-container')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    goToPage(page) {
        const totalPages = Math.max(1, Math.ceil(this.filteredFunds.length / this.pageSize));
        if (page < 1 || page > totalPages) return;
        this.currentPage = page;
        this.renderTable();
        this.updatePaginationInfo();
        document.querySelector('.table-container')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    goToLastPage() {
        const totalPages = Math.max(1, Math.ceil(this.filteredFunds.length / this.pageSize));
        this.currentPage = totalPages;
        this.renderTable();
        this.updatePaginationInfo();
        document.querySelector('.table-container')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    changePageSize(size) {
        this.pageSize = parseInt(size);
        this.currentPage = 1;
        this.renderTable();
        this.updatePaginationInfo();
    }

    showLoading(show) {
        const el = document.getElementById('loader');
        if (el) el.style.display = show ? 'flex' : 'none';
    }

    showError(show, message = '') {
        const el = document.getElementById('errorContainer');
        if (el) el.style.display = show ? 'block' : 'none';
        if (document.getElementById('errorMessage') && message) document.getElementById('errorMessage').textContent = message;
    }

    async handleManualRefresh() {
        const btn = document.getElementById('manualRefreshBtn');
        const icon = btn?.querySelector('.refresh-icon');
        const statusEl = document.getElementById('refreshStatus');

        if (btn) { btn.disabled = true; }
        if (icon) {
            icon.classList.remove('bouncing');
            void icon.offsetWidth;
            icon.classList.add('bouncing');
        }

        // 显示“刷新中...”
        if (statusEl) {
            statusEl.textContent = '刷新中...';
            statusEl.classList.add('show');
        }

        try {
            await this.checkHealth();
            await this.loadRankings();
            await this.loadFunds();

            // 显示“✓”成功
            if (statusEl) {
                statusEl.textContent = '✓';
            }
        } catch (error) {
            if (statusEl) {
                statusEl.textContent = '✗';
            }
            this.showToast('刷新失败: ' + error.message);
        } finally {
            if (btn) { btn.disabled = false; }

            // 2秒后隐藏状态
            setTimeout(() => {
                if (statusEl) {
                    statusEl.classList.remove('show');
                }
            }, 2000);
        }
    }

    showToast(message) { alert(message); }

    formatTime(isoString) {
        if (!isoString) return '-';
        return new Date(isoString).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
    }
}

document.addEventListener('DOMContentLoaded', () => { window.lofMonitor = new LofFundMonitor(); });
