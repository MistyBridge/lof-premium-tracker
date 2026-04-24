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
        } catch (error) {
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
            this.funds = api.filterSafeFunds(result.data);
            this.applyFilters();
            this.renderTable();
            this.updatePaginationInfo();
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
        if (!tbody) return;
        if (this.filteredFunds.length === 0) {
            tbody.innerHTML = `<tr><td colspan="9" class="empty-state"><i class="icon">📭</i><p>暂无数据</p></td></tr>`;
            return;
        }
        const start = (this.currentPage - 1) * this.pageSize;
        const end = start + this.pageSize;
        const pageData = this.filteredFunds.slice(start, end);
        tbody.innerHTML = pageData.map(fund => this.createFundRow(fund)).join('');
    }

    createFundRow(fund) {
        const premiumClass = fund.premium_rate > 0 ? 'premium-positive' : fund.premium_rate < 0 ? 'premium-negative' : 'premium-zero';
        const premiumSign = fund.premium_rate > 0 ? '+' : '';
        const changeClass = fund.change_pct >= 0 ? 'up' : 'down';
        const changeSign = fund.change_pct >= 0 ? '+' : '';
        const navType = fund.is_formal_nav ? '正式' : '估算';
        const amountText = fund.amount_w >= 10000 ? (fund.amount_w / 10000).toFixed(2) + '亿' : fund.amount_w.toFixed(2) + '万';
        return `<tr class="fund-row" data-code="${fund.code}">
            <td class="col-code">${fund.code}</td>
            <td class="col-name" title="${fund.name}">${this.truncateName(fund.name)}</td>
            <td class="col-price">${fund.price.toFixed(3)}</td>
            <td class="col-nav">${fund.nav.toFixed(3)}<span class="nav-badge">${navType}</span></td>
            <td class="col-change ${changeClass}">${changeSign}${fund.change_pct.toFixed(2)}%</td>
            <td class="col-premium ${premiumClass}">${premiumSign}${fund.premium_rate.toFixed(2)}%</td>
            <td class="col-amount">${amountText}</td>
            <td class="col-status"><span class="status-badge ${fund.premium_status || ''}">${fund.premium_status || '未知'}</span></td>
            <td class="col-time">${fund.nav_date || '-'}</td>
        </tr>`;
    }

    renderRankings(funds) {
        const container = document.getElementById('rankingsContainer');
        if (!container) return;
        container.innerHTML = funds.slice(0, 5).map((fund, index) => `
            <div class="ranking-item">
                <span class="rank-num rank-${index + 1}">${index + 1}</span>
                <div class="rank-info">
                    <span class="rank-code">${fund.code}</span>
                    <span class="rank-name">${this.truncateName(fund.name, 10)}</span>
                </div>
                <span class="rank-premium premium-high">+${fund.premium_rate.toFixed(2)}%</span>
            </div>
        `).join('');
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
        const refreshBtn = document.getElementById('refreshBtn');
        if (refreshBtn) refreshBtn.addEventListener('click', () => this.handleRefresh());
        const retryBtn = document.getElementById('retryBtn');
        if (retryBtn) retryBtn.addEventListener('click', () => this.init());
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

    async handleRefresh() {
        const btn = document.getElementById('refreshBtn');
        if (btn) { btn.disabled = true; btn.textContent = '刷新中...'; }
        try {
            this.updateStatus('正在刷新数据...');
            await api.refreshData();
            setTimeout(async () => {
                await this.loadFunds();
                await this.loadRankings();
                this.updateStatus('刷新成功');
            }, 5000);
        } catch (error) {
            this.showToast('刷新失败: ' + error.message);
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = '🔄 刷新'; }
        }
    }

    startAutoRefresh() {
        this.stopAutoRefresh();
        this.refreshTimer = setInterval(async () => {
            if (!this.isLoading) {
                try {
                    await this.loadRankings();
                    this.updateStatus('自动刷新成功');
                } catch (error) {
                    console.warn('自动刷新失败:', error.message);
                }
            }
        }, CONFIG.REFRESH_INTERVAL);
    }

    stopAutoRefresh() {
        if (this.refreshTimer) { clearInterval(this.refreshTimer); this.refreshTimer = null; }
    }

    updateStatus(message) {
        const el = document.getElementById('statusText');
        if (el) el.textContent = message;
    }

    updateStatusInfo(data) {
        const els = ['cacheCount', 'lastFetch', 'refreshInterval', 'totalFunds'];
        if (document.getElementById('cacheCount')) document.getElementById('cacheCount').textContent = data.cache_count;
        if (document.getElementById('lastFetch')) document.getElementById('lastFetch').textContent = this.formatTime(data.last_fetch);
        if (document.getElementById('refreshInterval')) document.getElementById('refreshInterval').textContent = (data.refresh_interval_sec || 300) / 60 + '分钟';
        if (document.getElementById('totalFunds')) document.getElementById('totalFunds').textContent = this.funds.length;
    }

    updatePaginationInfo() {
        if (document.getElementById('totalRecords')) document.getElementById('totalRecords').textContent = this.filteredFunds.length;
        if (document.getElementById('shownRecords')) {
            const start = (this.currentPage - 1) * this.pageSize + 1;
            const end = Math.min(this.currentPage * this.pageSize, this.filteredFunds.length);
            document.getElementById('shownRecords').textContent = `${start}-${end}`;
        }
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

    showToast(message) { alert(message); }

    formatTime(isoString) {
        if (!isoString) return '-';
        return new Date(isoString).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
    }
}

document.addEventListener('DOMContentLoaded', () => { window.lofMonitor = new LofFundMonitor(); });
