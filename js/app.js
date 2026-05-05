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
        // 筛选参数（从 localStorage 恢复或用默认值）
        this.threshold = parseFloat(localStorage.getItem('lof_threshold')) || 0;
        this.avgThreshold = parseFloat(localStorage.getItem('lof_avgThreshold')) || 0;
        this.minAmount = parseFloat(localStorage.getItem('lof_minAmount')) || 0;
        // 预计收益计算参数（从 localStorage 恢复或用默认值）
        this.commissionRate = parseFloat(localStorage.getItem('lof_commissionRate')) || 1.5;  // 万X
        this.commissionMin = parseFloat(localStorage.getItem('lof_commissionMin')) || 5;      // 元
        this.maxCapital = parseFloat(localStorage.getItem('lof_maxCapital')) || 1000;        // 元
        // 深色模式（只记录 dark 或 light，不跟随系统）
        this.darkMode = localStorage.getItem('lof_darkMode') || 'light';
        // 显示模式：premium=溢价模式（从高到低），discount=折价模式（从低到高）
        this.displayMode = localStorage.getItem('lof_displayMode') || 'premium';
        this.detailChart = null; // 详情图表实例
        this.bindEvents();
        this.applyDarkMode(false); // 不保存，仅应用
        this.applyDisplayMode(); // 应用显示模式按钮状态
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
                    // 更新 loader 文字提示重试进度
                    this.updateLoaderText(`连接中... (${retries}/${maxRetries})`);
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
            // 过滤停牌、无溢价率、暂停申购的基金
            this.funds = result.data.filter(fund => {
                if (fund.is_suspended) return false;
                if (fund.premium_rate === null || fund.premium_rate === undefined) return false;
                if (fund.can_purchase === false) return false;  // 暂停申购
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

    // ===== 预计收益计算 =====
    /**
     * 计算单只基金的预计套利收益
     * 溢价时：溢价套利（申购→场内卖出）
     *   收益率 = 溢价率 - 申购费率 - 卖出佣金率
     * 折价时：折价套利（场内买入→赎回）
     *   收益率 = |折价率| - 买入佣金率 - 赎回费率(最短档)
     * 实际投入 = min(用户最大资金量, 基金申购上限)
     * 实际佣金 = max(投入 × 佣金费率, 佣金最低收费)
     * 实际佣金率 = 实际佣金 / 投入
     * 预计收益额 = 投入 × 预计收益率
     */
    calcEstimatedProfit(fund, fixedCapital = null) {
        const premium = fund.premium_rate;
        if (premium === null || premium === undefined) return null;

        const nav = fund.nav;
        const price = fund.price;
        if (!nav || !price) return null;

        // 实际投入 = fixedCapital 或 min(最大资金量, 申购上限)
        // purchase_limit: null=无限额, number=限额(元)
        const purchaseLimit = fund.purchase_limit;
        const capital = fixedCapital !== null ? fixedCapital : (purchaseLimit ? Math.min(this.maxCapital, purchaseLimit) : this.maxCapital);

        // 佣金计算
        const commissionRatePct = this.commissionRate / 10000;
        const rawCommission = capital * commissionRatePct;
        const actualCommission = Math.max(rawCommission, this.commissionMin);
        const actualCommissionRate = (actualCommission / capital) * 100;
        const isMinCommission = rawCommission < this.commissionMin;

        if (premium > 0) {
            // 溢价套利: 申购→场内卖出
            const purchaseFeeRate = fund.purchase_fee_rate ?? 0;
            const purchaseFeeAmount = capital * purchaseFeeRate / 100;
            const sellCommissionRate = actualCommissionRate;
            const sellCommissionAmount = actualCommission;
            const profitRate = premium - purchaseFeeRate - sellCommissionRate;
            const profitAmount = capital * profitRate / 100;
            return {
                rate: profitRate, amount: profitAmount, capital,
                direction: '溢价套利',
                breakdown: {
                    premiumRate: premium,
                    purchaseFeeRate, purchaseFeeAmount,
                    sellCommissionRate, sellCommissionAmount,
                    commissionRatePct: this.commissionRate,
                    rawCommission, actualCommission, isMinCommission,
                    purchaseLimit, maxCapital: this.maxCapital,
                }
            };
        } else {
            // 折价套利: 场内买入→赎回
            const buyCommissionRate = actualCommissionRate;
            const buyCommissionAmount = actualCommission;
            const redemptionFeeRate = fund.redemption_fee_rate ?? 1.5;
            const redemptionFeeAmount = capital * redemptionFeeRate / 100;
            const profitRate = Math.abs(premium) - buyCommissionRate - redemptionFeeRate;
            const profitAmount = capital * profitRate / 100;
            return {
                rate: profitRate, amount: profitAmount, capital,
                direction: '折价套利',
                breakdown: {
                    discountRate: Math.abs(premium),
                    buyCommissionRate, buyCommissionAmount,
                    redemptionFeeRate, redemptionFeeAmount,
                    commissionRatePct: this.commissionRate,
                    rawCommission, actualCommission, isMinCommission,
                    purchaseLimit, maxCapital: this.maxCapital,
                }
            };
        }
    }

    /** 显示预计收益详细弹窗 */
    showProfitDetail(fundCode) {
        const fund = this.funds.find(f => f.code === fundCode);
        if (!fund) return;
        const est = this.calcEstimatedProfit(fund);
        if (!est) return;
        const bd = est.breakdown;

        // 构建弹窗内容
        let lines = [];
        lines.push(`<div class="profit-detail">`);
        lines.push(`<div class="profit-detail-title">${est.direction} · ${fund.code} ${fund.name}</div>`);
        lines.push(`<div class="profit-detail-section">`);
        lines.push(`<div class="profit-detail-subtitle">💰 投入金额</div>`);
        lines.push(`<div class="profit-detail-row"><span>最大资金量设定</span><span>${bd.maxCapital.toLocaleString()}元</span></div>`);
        if (bd.purchaseLimit) {
            lines.push(`<div class="profit-detail-row"><span>基金申购限额</span><span>${bd.purchaseLimit.toLocaleString()}元</span></div>`);
            lines.push(`<div class="profit-detail-row highlight"><span>实际投入</span><span>${est.capital.toLocaleString()}元</span></div>`);
        } else {
            lines.push(`<div class="profit-detail-row highlight"><span>实际投入</span><span>${est.capital.toLocaleString()}元（无限额）</span></div>`);
        }
        lines.push(`</div>`);

        // 收益率分解
        lines.push(`<div class="profit-detail-section">`);
        lines.push(`<div class="profit-detail-subtitle">📊 收益率构成</div>`);
        if (est.rate >= 0 && bd.premiumRate !== undefined) {
            // 溢价套利
            lines.push(`<div class="profit-detail-row plus"><span>溢价率</span><span>+${bd.premiumRate.toFixed(2)}%</span></div>`);
            lines.push(`<div class="profit-detail-row minus"><span>申购费率（天天基金优惠）</span><span>−${bd.purchaseFeeRate.toFixed(2)}%</span></div>`);
            lines.push(`<div class="profit-detail-row minus"><span>卖出佣金率${bd.isMinCommission ? '（按最低收费）' : ''}</span><span>−${bd.sellCommissionRate.toFixed(4)}%</span></div>`);
        } else if (bd.discountRate !== undefined) {
            // 折价套利
            lines.push(`<div class="profit-detail-row plus"><span>折价率</span><span>+${bd.discountRate.toFixed(2)}%</span></div>`);
            lines.push(`<div class="profit-detail-row minus"><span>买入佣金率${bd.isMinCommission ? '（按最低收费）' : ''}</span><span>−${bd.buyCommissionRate.toFixed(4)}%</span></div>`);
            lines.push(`<div class="profit-detail-row minus"><span>赎回费率（≤6天）</span><span>−${bd.redemptionFeeRate.toFixed(2)}%</span></div>`);
        }
        const rateClass = est.rate > 0 ? 'plus' : est.rate < 0 ? 'minus' : '';
        lines.push(`<div class="profit-detail-row ${rateClass} total"><span>预计收益率</span><span>${est.rate > 0 ? '+' : ''}${est.rate.toFixed(2)}%</span></div>`);
        lines.push(`</div>`);

        // 收益额分解
        lines.push(`<div class="profit-detail-section">`);
        lines.push(`<div class="profit-detail-subtitle">💵 收益额构成</div>`);
        if (est.rate >= 0 && bd.purchaseFeeAmount !== undefined) {
            lines.push(`<div class="profit-detail-row"><span>申购费</span><span>${bd.purchaseFeeAmount.toFixed(2)}元</span></div>`);
            lines.push(`<div class="profit-detail-row"><span>卖出佣金</span><span>${bd.sellCommissionAmount.toFixed(2)}元</span></div>`);
            lines.push(`<div class="profit-detail-row hint"><span>佣金费率万${bd.commissionRatePct}${bd.isMinCommission ? '，实际<最低收费' + this.commissionMin + '元' : ''}</span><span></span></div>`);
        } else if (bd.buyCommissionAmount !== undefined) {
            lines.push(`<div class="profit-detail-row"><span>买入佣金</span><span>${bd.buyCommissionAmount.toFixed(2)}元</span></div>`);
            lines.push(`<div class="profit-detail-row"><span>赎回费</span><span>${bd.redemptionFeeAmount.toFixed(2)}元</span></div>`);
            lines.push(`<div class="profit-detail-row hint"><span>佣金费率万${bd.commissionRatePct}${bd.isMinCommission ? '，实际<最低收费' + this.commissionMin + '元' : ''}</span><span></span></div>`);
        }
        const amtClass = est.amount > 0 ? 'plus' : est.amount < 0 ? 'minus' : '';
        lines.push(`<div class="profit-detail-row ${amtClass} total"><span>预计收益额</span><span>${est.amount > 0 ? '+' : ''}${est.amount.toFixed(2)}元</span></div>`);
        lines.push(`</div>`);

        lines.push(`<div class="profit-detail-footer">⚠️ 套利按最短时间估算，忽略T+N价格波动风险</div>`);
        lines.push(`</div>`);

        // 使用现有的 toast 机制或自定义弹窗
        this._showProfitPopover(lines.join(''), fundCode);
    }

    _showProfitPopover(html, fundCode) {
        // 移除已有弹窗
        const existing = document.getElementById('profitPopover');
        if (existing) existing.remove();

        const overlay = document.createElement('div');
        overlay.id = 'profitPopover';
        overlay.className = 'profit-popover-overlay';
        overlay.innerHTML = `<div class="profit-popover-card"><div class="profit-popover-close" id="profitPopoverClose">✕</div>${html}</div>`;
        document.body.appendChild(overlay);

        // 关闭事件
        const close = () => { overlay.remove(); };
        document.getElementById('profitPopoverClose').addEventListener('click', close);
        overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
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
        // 根据 displayMode 决定默认排序
        const effectiveSortField = this.sortField || 'premium_rate';
        const effectiveSortOrder = this.sortField ? this.sortOrder : (this.displayMode === 'premium' ? 'desc' : 'asc');
        filtered.sort((a, b) => {
            let valA, valB;
            if (effectiveSortField === 'amount_w') {
                valA = (a.amount ?? 0) / 10000;
                valB = (b.amount ?? 0) / 10000;
            } else if (effectiveSortField === 'est_profit_rate') {
                const estA = this.calcEstimatedProfit(a);
                const estB = this.calcEstimatedProfit(b);
                valA = estA ? estA.rate : -9999;
                valB = estB ? estB.rate : -9999;
            } else if (effectiveSortField === 'est_profit_amount') {
                const estA = this.calcEstimatedProfit(a);
                const estB = this.calcEstimatedProfit(b);
                valA = estA ? estA.amount : -9999;
                valB = estB ? estB.amount : -9999;
            } else {
                valA = a[effectiveSortField] ?? 0;
                valB = b[effectiveSortField] ?? 0;
            }
            return effectiveSortOrder === 'asc' ? valA - valB : valB - valA;
        });
        this.filteredFunds = filtered;
    }

    renderTable() {
        const tbody = document.getElementById('fundTableBody');
        const cardList = document.getElementById('mobileCardList');
        if (this.filteredFunds.length === 0) {
            if (tbody) tbody.innerHTML = `<tr><td colspan="12" class="empty-state"><i class="icon">📭</i><p>暂无数据</p><p class="loading-hint">尝试调整筛选条件</p></td></tr>`;
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
        // 预计收益计算
        const estProfit = this.calcEstimatedProfit(fund);
        let estProfitRateText = '--';
        let estProfitRateClass = 'premium-zero';
        let estProfitAmountText = '--';
        let estProfitAmountClass = 'premium-zero';
        let estProfitInfoBtn = '';
        if (estProfit) {
            const sign = estProfit.rate > 0 ? '+' : '';
            estProfitRateText = sign + estProfit.rate.toFixed(2) + '%';
            estProfitRateClass = estProfit.rate > 0 ? 'premium-positive' : estProfit.rate < 0 ? 'premium-negative' : 'premium-zero';
            if (estProfit.amount >= 10000) {
                estProfitAmountText = (estProfit.amount / 10000).toFixed(2) + '万';
            } else {
                estProfitAmountText = estProfit.amount.toFixed(2) + '元';
            }
            const amtSign = estProfit.amount > 0 ? '+' : '';
            estProfitAmountText = amtSign + estProfitAmountText;
            estProfitAmountClass = estProfit.amount > 0 ? 'premium-positive' : estProfit.amount < 0 ? 'premium-negative' : 'premium-zero';
            estProfitInfoBtn = `<button class="btn-profit-info" onclick="lofMonitor.showProfitDetail('${fund.code}')" title="查看收益构成">?</button>`;
        }
        return `<tr class="fund-row" data-code="${fund.code}" onclick="lofMonitor.showFundDetail('${fund.code}')" style="cursor:pointer">
            <td class="col-code click-copy" data-copy="${fund.code}" title="点击复制">${fund.code}</td>
            <td class="col-name click-copy" data-copy="${fund.name}" title="点击复制">${this.truncateName(fund.name)}</td>
            <td class="col-price">${priceText}</td>
            <td class="col-nav">${navText}${fund.nav ? '<span class="nav-badge">' + navType + '</span>' : ''}</td>
            <td class="col-change ${changeClass}">${changeText}</td>
            <td class="col-premium ${premiumClass}">${premiumText}</td>
            <td class="col-avg-premium ${avgPremiumClass}">${avgPremiumText}</td>
            <td class="col-amount">${amountText}</td>
            <td class="col-est-profit-rate ${estProfitRateClass}">${estProfitRateText}${estProfitInfoBtn}</td>
            <td class="col-est-profit-amount ${estProfitAmountClass}">${estProfitAmountText}${estProfitInfoBtn}</td>
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
        const navType = fund.is_formal_nav ? '正式' : '估算';
        const navText = fund.nav !== null && fund.nav !== undefined ? navType + ' ' + fund.nav.toFixed(3) : '--';
        const priceText = fund.price !== null && fund.price !== undefined ? fund.price.toFixed(3) : '--';
        const statusHtml = fund.premium_status ? `<span class="mc-status-badge status-badge ${fund.premium_status}">${fund.premium_status}</span>` : '';
        
        // 计算千元可赚收益（固定1000元基准）
        const est = this.calcEstimatedProfit(fund, 1000);
        // 按固定1000元计算: profit = 1000 * rate / 100 = rate * 10
        const per1000Profit = est && est.amount ? est.amount : 0;
        const per1000Text = per1000Profit > 0 ? per1000Profit.toFixed(2) + '元' : '--';
        
        // 状态样式
        let cardClass = 'mobile-card';
        let profitColor = '';
        if (pr > 0) {
            profitColor = pr > 3 ? '#ff4d4f' : '#ff7a45';
        } else if (pr < 0) {
            profitColor = '#73d13d';
        }
        // 流动性差 (<10万成交额)
        const amountWan = (fund.amount ?? 0) / 10000;
        if (amountWan < 10) {
            cardClass += ' mc-low-liquidity';
        }
        // 暂停申购
        if (fund.premium_status === '暂停申购') {
            cardClass += ' mc-suspended';
        }
        
        return `<div class="${cardClass}" data-code="${fund.code}" onclick="lofMonitor.showFundDetail('${fund.code}')" style="cursor:pointer">
            <div class="mc-left">
                <div class="mc-row"><span class="mc-code">${fund.code}</span></div>
                <div class="mc-row"><span class="mc-name">${fund.name}</span></div>
                <div class="mc-row mc-row3">
                    <span class="mb-item"><span class="mb-label">现价</span><span class="mb-val">${priceText}</span></span>
                    <span class="mb-item"><span class="mb-label">净值</span><span class="mb-val">${navText}</span></span>
                </div>
            </div>
            <div class="mc-right">
                <div class="mc-premium-wrap"><span class="mc-premium ${premiumClass}">${premiumText}</span></div>
                <div class="mc-profit-row">
                    <span class="mb-item mb-profit" style="${profitColor ? 'color:' + profitColor + ';' : ''}">
                        <span class="mb-label">千元可赚</span>
                        <span class="mb-val ${amountWan < 10 ? 'low-liquidity' : ''} ${fund.premium_status === '暂停申购' ? 'suspended' : ''}">${per1000Text}</span>
                    </span>
                </div>
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
        // 深色模式按钮
        const darkModeBtn = document.getElementById('darkModeBtn');
        if (darkModeBtn) darkModeBtn.addEventListener('click', () => this.toggleDarkMode());
        // 模式切换按钮
        const premiumModeBtn = document.getElementById('premiumModeBtn');
        const discountModeBtn = document.getElementById('discountModeBtn');
        if (premiumModeBtn) premiumModeBtn.addEventListener('click', () => this.setDisplayMode('premium'));
        if (discountModeBtn) discountModeBtn.addEventListener('click', () => this.setDisplayMode('discount'));
        // 基金详情弹窗事件
        const closeFundDetailBtn = document.getElementById('closeFundDetailBtn');
        const fundDetailModal = document.getElementById('fundDetailModal');
        if (closeFundDetailBtn) closeFundDetailBtn.addEventListener('click', () => this.closeFundDetail());
        if (fundDetailModal) fundDetailModal.addEventListener('click', e => { if (e.target === fundDetailModal) this.closeFundDetail(); });
        // 点击复制
        document.addEventListener('click', e => {
            const target = e.target.closest('.click-copy');
            if (target) {
                const text = target.dataset.copy;
                if (text) {
                    navigator.clipboard.writeText(text).then(() => {
                        this.showCopyToast(text);
                    }).catch(() => {});
                }
            }
        });
    }

    // ===== 深色模式 =====
    toggleDarkMode() {
        // 循环切换: 'dark' <-> 'light'
        this.darkMode = this.darkMode === 'dark' ? 'light' : 'dark';
        localStorage.setItem('lof_darkMode', this.darkMode);
        this.applyDarkMode(true);
    }

    applyDarkMode(save) {
        const btn = document.getElementById('darkModeBtn');
        const root = document.documentElement;

        // 清除之前的类
        root.classList.remove('dark-mode', 'light-mode');

        if (this.darkMode === 'dark') {
            root.classList.add('dark-mode');
            if (btn) btn.textContent = '☀️';
            if (btn) btn.title = '深色模式（点击切换浅色）';
        } else {
            root.classList.add('light-mode');
            if (btn) btn.textContent = '🌙';
            if (btn) btn.title = '浅色模式（点击切换深色）';
        }
    }

    // ===== 显示模式切换 =====
    applyDisplayMode() {
        const premiumBtn = document.getElementById('premiumModeBtn');
        const discountBtn = document.getElementById('discountModeBtn');
        if (premiumBtn) premiumBtn.classList.toggle('active', this.displayMode === 'premium');
        if (discountBtn) discountBtn.classList.toggle('active', this.displayMode === 'discount');
    }

    setDisplayMode(mode) {
        this.displayMode = mode;
        localStorage.setItem('lof_displayMode', mode);
        // 更新按钮状态
        this.applyDisplayMode();
        // 重置排序字段，让 applyFilters 使用 displayMode 决定排序
        this.sortField = null;
        this.applyFilters();
        this.renderTable();
        this.updatePaginationInfo();
    }

    // ===== 复制提示 =====
    showCopyToast(text) {
        let toast = document.getElementById('copyToast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'copyToast';
            toast.className = 'copy-toast';
            document.body.appendChild(toast);
        }
        toast.textContent = '✓ 已复制: ' + text;
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 1000);
    }

    openSettingsModal() {
        const modal = document.getElementById('settingsModal');
        const thresholdInput = document.getElementById('thresholdInput');
        const avgThresholdInput = document.getElementById('avgThresholdInput');
        const minAmountInput = document.getElementById('minAmountInput');
        const commissionRateInput = document.getElementById('commissionRateInput');
        const commissionMinInput = document.getElementById('commissionMinInput');
        const maxCapitalInput = document.getElementById('maxCapitalInput');
        if (thresholdInput) thresholdInput.value = this.threshold || 0;
        if (avgThresholdInput) avgThresholdInput.value = this.avgThreshold || 0;
        if (minAmountInput) minAmountInput.value = this.minAmount || 0;
        if (commissionRateInput) commissionRateInput.value = this.commissionRate;
        if (commissionMinInput) commissionMinInput.value = this.commissionMin;
        if (maxCapitalInput) maxCapitalInput.value = this.maxCapital;
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
        const commissionRateInput = document.getElementById('commissionRateInput');
        const commissionMinInput = document.getElementById('commissionMinInput');
        const maxCapitalInput = document.getElementById('maxCapitalInput');
        this.threshold = parseFloat(thresholdInput?.value) || 0;
        this.avgThreshold = parseFloat(avgThresholdInput?.value) || 0;
        this.minAmount = parseFloat(minAmountInput?.value) || 0;
        this.commissionRate = parseFloat(commissionRateInput?.value) || 1.5;
        this.commissionMin = parseFloat(commissionMinInput?.value) || 5;
        this.maxCapital = parseFloat(maxCapitalInput?.value) || 1000;
        // 保存所有设置到 localStorage（扩展记忆功能）
        localStorage.setItem('lof_threshold', this.threshold);
        localStorage.setItem('lof_avgThreshold', this.avgThreshold);
        localStorage.setItem('lof_minAmount', this.minAmount);
        localStorage.setItem('lof_commissionRate', this.commissionRate);
        localStorage.setItem('lof_commissionMin', this.commissionMin);
        localStorage.setItem('lof_maxCapital', this.maxCapital);
        this.currentPage = 1;
        this.applyFilters();
        this.renderTable();
        this.updatePaginationInfo();
        this.closeSettingsModal();
        const parts = [];
        if (this.threshold > 0) parts.push(`溢价率≥${this.threshold}%`);
        if (this.avgThreshold > 0) parts.push(`三日均溢≥${this.avgThreshold}%`);
        if (this.minAmount > 0) parts.push(`成交额≥${this.minAmount}万`);
        parts.push(`佣金万${this.commissionRate} 最低${this.commissionMin}元 最大投入${this.maxCapital}元`);
        this.showToast(parts.length ? '设置已应用：' + parts.join('，') : '设置已重置');
    }

    resetSettings() {
        const thresholdInput = document.getElementById('thresholdInput');
        const avgThresholdInput = document.getElementById('avgThresholdInput');
        const minAmountInput = document.getElementById('minAmountInput');
        const commissionRateInput = document.getElementById('commissionRateInput');
        const commissionMinInput = document.getElementById('commissionMinInput');
        const maxCapitalInput = document.getElementById('maxCapitalInput');
        if (thresholdInput) thresholdInput.value = 0;
        if (avgThresholdInput) avgThresholdInput.value = 0;
        if (minAmountInput) minAmountInput.value = 0;
        if (commissionRateInput) commissionRateInput.value = 1.5;
        if (commissionMinInput) commissionMinInput.value = 5;
        if (maxCapitalInput) maxCapitalInput.value = 1000;
    }

    handleSort(field) {
        if (this.sortField === field) {
            this.sortOrder = this.sortOrder === 'asc' ? 'desc' : 'asc';
        } else {
            this.sortField = field;
            this.sortOrder = 'desc';
        }
        document.querySelectorAll('.sortable').forEach(th => {
            th.classList.remove('sort-asc', 'sort-desc', 'active');
            if (th.dataset.field === field) th.classList.add(`sort-${this.sortOrder}`, 'active');
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

    updateLoaderText(text) {
        const loaderText = document.querySelector('.loader-content p');
        if (loaderText) loaderText.textContent = text;
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

        // 显示"刷新中..."
        if (statusEl) {
            statusEl.textContent = '刷新中...';
            statusEl.classList.add('show');
        }

        try {
            await this.checkHealth();
            await this.loadRankings();
            await this.loadFunds();

            // 显示"✓"成功
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

    // ===== 基金详情 =====
    async showFundDetail(code) {
        const fund = this.funds.find(f => f.code === code);
        if (!fund) {
            this.showToast('未找到该基金');
            return;
        }

        const modal = document.getElementById('fundDetailModal');
        if (!modal) return;

        // 填充基本信息
        document.getElementById('fundDetailTitle').textContent = `${fund.code} ${fund.name}`;
        document.getElementById('fdCode').textContent = fund.code;
        document.getElementById('fdName').textContent = fund.name;
        document.getElementById('fdPrice').textContent = fund.price != null ? fund.price.toFixed(3) : '--';
        const navType = fund.is_formal_nav ? '正式' : '估算';
        document.getElementById('fdNav').textContent = fund.nav != null ? `${navType} ${fund.nav.toFixed(3)}` : '--';
        
        const pr = fund.premium_rate;
        const premiumSign = pr > 0 ? '+' : '';
        document.getElementById('fdPremiumRate').textContent = pr != null ? premiumSign + pr.toFixed(2) + '%' : '--';
        document.getElementById('fdPremiumRate').className = 'fd-value ' + (pr > 0 ? 'fd-pos' : pr < 0 ? 'fd-neg' : '');
        
        const amountWan = (fund.amount ?? 0) / 10000;
        document.getElementById('fdAmount').textContent = amountWan >= 10000 ? (amountWan / 10000).toFixed(2) + '亿' : amountWan.toFixed(2) + '万';
        
        const est = this.calcEstimatedProfit(fund);
        document.getElementById('fdEstProfitRate').textContent = est ? (est.rate > 0 ? '+' : '') + est.rate.toFixed(2) + '%' : '--';
        document.getElementById('fdEstProfitRate').className = 'fd-value ' + (est && est.rate > 0 ? 'fd-pos' : est && est.rate < 0 ? 'fd-neg' : '');
        document.getElementById('fdEstProfitAmount').textContent = est ? (est.amount > 0 ? '+' : '') + est.amount.toFixed(2) + '元' : '--';
        document.getElementById('fdEstProfitAmount').className = 'fd-value ' + (est && est.amount > 0 ? 'fd-pos' : est && est.amount < 0 ? 'fd-neg' : '');
        
        document.getElementById('fdStatus').innerHTML = `<span class="status-badge ${fund.premium_status || ''}">${fund.premium_status || '未知'}</span>`;
        document.getElementById('fdNavDate').textContent = fund.nav_date || '--';

        // 绘制图表
        await this.renderFundDetailChart(fund);

        modal.style.display = 'flex';
    }

    async renderFundDetailChart(fund) {
        const canvas = document.getElementById('fdChart');
        if (!canvas) return;

        // 销毁旧图表
        if (this.detailChart) {
            this.detailChart.destroy();
            this.detailChart = null;
        }

        // 尝试从 API 获取历史数据
        let historyData = null;
        try {
            const result = await api.getFundDetail(fund.code);
            historyData = result.data?.history || result.data?.price_history || null;
        } catch (e) {
            console.warn('获取历史数据失败:', e.message);
        }

        // 如果没有历史数据，生成模拟数据
        if (!historyData || !historyData.length) {
            const labels = [];
            const prices = [];
            const premiums = [];
            const today = new Date();
            for (let i = 6; i >= 0; i--) {
                const d = new Date(today);
                d.setDate(d.getDate() - i);
                labels.push(`${d.getMonth()+1}/${d.getDate()}`);
                // 模拟数据：基于当前值添加随机波动
                const priceVar = fund.price * (1 + (Math.random() - 0.5) * 0.02);
                const premiumVar = fund.premium_rate + (Math.random() - 0.5) * 2;
                prices.push(priceVar.toFixed(3));
                premiums.push(premiumVar.toFixed(2));
            }
            historyData = { labels, prices, premiums };
        }

        const ctx = canvas.getContext('2d');
        const isDark = this.darkMode === 'dark';
        
        this.detailChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: historyData.labels || historyData.map(h => h.date),
                datasets: [
                    {
                        label: '价格',
                        data: historyData.prices || historyData.map(h => h.price),
                        borderColor: '#ff7a45',
                        backgroundColor: 'rgba(255, 122, 69, 0.1)',
                        yAxisID: 'y',
                        tension: 0.3,
                        pointRadius: 3,
                    },
                    {
                        label: '溢价率(%)',
                        data: historyData.premiums || historyData.map(h => h.premium_rate),
                        borderColor: '#73d13d',
                        backgroundColor: 'rgba(115, 209, 61, 0.1)',
                        yAxisID: 'y1',
                        tension: 0.3,
                        pointRadius: 3,
                    }
                ]
            },
            options: {
                responsive: true,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { position: 'top', labels: { color: isDark ? '#fff' : '#333' } },
                    tooltip: { mode: 'index', intersect: false }
                },
                scales: {
                    x: { ticks: { color: isDark ? '#aaa' : '#666' }, grid: { color: isDark ? '#333' : '#eee' } },
                    y: { type: 'linear', display: true, position: 'left', title: { display: true, text: '价格', color: isDark ? '#fff' : '#333' }, ticks: { color: isDark ? '#aaa' : '#666' }, grid: { color: isDark ? '#333' : '#eee' } },
                    y1: { type: 'linear', display: true, position: 'right', title: { display: true, text: '溢价率(%)', color: isDark ? '#fff' : '#333' }, ticks: { color: isDark ? '#aaa' : '#666' }, grid: { drawOnChartArea: false } }
                }
            }
        });
    }

    closeFundDetail() {
        const modal = document.getElementById('fundDetailModal');
        if (modal) modal.style.display = 'none';
        if (this.detailChart) {
            this.detailChart.destroy();
            this.detailChart = null;
        }
    }
}

document.addEventListener('DOMContentLoaded', () => { window.lofMonitor = new LofFundMonitor(); });
