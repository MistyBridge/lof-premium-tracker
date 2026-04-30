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
        this.bindEvents();
        this.init();
    }

    async init() {
        this.showLoading(true);
        this.updateStatus('正在连接服务...');
        try {
            await this.checkHealth();
            await this.loadRankings();
            await this.loadFunds();
            this.startAutoRefresh();
            this.showError(false);
            this.updateStatus('数据已加载');
        } catch (error) {
            this.updateStatus('连接失败');
            this.showError(true, error.message);
        } finally {
            this.showLoading(false);
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
            // 过滤停牌和无溢价率数据的基金
            this.funds = result.data.filter(fund => {
                if (fund.is_suspended) return false;
                if (fund.premium_rate === null || fund.premium_rate === undefined) return false;
                if (fund.premium_rate > 50 || fund.premium_rate < -30) return false;
                return true;
            });
            this.applyFilters();
            this.renderTable();
            this.updatePaginationInfo();
            // 用 API 返回的原始总数更新基金总数
            if (document.getElementById('totalFunds')) document.getElementById('totalFunds').textContent = totalFromApi;
        } catch (error) {
            throw new Error(`基金列表加载失败: ${error.message}`);
        } finally {
            this.isLoading = false;
        }
    }

    applyFilters() {
        let filtered = [...this.funds];
        if (this.searchKeyword) {
            const keyword = this.searchKeyword.toLowerCase();
            filtered = filtered.filter(fund => 
                fund.code.toLowerCase().includes(keyword) ||
                fund.name.toLowerCase().includes(keyword)
            );
        }
        filtered.sort((a, b) => {
            let valA = a[this.sortField] ?? 0;
            let valB = b[this.sortField] ?? 0;
            return this.sortOrder === 'asc' ? valA - valB : valB - valA;
        });
        this.filteredFunds = filtered;
    }

    renderTable() {
        const tbody = document.getElementById('fundTableBody');
        const cardList = document.getElementById('mobileCardList');
        if (this.filteredFunds.length === 0) {
            if (tbody) tbody.innerHTML = `<tr><td colspan="9" class="empty-state"><i class="icon">📭</i><p>暂无数据</p></td></tr>`;
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
                    <div class="rank-info">
                        <span class="rank-code">${fund.code}</span>
                        <span class="rank-name">${this.truncateName(fund.name, 10)}</span>
                    </div>
                    <span class="rank-premium premium-high">${fund.premium_rate != null ? '+' + fund.premium_rate.toFixed(2) + '%' : '--'}</span>
                </div>
            `).join('');
        }
        // 移动端排行条
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

    createMobileCard(fund) {
        const pr = fund.premium_rate;
        const premiumClass = pr > 0 ? 'mc-pos' : pr < 0 ? 'mc-neg' : 'mc-zero';
        const premiumSign = pr > 0 ? '+' : '';
        const premiumText = pr !== null && pr !== undefined ? premiumSign + pr.toFixed(2) + '%' : '--';
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
                    this.updateStatus('自动刷新成功');
                } catch (error) {
                    console.warn('自动刷新失败:', error.message);
                    this.updateStatus('自动刷新失败');
                }
            }
        }, window.LOF_CONFIG?.REFRESH_INTERVAL || 90000);
    }

    stopAutoRefresh() {
        if (this.refreshTimer) { clearInterval(this.refreshTimer); this.refreshTimer = null; }
    }

    updateStatus(message) {
        const el = document.getElementById('statusText');
        if (el) el.textContent = message;
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
        if (prevBtn) prevBtn.disabled = this.currentPage <= 1;
        if (nextBtn) nextBtn.disabled = this.currentPage >= totalPages;
    }

    changePage(delta) {
        const totalPages = Math.max(1, Math.ceil(this.filteredFunds.length / this.pageSize));
        const newPage = this.currentPage + delta;
        if (newPage < 1 || newPage > totalPages) return;
        this.currentPage = newPage;
        this.renderTable();
        this.updatePaginationInfo();
        // 滚动到表格顶部
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
        if (btn) { btn.disabled = true; btn.querySelector('.taiji').classList.add('spinning'); }
        try {
            await this.checkHealth();
            await this.loadRankings();
            await this.loadFunds();
            this.updateStatus('刷新成功');
        } catch (error) {
            this.updateStatus('刷新失败');
            this.showToast('刷新失败: ' + error.message);
        } finally {
            if (btn) { btn.disabled = false; btn.querySelector('.taiji').classList.remove('spinning'); }
        }
    }

    showToast(message) { alert(message); }

    formatTime(isoString) {
        if (!isoString) return '-';
        return new Date(isoString).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
    }
}

document.addEventListener('DOMContentLoaded', () => { window.lofMonitor = new LofFundMonitor(); });
