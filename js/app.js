/**
 * LOF基金监控系统 - 主应用逻辑
 */

class LofFundMonitor {
    constructor() {
        this.funds = [];
        this.filteredFunds = [];
        this.currentPage = 1;
        this.pageSize = 20;
        this.sortField = 'premium_rate';
        this.sortOrder = 'desc';
        this.searchKeyword = '';
        this.refreshTimer = null;
        this.searchTimeout = null;
        this.isLoading = false;
        // 筛选参数（从 localStorage 恢复或用默认值）
        this.threshold = parseFloat(localStorage.getItem('lof_threshold')) || 0;
        this.avgThreshold = parseFloat(localStorage.getItem('lof_avgThreshold')) || 0;
        this.minAmount = parseFloat(localStorage.getItem('lof_minAmount')) || 100;
        this.showUnpurchasable = localStorage.getItem('lof_showUnpurchasable') !== '0';
        // 预计收益计算参数（从 localStorage 恢复或用默认值）
        this.commissionRate = parseFloat(localStorage.getItem('lof_commissionRate')) || 1.5;  // 万X
        this.commissionMin = parseFloat(localStorage.getItem('lof_commissionMin')) || 5;      // 元
        this.maxCapital = parseFloat(localStorage.getItem('lof_maxCapital')) || 1000;        // 元
        // 深色模式（从 localStorage 恢复，默认浅色）
        this.darkMode = localStorage.getItem('lof_darkMode') || 'light';
        this.bindEvents();
        this.applyDarkMode(false); // 不保存，仅应用
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
                // 欢迎弹窗 —— 首次访问，页面加载完毕后再弹出
                this._showWelcome();
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

    _toggleChartFullscreen() {
        const container = document.querySelector('.fd-chart-container');
        if (!container) return;
        if (document.fullscreenElement) {
            document.exitFullscreen();
        } else {
            container.requestFullscreen().then(() => {
                if (screen.orientation && screen.orientation.lock) {
                    screen.orientation.lock('landscape').catch(() => {});
                }
            }).catch(() => {});
        }
    }

    _showWelcome() {
        // sessionStorage: 浏览器会话内记住，关闭标签页后自动清除
        if (sessionStorage.getItem('jkc_welcome_shown')) return;
        sessionStorage.setItem('jkc_welcome_shown', '1');
        const overlay = document.getElementById('welcomeOverlay');
        const agreeBtn = document.getElementById('welcomeAgreeBtn');
        if (overlay && agreeBtn) {
            overlay.classList.remove('hidden');
            agreeBtn.addEventListener('click', () => {
                overlay.classList.add('hidden');
            }, { once: true });
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
            // 记录服务端数据时间戳，用于刷新按钮时间对齐
            if (result.meta?.last_fetch) {
                this._lastServerFetch = result.meta.last_fetch;
            }
            // 保存原始数据总数（过滤前）
            const totalFromApi = result.data.length;
            // 过滤停牌、无溢价率的基金（停购基金动态过滤，不在此处处理）
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
        const fund = this.funds.find(f => f.code === code);
        return fund?.avg_premium_3d ?? null;
    }

    // ===== 预计收益计算 =====
    calcEstimatedProfit(fund, overrideCapital = null) {
        if (fund.can_purchase === false) return { rate: 0, amount: 0, capital: 0, direction: '停止申购', breakdown: { maxCapital: 0 } };
        const premium = fund.premium_rate;
        if (premium === null || premium === undefined) return null;

        const nav = fund.nav;
        const price = fund.price;
        if (!nav || !price) return null;

        const purchaseLimit = fund.purchase_limit;
        const maxCap = overrideCapital !== null ? overrideCapital : this.maxCapital;
        const capital = purchaseLimit ? Math.min(maxCap, purchaseLimit) : maxCap;

        const commissionRatePct = this.commissionRate / 10000;
        const rawCommission = capital * commissionRatePct;
        const actualCommission = Math.max(rawCommission, this.commissionMin);
        const actualCommissionRate = (actualCommission / capital) * 100;
        const isMinCommission = rawCommission < this.commissionMin;

        if (premium > 0) {
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
                    purchaseLimit, maxCapital: maxCap,
                }
            };
        } else {
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
                    purchaseLimit, maxCapital: maxCap,
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

        lines.push(`<div class="profit-detail-section">`);
        lines.push(`<div class="profit-detail-subtitle">📊 收益率构成</div>`);
        if (est.rate >= 0 && bd.premiumRate !== undefined) {
            lines.push(`<div class="profit-detail-row plus"><span>溢价率</span><span>+${bd.premiumRate.toFixed(2)}%</span></div>`);
            lines.push(`<div class="profit-detail-row minus"><span>申购费率（天天基金优惠）</span><span>−${bd.purchaseFeeRate.toFixed(2)}%</span></div>`);
            lines.push(`<div class="profit-detail-row minus"><span>卖出佣金率${bd.isMinCommission ? '（按最低收费）' : ''}</span><span>−${bd.sellCommissionRate.toFixed(4)}%</span></div>`);
        } else if (bd.discountRate !== undefined) {
            lines.push(`<div class="profit-detail-row plus"><span>折价率</span><span>+${bd.discountRate.toFixed(2)}%</span></div>`);
            lines.push(`<div class="profit-detail-row minus"><span>买入佣金率${bd.isMinCommission ? '（按最低收费）' : ''}</span><span>−${bd.buyCommissionRate.toFixed(4)}%</span></div>`);
            lines.push(`<div class="profit-detail-row minus"><span>赎回费率（≤6天）</span><span>−${bd.redemptionFeeRate.toFixed(2)}%</span></div>`);
        }
        const rateClass = est.rate > 0 ? 'plus' : est.rate < 0 ? 'minus' : '';
        lines.push(`<div class="profit-detail-row ${rateClass} total"><span>预计收益率</span><span>${est.rate > 0 ? '+' : ''}${est.rate.toFixed(2)}%</span></div>`);
        lines.push(`</div>`);

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

        lines.push(`<div class="profit-detail-footer">所有预估收益为理论计算结果，不产生任何收益保证</div>`);
        lines.push(`</div>`);

        this._showProfitPopover(lines.join(''), fundCode);
    }

    _showProfitPopover(html, fundCode) {
        const existing = document.getElementById('profitPopover');
        if (existing) existing.remove();

        const overlay = document.createElement('div');
        overlay.id = 'profitPopover';
        overlay.className = 'profit-popover-overlay';
        overlay.innerHTML = `<div class="profit-popover-card"><div class="profit-popover-close" id="profitPopoverClose">✕</div>${html}</div>`;
        document.body.appendChild(overlay);

        const close = () => { overlay.remove(); };
        document.getElementById('profitPopoverClose').addEventListener('click', close);
        overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    }

    applyFilters() {
        let filtered = [...this.funds];
        if (!this.showUnpurchasable) {
            filtered = filtered.filter(fund => fund.can_purchase !== false);
        }
        if (this.searchKeyword) {
            const keyword = this.searchKeyword.toLowerCase();
            filtered = filtered.filter(fund =>
                fund.code.toLowerCase().includes(keyword) ||
                fund.name.toLowerCase().includes(keyword)
            );
        }
        if (this.threshold > 0) {
            filtered = filtered.filter(fund => {
                const absRate = Math.abs(fund.premium_rate ?? 0);
                return absRate >= this.threshold;
            });
        }
        if (this.minAmount > 0) {
            filtered = filtered.filter(fund => {
                const amountWan = (fund.amount ?? 0) / 10000;
                return amountWan >= this.minAmount;
            });
        }
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
            } else if (this.sortField === 'est_profit_rate') {
                const estA = this.calcEstimatedProfit(a);
                const estB = this.calcEstimatedProfit(b);
                valA = estA ? estA.rate : -9999;
                valB = estB ? estB.rate : -9999;
            } else if (this.sortField === 'est_profit_amount') {
                const estA = this.calcEstimatedProfit(a);
                const estB = this.calcEstimatedProfit(b);
                valA = estA ? estA.amount : -9999;
                valB = estB ? estB.amount : -9999;
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

        let amountText = '--';
        if (fund.amount !== null && fund.amount !== undefined) {
            const amountWan = fund.amount / 10000;
            amountText = amountWan >= 10000 ? (amountWan / 10000).toFixed(2) + '亿' : amountWan.toFixed(2) + '万';
        }

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
            estProfitInfoBtn = `<button class="btn-profit-info" data-code="${fund.code}" title="查看收益构成">?</button>`;
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
        const statusText = fund.premium_status || '未知';
        // 千元可赚
        const est = this.calcEstimatedProfit(fund);
        let profitText = '--', profitClass = '';
        if (est) {
            const scale = est.breakdown.maxCapital > 0 ? 1000 / est.breakdown.maxCapital : 0;
            const profit1000 = est.amount * scale;
            profitText = profit1000 > 0 ? '+' + profit1000.toFixed(2) : profit1000.toFixed(2);
            profitClass = profit1000 > 0 ? 'mc-pos' : profit1000 < 0 ? 'mc-neg' : '';
        }
        return `<div class="mobile-card" data-code="${fund.code}">
            <div class="mc-top-row">
                <span class="mc-code">${fund.code}</span>
                <span class="mc-name">${this.truncateName(fund.name, 8)}</span>
                <span class="mc-status-badge status-badge ${fund.premium_status || ''}">${statusText}</span>
            </div>
            <div class="mc-right">
                <span class="mc-premium ${premiumClass}">${premiumText}</span>
            </div>
            <div class="mc-profit-row">
                <span class="mc-profit-label">千元可赚</span>
                <span class="mc-profit-val ${profitClass}">${profitText}</span>
                <button class="mc-profit-help" data-code="${fund.code}" title="查看计算详情">?</button>
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
        const settingsBtn = document.getElementById('settingsBtn');
        const closeSettingsBtn = document.getElementById('closeSettingsBtn');
        const settingsModal = document.getElementById('settingsModal');
        const applySettingsBtn = document.getElementById('applySettingsBtn');
        const resetSettingsBtn = document.getElementById('resetSettingsBtn');
        if (settingsBtn) settingsBtn.addEventListener('click', () => this.openSettingsModal());
        if (closeSettingsBtn) closeSettingsBtn.addEventListener('click', () => this.closeSettingsModal());
        // 移动端溢价/折价模式按钮
        const premiumModeBtn = document.getElementById('premiumModeBtn');
        const discountModeBtn = document.getElementById('discountModeBtn');
        if (premiumModeBtn) premiumModeBtn.addEventListener('click', () => this.setSortMode('premium'));
        if (discountModeBtn) discountModeBtn.addEventListener('click', () => this.setSortMode('discount'));
        // 套利流程帮助按钮
        document.querySelectorAll('.btn-arb-help').forEach(btn => {
            btn.addEventListener('click', () => this.showArbHelp(btn.dataset.type));
        });
        const arbHelpOverlay = document.getElementById('arbHelpOverlay');
        const arbHelpClose = document.getElementById('arbHelpClose');
        if (arbHelpOverlay) arbHelpOverlay.addEventListener('click', e => { if (e.target === arbHelpOverlay) this.closeArbHelp(); });
        if (arbHelpClose) arbHelpClose.addEventListener('click', () => this.closeArbHelp());
        if (settingsModal) settingsModal.addEventListener('click', e => { if (e.target === settingsModal) this.closeSettingsModal(); });
        if (applySettingsBtn) applySettingsBtn.addEventListener('click', () => this.applySettings());
        if (resetSettingsBtn) resetSettingsBtn.addEventListener('click', () => this.resetSettings());
        // 分页按钮（替代HTML内联onclick）
        const firstPageBtn = document.getElementById("firstPageBtn");
        const prevPageBtn = document.getElementById("prevPageBtn");
        const nextPageBtn = document.getElementById("nextPageBtn");
        const lastPageBtn = document.getElementById("lastPageBtn");
        const pageSizeSelect = document.getElementById("pageSizeSelect");
        if (firstPageBtn) firstPageBtn.addEventListener("click", () => this.goToPage(1));
        if (prevPageBtn) prevPageBtn.addEventListener("click", () => this.changePage(-1));
        if (nextPageBtn) nextPageBtn.addEventListener("click", () => this.changePage(1));
        if (lastPageBtn) lastPageBtn.addEventListener("click", () => this.goToLastPage());
        if (pageSizeSelect) pageSizeSelect.addEventListener("change", (e) => this.changePageSize(e.target.value));

        // 图表下拉菜单（change 事件只在真正切换时触发，click 不会误触发）
        const indSel = document.getElementById('fdIndSelect');
        const rangeSel = document.getElementById('fdRangeSelect');
        if (indSel) indSel.addEventListener('change', (e) => {
            this._detailMode = e.target.value;
            this._loadDetailChart(this._detailFundCode);
        });
        if (rangeSel) rangeSel.addEventListener('change', (e) => {
            this._detailDays = parseInt(e.target.value);
            this._loadDetailChart(this._detailFundCode);
        });

        // 图表全屏按钮
        const fsBtn = document.getElementById('fdFullscreenBtn');
        if (fsBtn) fsBtn.addEventListener('click', () => this._toggleChartFullscreen());

        // 深色模式按钮
        const darkModeBtn = document.getElementById('darkModeBtn');
        if (darkModeBtn) darkModeBtn.addEventListener('click', () => this.toggleDarkMode());
        // PC端：点击代码/名称列 → 复制文本
        document.querySelector('.fund-table')?.addEventListener('click', (e) => {
            const codeCell = e.target.closest('.col-code');
            const nameCell = e.target.closest('.col-name');
            if (codeCell || nameCell) {
                e.stopPropagation();
                const text = (codeCell || nameCell).textContent.trim();
                navigator.clipboard.writeText(text).then(() => this.showToast('复制成功')).catch(() => {});
                return;
            }
        });
        // 标记初始排序列
        const initTh = document.querySelector(`.sortable[data-field="${this.sortField}"]`);
        if (initTh) initTh.classList.add('sort-desc', 'active');
        // 通用点击事件委托（移动端 ? 图标 / 详情弹窗 / 卡片→弹窗）
        document.addEventListener('click', (e) => {
            // 移动端 ? 按钮
            const helpBtn = e.target.closest('.mc-profit-help');
            if (helpBtn) {
                e.stopPropagation();
                this.showProfitDetail(helpBtn.dataset.code);
                return;
            }
            // 详情弹窗预计收益额 ? 图标
            const profitHelp = e.target.closest('#fdProfitHelp');
            if (profitHelp) {
                e.stopPropagation();
                this._toggleFeeBreakdown();
                return;
            }
            // 图表信息 ? 图标
            const infoIcon = e.target.closest('.fd-info-icon');
            if (infoIcon) {
                e.stopPropagation();
                this._showChartInfoTip(infoIcon.dataset.tip);
                return;
            }
            // 图表指标/时间范围下拉切换 → 由 change 事件处理，避免 click 时误触发
            // 详情弹窗内代码/名称点击 → 复制文本 (Change 6)
            const detailCopy = e.target.closest('[data-copy]');
            if (detailCopy) {
                e.stopPropagation();
                const text = detailCopy.textContent.trim();
                navigator.clipboard.writeText(text).then(() => this.showToast('复制成功')).catch(() => {});
                return;
            }
            // PC端 ? 按钮 → 收益构成弹窗
            const profitInfo = e.target.closest('.btn-profit-info');
            if (profitInfo) {
                e.stopPropagation();
                this.showProfitDetail(profitInfo.dataset.code);
                return;
            }

            // 点击收益明细弹窗外部时关闭
            const feeBreakdown = document.getElementById('fdFeeBreakdown');
            if (feeBreakdown && feeBreakdown.classList.contains('show') &&
                !e.target.closest('#fdFeeBreakdown') && !e.target.closest('#fdProfitHelp')) {
                feeBreakdown.classList.remove('show');
            }

                        // 关闭详情弹窗
            const closeBtn = e.target.closest('#fdCloseBtn');
            if (closeBtn) { this.closeFundDetail(); return; }
            if (e.target.id === 'fundDetailModal') { this.closeFundDetail(); return; }
            // PC端基金行 / 移动端卡片点击 → 详情弹窗
            const row = e.target.closest('.fund-row');
            const card = e.target.closest('.mobile-card');
            if (row || card) {
                if (e.target.closest('.col-code') || e.target.closest('.col-name') ||
                    e.target.closest('.btn-profit-info') || e.target.closest('.mc-profit-help')) return;
                const code = (row || card).dataset.code;
                if (code) this.showFundDetail(code);
            }
        });
    }

    // ===== 深色模式 =====
    toggleDarkMode() {
        if (this.darkMode === 'light') {
            this.darkMode = 'dark';
        } else {
            this.darkMode = 'light';
        }
        localStorage.setItem('lof_darkMode', this.darkMode);
        this.applyDarkMode(true);
    }

    applyDarkMode(save) {
        const btn = document.getElementById('darkModeBtn');
        const root = document.documentElement;

        root.classList.remove('dark-mode', 'light-mode');

        if (this.darkMode === 'dark') {
            root.classList.add('dark-mode');
            if (btn) { btn.textContent = '☀️'; btn.title = '当前：深色模式（点击切换浅色）'; }
        } else {
            root.classList.add('light-mode');
            if (btn) { btn.textContent = '🌙'; btn.title = '当前：浅色模式（点击切换深色）'; }
        }
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
        const unpurchasableCheck = document.getElementById('showUnpurchasableCheck');
        if (unpurchasableCheck) unpurchasableCheck.checked = this.showUnpurchasable;
        if (commissionRateInput) commissionRateInput.value = this.commissionRate;
        if (commissionMinInput) commissionMinInput.value = this.commissionMin;
        if (maxCapitalInput) maxCapitalInput.value = this.maxCapital;
        if (modal) modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    }

    closeSettingsModal() {
        const modal = document.getElementById('settingsModal');
        if (modal) modal.style.display = 'none';
        document.body.style.overflow = '';  
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
        const unpurchasableCheck = document.getElementById('showUnpurchasableCheck');
        this.showUnpurchasable = unpurchasableCheck?.checked || false;
        localStorage.setItem('lof_showUnpurchasable', this.showUnpurchasable ? '1' : '0');
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
        if (minAmountInput) minAmountInput.value = 100;
        const unpurchasableCheck = document.getElementById('showUnpurchasableCheck');
        if (unpurchasableCheck) unpurchasableCheck.checked = false;
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
        this.currentPage = 1;
        this.applyFilters();
        this.renderTable();
    }

    setSortMode(mode) {
        this.sortField = 'premium_rate';
        this.sortOrder = mode === 'discount' ? 'asc' : 'desc';
        // 更新按钮样式
        const premiumBtn = document.getElementById('premiumModeBtn');
        const discountBtn = document.getElementById('discountModeBtn');
        if (premiumBtn && discountBtn) {
            premiumBtn.classList.toggle('active', mode === 'premium');
            discountBtn.classList.toggle('active', mode === 'discount');
        }
        // 同步PC端表头
        document.querySelectorAll('.sortable').forEach(th => {
            th.classList.remove('sort-asc', 'sort-desc', 'active');
            if (th.dataset.field === 'premium_rate') {
                th.classList.add(`sort-${this.sortOrder}`, 'active');
            }
        });
        this.currentPage = 1;
        this.applyFilters();
        this.renderTable();
    }

    showArbHelp(type) {
        const overlay = document.getElementById('arbHelpOverlay');
        const title = document.getElementById('arbHelpTitle');
        const body = document.getElementById('arbHelpBody');
        if (!overlay || !body) return;

        if (type === 'premium') {
            if (title) title.textContent = '溢价套利流程';
            body.innerHTML = `
                <div class="arb-step"><span class="arb-step-num">1</span><span class="arb-step-text"><b>场内申购</b>基金份额，按<b>净值</b>成交（价格更低）</span></div>
                <div class="arb-step"><span class="arb-step-num">2</span><span class="arb-step-text"><b>T+2 日</b>份额到账</span></div>
                <div class="arb-step"><span class="arb-step-num">3</span><span class="arb-step-text"><b>场内卖出</b>，按<b>市价</b>成交（价格更高）</span></div>
                <div class="arb-step"><span class="arb-step-num">4</span><span class="arb-step-text"><b>收益</b> = 溢价率 − 申购费率 − 卖出佣金率</span></div>
                <div class="arb-warn">⚠️ 风险：T+2 期间基金净值可能下跌，导致套利亏损甚至折价。溢价率需覆盖交易成本才有安全垫。</div>
            `;
        } else {
            if (title) title.textContent = '折价套利流程';
            body.innerHTML = `
                <div class="arb-step"><span class="arb-step-num">1</span><span class="arb-step-text"><b>场内买入</b>基金份额，按<b>市价</b>成交（价格更低）</span></div>
                <div class="arb-step"><span class="arb-step-num">2</span><span class="arb-step-text"><b>T+1 日</b>申请<b>赎回</b></span></div>
                <div class="arb-step"><span class="arb-step-num">3</span><span class="arb-step-text">按<b>净值</b>赎回，资金 <b>T+3~7 日</b>到账</span></div>
                <div class="arb-step"><span class="arb-step-num">4</span><span class="arb-step-text"><b>收益</b> = 折价率 − 买入佣金率 − 赎回费率</span></div>
                <div class="arb-warn">⚠️ 风险：赎回期间净值波动可能侵蚀折价空间，且资金占用时间较长（3~7天）。部分基金持有不足7天有惩罚性赎回费。</div>
            `;
        }
        overlay.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    }

    closeArbHelp() {
        const overlay = document.getElementById('arbHelpOverlay');
        if (overlay) overlay.style.display = 'none';
        // Only restore body scroll if fund detail modal is also closed
        const fundModal = document.getElementById('fundDetailModal');
        if (!fundModal || fundModal.style.display === 'none') {
            document.body.style.overflow = '';
        }
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
        const el = document.getElementById('statusText');
        if (el && el.textContent !== message) el.textContent = message;
    }

    updateLoaderText(text) {
        const loaderText = document.querySelector('.loader-content p');
        if (loaderText) loaderText.textContent = text;
    }

    updateStatusInfo(data) {
        if (document.getElementById('cacheCount')) document.getElementById('cacheCount').textContent = data.cache_count ?? '-';
        if (document.getElementById('lastFetch')) document.getElementById('lastFetch').textContent = this.formatTime(data.last_fetch);
        if (document.getElementById('refreshInterval')) document.getElementById('refreshInterval').textContent = (data.refresh_interval_sec || 300) / 60 + '分钟';
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
            document.getElementById('pageInfo').textContent = `${this.currentPage}/${totalPages} 页`;
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
        // 立即播放动画，不管数据是否更新
        if (icon) {
            icon.classList.remove('bouncing');
            icon.addEventListener('animationend', () => icon.classList.remove('bouncing'), { once: true });
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    icon.classList.add('bouncing');
                });
            });
        }

        if (statusEl) {
            statusEl.textContent = '刷新中...';
            statusEl.classList.add('show');
        }

        try {
            // 先查健康检查，获取中心服务器的 last_fetch 时间
            const healthResult = await this.checkHealth();
            const serverLastFetch = healthResult.data?.last_fetch;

            // 对齐时间：与本地缓存的 last_fetch 比较
            if (serverLastFetch && this._lastServerFetch === serverLastFetch) {
                // 时间相同 → 中心服务器数据未更新，只执行动画
                if (statusEl) statusEl.textContent = '✓';
                setTimeout(() => {
                    if (statusEl) statusEl.classList.remove('show');
                }, 1500);
                return;
            }

            // 时间不同 → 从中心服务器分发数据到网页
            this._lastServerFetch = serverLastFetch;
            await this.loadRankings();
            await this.loadFunds();
            if (statusEl) statusEl.textContent = '✓';
        } catch (error) {
            if (statusEl) statusEl.textContent = '✗';
            this.showToast('刷新失败: ' + error.message);
        } finally {
            if (btn) { btn.disabled = false; }
            setTimeout(() => {
                if (statusEl) statusEl.classList.remove('show');
            }, 2000);
        }
    }

    showToast(message) {
        const existing = document.querySelector('.copy-toast');
        if (existing) existing.remove();
        const toast = document.createElement('div');
        toast.className = 'copy-toast';
        toast.textContent = message;
        document.body.appendChild(toast);
        requestAnimationFrame(() => toast.classList.add('show'));
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, 1000);
    }

    // ===== 基金详情弹窗 =====
    showFundDetail(code) {
        const modal = document.getElementById('fundDetailModal');
        const skeleton = document.getElementById('fdSkeleton');
        const phase1 = document.getElementById('fdPhase1');
        const phase2 = document.getElementById('fdPhase2');
        if (!modal) return;

        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
        skeleton.classList.add('show');
        phase1.classList.add('hidden');
        phase2.style.display = 'block';
        phase2.classList.remove('visible');

        // Reset dropdowns to default
        this._detailMode = 'price,nav';
        this._detailDays = 7;
        this._detailFundCode = code;
        const indSel = document.getElementById('fdIndSelect');
        const rangeSel = document.getElementById('fdRangeSelect');
        if (indSel) indSel.value = 'price,nav';
        if (rangeSel) rangeSel.value = '7';

        if (this._detailChart) {
            this._detailChart.destroy();
            this._detailChart = null;
        }

        api.getFundDetail(code).then(detailResult => {
            const fund = detailResult.data;
            this._populateDetailKpi(fund);
            skeleton.classList.remove('show');
            phase1.classList.remove('hidden');

            requestAnimationFrame(() => {
                phase2.classList.add('visible');
                this._renderEmptyChart();
                this._loadDetailChart(code);
            });
        }).catch(err => {
            console.error('[LOF] 基金详情加载失败:', err);
            this.showToast('详情加载失败: ' + err.message);
        });
    }

    _loadDetailChart(code) {
        const days = this._detailDays || 7;
        api.getFundChart(code, days).then(chartResult => {
            const chartData = chartResult.data?.chart || [];
            if (chartData.length > 0) {
                this._renderDetailChart(chartData);
            }
        }).catch(() => {});
    }

    _renderEmptyChart() {
        const canvas = document.getElementById('fdChart');
        if (!canvas) return;
        if (this._detailChart) { this._detailChart.destroy(); this._detailChart = null; }

        const ctx = canvas.getContext('2d');
        const isDark = this.darkMode === 'dark';
        const tc = isDark ? '#8899aa' : '#666';
        const gc = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)';

        this._detailChart = new Chart(ctx, {
            type: 'line',
            data: { labels: [], datasets: [
                { _key: 'price', label: '场内价格', data: [], borderColor: '#ff7a45', borderWidth: 2, pointRadius: 0, tension: 0.2, fill: false, yAxisID: 'yPrice' },
                { _key: 'nav', label: '场外净值', data: [], borderColor: '#40a9ff', borderWidth: 2, pointRadius: 0, tension: 0.2, fill: false, yAxisID: 'yPrice' },
                { _key: 'premium', label: '溢价率', data: [], borderColor: '#e74c3c', borderWidth: 2, pointRadius: 0, tension: 0.2, fill: false, yAxisID: 'yPrem', hidden: true },
            ]},
            options: {
                responsive: true, maintainAspectRatio: false, animation: false,
                plugins: { legend: { display: false }, tooltip: { enabled: false } },
                scales: {
                    x: { grid: { display: false }, ticks: { font: { size: 11 }, color: tc } },
                    yPrice: { type: 'linear', display: true, position: 'left', grid: { color: gc }, min: 0, max: 1, ticks: { font: { size: 11 }, color: tc, callback: (v) => v.toFixed(3) } },
                    yPrem: { type: 'linear', display: false, position: 'right', grid: { drawOnChartArea: false }, min: -5, max: 5, ticks: { font: { size: 11 }, color: (ctx) => ctx.tick.value > 0 ? '#e74c3c' : ctx.tick.value < 0 ? '#27ae60' : tc, callback: (v) => v + '%' } },
                },
            },
        });
    }
    _populateDetailKpi(fund) {
        const setVal = (id, text, cls) => {
            const el = document.getElementById(id);
            if (!el) return;
            el.textContent = text || '--';
            el.className = 'fd-kpi-value';
            if (cls) el.classList.add(cls);
        };
        const isCopy = (id) => {
            const el = document.getElementById(id);
            if (el) el.classList.add('fd-code-name');
        };

        const pr = fund.premium_rate;
        const prCls = pr > 0 ? 'fd-pos' : pr < 0 ? 'fd-neg' : '';
        const prSign = pr > 0 ? '+' : '';

        const avg3d = fund.avg_premium_3d;
        const avgCls = avg3d > 0 ? 'fd-pos' : avg3d < 0 ? 'fd-neg' : '';
        const avgSign = avg3d > 0 ? '+' : '';

        const cp = fund.change_pct;
        const cpCls = cp >= 0 ? 'fd-change-up' : 'fd-change-down';
        const cpSign = cp >= 0 ? '+' : '';

        const navType = fund.is_formal_nav ? '正式' : '估算';

        let amountText = '--';
        if (fund.amount != null) {
            const aw = fund.amount / 10000;
            amountText = aw >= 10000 ? (aw / 10000).toFixed(2) + '亿' : aw.toFixed(2) + '万';
        }

        const est = this.calcEstimatedProfit(fund);

        setVal('fdCode', fund.code); isCopy('fdCode');
        setVal('fdName', fund.name); isCopy('fdName');
        setVal('fdPrice', fund.price != null ? fund.price.toFixed(3) : null);
        setVal('fdNav', fund.nav != null ? fund.nav.toFixed(3) + ' (' + navType + ')' : null);
        setVal('fdChangePct', cp != null ? cpSign + cp.toFixed(2) + '%' : null, cpCls);
        setVal('fdPremiumRate', pr != null ? prSign + pr.toFixed(2) + '%' : null, prCls);
        setVal('fdAvgPremium', avg3d != null ? avgSign + avg3d.toFixed(2) + '%' : null, avgCls);
        setVal('fdAmount', amountText);
        setVal('fdEstProfitRate', est ? (est.rate > 0 ? '+' : '') + est.rate.toFixed(2) + '%' : '--',
            est ? (est.rate > 0 ? 'fd-pos' : est.rate < 0 ? 'fd-neg' : '') : '');
        setVal('fdEstProfitAmount', est ? (est.amount > 0 ? '+' : '') + (Math.abs(est.amount) >= 10000 ? (est.amount / 10000).toFixed(2) + '万' : est.amount.toFixed(2) + '元') : '--',
            est ? (est.amount > 0 ? 'fd-pos' : est.amount < 0 ? 'fd-neg' : '') : '');
        setVal('fdStatus', fund.premium_status || '未知');

        // 申购限额
        const limitEl = document.getElementById('fdPurchaseLimit');
        if (limitEl) {
            if (fund.can_purchase === false) {
                limitEl.parentElement.style.display = '';
                limitEl.textContent = '暂停申购';
                limitEl.className = 'fd-kpi-value fd-neg';
            } else {
                limitEl.parentElement.style.display = '';
                limitEl.className = 'fd-kpi-value';
                if (fund.purchase_limit != null && fund.purchase_limit > 0) {
                    limitEl.textContent = (fund.purchase_limit / 10000).toFixed(0) + '万';
                } else {
                    limitEl.textContent = '不限额';
                }
            }
        }

        setVal('fdNavDate', fund.nav_date || '-');

        this._detailEstProfit = est;
        this._detailFundCode = fund.code;
        this._detailFundData = fund;

        const profitVal = document.getElementById('fdEstProfit');
        if (profitVal) {
            if (est) {
                const sign = est.amount > 0 ? '+' : '';
                profitVal.textContent = sign + (Math.abs(est.amount) >= 10000 ? (est.amount / 10000).toFixed(2) + '万' : est.amount.toFixed(2) + '元');
                profitVal.className = 'fd-profit-val ' + (est.amount > 0 ? 'fd-pos' : est.amount < 0 ? 'fd-neg' : '');
            } else {
                profitVal.textContent = '--';
                profitVal.className = 'fd-profit-val';
            }
        }

        const breakdown = document.getElementById('fdFeeBreakdown');
        if (breakdown) { breakdown.innerHTML = ''; breakdown.classList.remove('show'); }
    }

    closeFundDetail() {
        const modal = document.getElementById('fundDetailModal');
        if (modal) modal.style.display = 'none';
        document.body.style.overflow = '';  
        if (this._detailChart) {
            this._detailChart.destroy();
            this._detailChart = null;
        }
    }

    _renderDetailChart(chartData) {
        const canvas = document.getElementById('fdChart');
        if (!canvas) return;
        if (this._detailChart) { this._detailChart.destroy(); this._detailChart = null; }

        const ctx = canvas.getContext('2d');
        const labels = chartData.map(d => d.date.slice(5));
        const prices = chartData.map(d => d.price);
        const navs = chartData.map(d => d.nav);
        const premiums = chartData.map(d => d.premium_rate);

        const isDark = this.darkMode === 'dark';
        const tc = isDark ? '#8899aa' : '#666';
        const gc = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)';
        const isYearly = chartData.length > 60;
        const pointR = isYearly ? 0 : 4;
        const tickLimit = isYearly ? 15 : chartData.length;

        // 模式: 'price,nav' 显示价格+净值, 'premium' 显示溢价率
        const mode = this._detailMode || 'price,nav';
        const isPremMode = mode === 'premium';

        // 价格/净值 Y轴范围
        const pnVals = prices.concat(navs).filter(v => v != null);
        const pnMin = pnVals.length > 0 ? Math.floor(Math.min(...pnVals) * 0.995 * 1000) / 1000 : 0;
        const pnMax = pnVals.length > 0 ? Math.ceil(Math.max(...pnVals) * 1.005 * 1000) / 1000 : 1;

        // 溢价率 Y轴范围
        const prVals = premiums.filter(v => v != null);
        const prAbs = prVals.length > 0 ? Math.max(Math.abs(Math.min(...prVals)), Math.abs(Math.max(...prVals))) : 5;
        const prMax = Math.ceil(prAbs * 1.2) || 5;

        this._detailChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    {
                        _key: 'price', label: '场内价格', yAxisID: 'yPrice',
                        data: prices, borderColor: '#ff7a45', backgroundColor: 'rgba(255,122,69,0.08)',
                        borderWidth: 2, pointRadius: pointR, pointBackgroundColor: '#ff7a45', tension: 0.2, fill: false,
                        hidden: isPremMode,
                    },
                    {
                        _key: 'nav', label: '场外净值', yAxisID: 'yPrice',
                        data: navs, borderColor: '#40a9ff', backgroundColor: 'rgba(64,169,255,0.08)',
                        borderWidth: 2, pointRadius: pointR, pointBackgroundColor: '#40a9ff', tension: 0.2, fill: false,
                        hidden: isPremMode,
                    },
                    {
                        _key: 'premium', label: '溢价率', yAxisID: 'yPrem',
                        data: premiums, borderWidth: 2, pointRadius: pointR, tension: 0.2, fill: false,
                        hidden: !isPremMode,
                        segment: {
                            borderColor: (ctx) => (ctx.p0.raw >= 0 ? '#e74c3c' : '#27ae60'),
                        },
                        pointBackgroundColor: premiums.map(v => v >= 0 ? '#e74c3c' : '#27ae60'),
                    },
                ],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        enabled: false,
                        external: (context) => this._arbTooltip(context, chartData),
                    },
                },
                scales: {
                    x: { grid: { display: false }, ticks: { font: { size: 11 }, color: tc, maxTicksLimit: tickLimit, autoSkip: true } },
                    yPrice: {
                        type: 'linear', display: !isPremMode, position: 'left',
                        grid: { color: gc }, min: pnMin, max: pnMax,
                        ticks: { font: { size: 11 }, color: tc, callback: (v) => v.toFixed(3) },
                    },
                    yPrem: {
                        type: 'linear', display: isPremMode, position: 'left',
                        grid: { color: gc }, min: -prMax, max: prMax,
                        ticks: {
                            font: { size: 11 },
                            color: (ctx) => ctx.tick.value > 0 ? '#e74c3c' : ctx.tick.value < 0 ? '#27ae60' : tc,
                            callback: (v) => v.toFixed(1) + '%',
                        },
                    },
                },
            },
        });
    }

    _arbTooltip(context, chartData) {
        const tooltipEl = document.getElementById('fdArbTooltip');
        const ci = context.tooltip;
        if (ci.opacity === 0 || !ci.dataPoints?.length) {
            if (tooltipEl) tooltipEl.style.display = 'none';
            return;
        }

        const dataIdx = ci.dataPoints[0].dataIndex;
        const point = chartData[dataIdx];
        if (!point) { if (tooltipEl) tooltipEl.style.display = 'none'; return; }

        if (!tooltipEl) {
            const el = document.createElement('div');
            el.id = 'fdArbTooltip';
            el.className = 'fd-arb-tooltip';
            document.getElementById('fdPhase2')?.appendChild(el);
        }
        const el = document.getElementById('fdArbTooltip');
        if (!el) return;

        const mode = this._detailMode || 'price,nav';
        const isPrem = mode === 'premium';
        const date = point.date;

        // Get settings
        const maxCap = this.maxCapital || 1000;
        const commRate = (this.commissionRate || 1.5) / 10000;
        const commMin = this.commissionMin || 5;

        // Get fee rates from the current fund detail
        const purchaseFeePct = (this._detailFundData?.purchase_fee_rate ?? 0) / 100;
        const redeemFeePct = (this._detailFundData?.redemption_fee_rate ?? 1.5) / 100;

        // Price/nav values
        const tPrice = point.price != null ? Number(point.price) : null;
        const tNav = point.nav != null ? Number(point.nav) : null;
        // T+2 price for premium arbitrage
        const tp2 = chartData[dataIdx + 2];
        const tp2Price = tp2?.price != null ? Number(tp2.price) : null;
        // T+1 NAV for discount arbitrage
        const tp1 = chartData[dataIdx + 1];
        const tp1Nav = tp1?.nav != null ? Number(tp1.nav) : null;

        const capStr = maxCap >= 10000 ? (maxCap/10000).toFixed(2) + '万' : maxCap.toFixed(2) + '元';

        // Calculate both arbitrage profits, pick the higher one
        let bestProfit = null;
        let bestLabel = '';

        // Premium arbitrage: T nav → T+2 price
        let premProfit = null;
        if (tNav && tNav > 0 && tp2Price && tp2Price > 0) {
            const shares = Math.floor(maxCap / tNav);
            const buyAmt = shares * tNav;
            const sellAmt = shares * tp2Price;
            const purchaseFee = buyAmt * purchaseFeePct;
            const sellComm = Math.max(sellAmt * commRate, commMin);
            premProfit = sellAmt - buyAmt - purchaseFee - sellComm;
        }

        // Discount arbitrage: T price → T+1 NAV
        let discProfit = null;
        if (tPrice && tPrice > 0 && tp1Nav && tp1Nav > 0) {
            const shares = Math.floor(maxCap / tPrice);
            const buyAmt2 = shares * tPrice;
            const redeemAmt = shares * tp1Nav;
            const buyComm = Math.max(buyAmt2 * commRate, commMin);
            const redeemFee = redeemAmt * redeemFeePct;
            discProfit = redeemAmt - buyAmt2 - buyComm - redeemFee;
        }

        if (premProfit !== null && (discProfit === null || premProfit >= discProfit)) {
            bestProfit = premProfit;
            bestLabel = '溢价套利';
        } else if (discProfit !== null) {
            bestProfit = discProfit;
            bestLabel = '折价套利';
        }

        const titleText = '套利模拟(投入' + capStr + ')-基于大模型分析';

        let html = '';
        html += '<div class="arb-tooltip-date">' + date + '</div>';

        if (isPrem) {
            html += '<div class="arb-tooltip-row"><span>溢价率</span><span class="' + (point.premium_rate >= 0 ? 'arb-pos' : 'arb-neg') + '">' + (point.premium_rate != null ? (point.premium_rate >= 0 ? '+' : '') + point.premium_rate.toFixed(2) + '%' : '--') + '</span></div>';
        } else {
            html += '<div class="arb-tooltip-row"><span>场内价格</span><span>' + (tPrice != null ? tPrice.toFixed(3) : '--') + '</span></div>';
            html += '<div class="arb-tooltip-row"><span>场外净值</span><span>' + (tNav != null ? tNav.toFixed(3) : '--') + '</span></div>';
        }

        html += '<div class="arb-tooltip-sep"></div>';
        html += '<div class="arb-tooltip-title">' + titleText + '</div>';

        // 数据不足：任一套利方向无法计算即视为数据不足
        if (premProfit === null || discProfit === null) {
            html += '<div class="arb-tooltip-row"><span>数据不足</span><span>缺少后续价格/净值</span></div>';
        } else if (bestProfit > 0) {
            html += '<div class="arb-tooltip-row arb-tooltip-profit"><span>' + bestLabel + ' 预计收益</span><span class="arb-pos">+' + bestProfit.toFixed(2) + '元</span></div>';
        } else {
            html += '<div class="arb-tooltip-row arb-tooltip-profit"><span>不建议操作</span><span class="arb-neg">无正收益机会</span></div>';
        }

        html += '<div class="arb-tooltip-disclaimer">所有预估收益为理论计算结果，不产生任何收益保证</div>';
        el.innerHTML = html;
        el.style.display = 'block';
    }

    _toggleFeeBreakdown() {
        const breakdown = document.getElementById('fdFeeBreakdown');
        if (!breakdown) return;
        const isOpen = breakdown.classList.contains('show');
        if (isOpen) {
            breakdown.classList.remove('show');
            return;
        }
        const est = this._detailEstProfit;
        if (!est) return;
        const bd = est.breakdown;
        let rows = '';
        if (bd.premiumRate !== undefined) {
            rows += '<tr><td class="fd-fee-label">溢价率</td><td class="fd-fee-val fd-pos">+' + bd.premiumRate.toFixed(2) + '%</td></tr>';
            rows += '<tr><td class="fd-fee-label">申购费率</td><td class="fd-fee-val fd-neg">-' + bd.purchaseFeeRate.toFixed(2) + '%</td></tr>';
            rows += '<tr><td class="fd-fee-label">卖出佣金率' + (bd.isMinCommission ? '(最低收费)' : '') + '</td><td class="fd-fee-val fd-neg">-' + bd.sellCommissionRate.toFixed(4) + '%</td></tr>';
            rows += '<tr class="fd-fee-sep"><td colspan="2"></td></tr>';
            rows += '<tr class="fd-fee-total"><td>预计收益率</td><td class="fd-fee-val ' + (est.rate > 0 ? 'fd-pos' : 'fd-neg') + '">' + (est.rate > 0 ? '+' : '') + est.rate.toFixed(2) + '%</td></tr>';
        } else if (bd.discountRate !== undefined) {
            rows += '<tr><td class="fd-fee-label">折价率</td><td class="fd-fee-val fd-pos">+' + bd.discountRate.toFixed(2) + '%</td></tr>';
            rows += '<tr><td class="fd-fee-label">买入佣金率' + (bd.isMinCommission ? '(最低收费)' : '') + '</td><td class="fd-fee-val fd-neg">-' + bd.buyCommissionRate.toFixed(4) + '%</td></tr>';
            rows += '<tr><td class="fd-fee-label">赎回费率</td><td class="fd-fee-val fd-neg">-' + bd.redemptionFeeRate.toFixed(2) + '%</td></tr>';
            rows += '<tr class="fd-fee-sep"><td colspan="2"></td></tr>';
            rows += '<tr class="fd-fee-total"><td>预计收益率</td><td class="fd-fee-val ' + (est.rate > 0 ? 'fd-pos' : 'fd-neg') + '">' + (est.rate > 0 ? '+' : '') + est.rate.toFixed(2) + '%</td></tr>';
        }
        if (rows) {
            rows += '<tr class="fd-fee-disclaimer"><td colspan="2">所有预估收益为理论计算结果，不产生任何收益保证</td></tr>';
            breakdown.innerHTML = '<table class="fd-fee-table"><tbody>' + rows + '</tbody></table>';
            breakdown.classList.add('show');
        }
    }

    _showChartInfoTip(type) {
        const existing = document.querySelector('.fd-custom-tip');
        if (existing) existing.remove();

        const tips = {
            price: '场内价格 = 基金在证券交易所的实时成交价，随买卖供需波动',
            nav: '场外净值 = 基金公司公布的每日单位净值（盘后正式/盘中估算），反映基金持仓的真实价值'
        };
        const text = tips[type] || '';
        if (!text) return;

        const tip = document.createElement('div');
        tip.className = 'fd-custom-tip';
        tip.textContent = text;
        document.querySelector('.fund-detail-modal')?.appendChild(tip);
        setTimeout(() => tip.remove(), 4000);
    }

    formatTime(isoString) {
        if (!isoString) return '-';
        // 服务端返回 UTC 时间（含 +00:00 时区标记），JS 自动转本地时间
        return new Date(isoString).toLocaleString('zh-CN', {
            month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit',
            timeZone: 'Asia/Shanghai',
        });
    }
}

document.addEventListener('DOMContentLoaded', () => { window.lofMonitor = new LofFundMonitor(); });
