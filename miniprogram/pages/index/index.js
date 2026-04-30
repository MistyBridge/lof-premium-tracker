const api = require('../../utils/request');
const fmt = require('../../utils/format');
const config = require('../../utils/config');

Page({
  data: {
    // 统计卡片
    fundCount: '--',
    maxPremium: '--',
    minDiscount: '--',
    lastFetch: '--',
    // 列表数据
    fundList: [],
    allFunds: [],       // 全量缓存（本地搜索用）
    // 搜索 & 排序
    keyword: '',
    sortField: 'premium_rate',
    sortOrder: 'desc',
    sortOptions: [
      { field: 'premium_rate', label: '溢价率' },
      { field: 'amount', label: '成交额' },
      { field: 'price', label: '现价' },
      { field: 'change_pct', label: '涨跌幅' }
    ],
    activeSortIndex: 0,
    // 状态
    loading: true,
    refreshing: false,
    searchFocused: false,
    // 自动刷新
    refreshTimer: null
  },

  onLoad() {
    this.init();
  },

  onShow() {
    this.startAutoRefresh();
  },

  onHide() {
    this.stopAutoRefresh();
  },

  onUnload() {
    this.stopAutoRefresh();
  },

  // 下拉刷新
  onPullDownRefresh() {
    this.handleRefresh().finally(() => {
      wx.stopPullDownRefresh();
    });
  },

  // 初始化
  async init() {
    this.setData({ loading: true });
    try {
      await Promise.all([
        this.loadStats(),
        this.loadFunds()
      ]);
    } catch (e) {
      console.error('[LOF] 初始化失败:', e);
    } finally {
      this.setData({ loading: false });
    }
  },

  // 加载统计信息
  async loadStats() {
    try {
      const health = await api.getHealth();
      const funds = this.data.allFunds.length > 0 ? this.data.allFunds : [];
      // 计算最高溢价和最低折价
      let maxPrem = null;
      let minDisc = null;
      funds.forEach(f => {
        if (f.premium_rate !== null && f.premium_rate !== undefined) {
          if (f.premium_rate > 0) {
            if (maxPrem === null || f.premium_rate > maxPrem) maxPrem = f.premium_rate;
          }
          if (f.premium_rate < 0) {
            if (minDisc === null || f.premium_rate < minDisc) minDisc = f.premium_rate;
          }
        }
      });
      this.setData({
        fundCount: health.cache_count || funds.length || '--',
        lastFetch: fmt.formatTime(health.last_fetch),
        maxPremium: maxPrem !== null ? fmt.formatPremiumRate(maxPrem) : '--',
        minDiscount: minDisc !== null ? fmt.formatPremiumRate(minDisc) : '--'
      });
    } catch (e) {
      console.error('[LOF] 健康检查失败:', e);
    }
  },

  // 加载基金列表（全量）
  async loadFunds() {
    try {
      // 一次拉取全量数据（page_size=600 足够覆盖所有LOF基金）
      const data = await api.getFunds(1, 600, this.data.sortField, this.data.sortOrder, '');
      const funds = Array.isArray(data) ? data : (data.data || []);
      // 过滤无效数据
      const validFunds = funds.filter(f =>
        f.premium_rate !== null && f.premium_rate !== undefined &&
        f.premium_rate > -50 && f.premium_rate < 50
      );
      this.setData({
        allFunds: validFunds,
        fundList: this.applySearchAndSort(validFunds)
      });
      // 更新统计
      this.recalcStats(validFunds);
    } catch (e) {
      console.error('[LOF] 加载基金列表失败:', e);
      wx.showToast({ title: '数据加载失败', icon: 'none' });
    }
  },

  // 重新计算统计
  recalcStats(funds) {
    let maxPrem = null;
    let minDisc = null;
    funds.forEach(f => {
      if (f.premium_rate > 0) {
        if (maxPrem === null || f.premium_rate > maxPrem) maxPrem = f.premium_rate;
      }
      if (f.premium_rate < 0) {
        if (minDisc === null || f.premium_rate < minDisc) minDisc = f.premium_rate;
      }
    });
    this.setData({
      fundCount: funds.length,
      maxPremium: maxPrem !== null ? fmt.formatPremiumRate(maxPrem) : '--',
      minDiscount: minDisc !== null ? fmt.formatPremiumRate(minDisc) : '--'
    });
  },

  // 搜索 + 排序
  applySearchAndSort(funds) {
    let list = [...funds];
    // 搜索过滤
    if (this.data.keyword) {
      const kw = this.data.keyword.toLowerCase();
      list = list.filter(f =>
        f.code.toLowerCase().includes(kw) ||
        f.name.toLowerCase().includes(kw)
      );
    }
    // 排序
    const field = this.data.sortField;
    const order = this.data.sortOrder;
    list.sort((a, b) => {
      const va = a[field] ?? 0;
      const vb = b[field] ?? 0;
      return order === 'asc' ? va - vb : vb - va;
    });
    return list;
  },

  // 搜索输入
  onSearchInput(e) {
    this.setData({ keyword: e.detail.value.trim() });
    // 本地搜索，防抖
    if (this._searchTimer) clearTimeout(this._searchTimer);
    this._searchTimer = setTimeout(() => {
      this.setData({
        fundList: this.applySearchAndSort(this.data.allFunds)
      });
    }, 300);
  },

  // 清空搜索
  onClearSearch() {
    this.setData({ keyword: '' });
    this.setData({
      fundList: this.applySearchAndSort(this.data.allFunds)
    });
  },

  // 搜索聚焦
  onSearchFocus() {
    this.setData({ searchFocused: true });
  },

  // 搜索失焦
  onSearchBlur() {
    this.setData({ searchFocused: false });
  },

  // 切换排序字段
  onSortTap(e) {
    const idx = e.currentTarget.dataset.index;
    const opt = this.data.sortOptions[idx];
    if (this.data.sortField === opt.field) {
      // 同字段切换升降序
      this.setData({
        sortOrder: this.data.sortOrder === 'desc' ? 'asc' : 'desc'
      });
    } else {
      this.setData({
        sortField: opt.field,
        sortOrder: 'desc',
        activeSortIndex: idx
      });
    }
    this.setData({
      fundList: this.applySearchAndSort(this.data.allFunds)
    });
  },

  // 手动刷新
  async handleRefresh() {
    this.setData({ refreshing: true });
    try {
      await api.refresh();
      // 等待后端刷新完成
      await new Promise(r => setTimeout(r, 3000));
      await this.loadFunds();
      await this.loadStats();
      wx.showToast({ title: '刷新成功', icon: 'success' });
    } catch (e) {
      wx.showToast({ title: '刷新失败', icon: 'none' });
    } finally {
      this.setData({ refreshing: false });
    }
  },

  // 跳转详情
  goDetail(e) {
    const code = e.currentTarget.dataset.code;
    wx.navigateTo({ url: `/pages/detail/detail?code=${code}` });
  },

  // 格式化方法（供 wxml 使用）
  formatPrice: fmt.formatPrice,
  formatPremiumRate: fmt.formatPremiumRate,
  getPremiumClass: fmt.getPremiumClass,
  formatAmount: fmt.formatAmount,
  formatChangePct: fmt.formatChangePct,

  // 自动刷新（5分钟）
  startAutoRefresh() {
    this.stopAutoRefresh();
    this._refreshTimer = setInterval(() => {
      if (!this.data.loading && !this.data.refreshing) {
        this.loadFunds();
        this.loadStats();
      }
    }, config.refreshInterval);
  },

  stopAutoRefresh() {
    if (this._refreshTimer) {
      clearInterval(this._refreshTimer);
      this._refreshTimer = null;
    }
  }
});
