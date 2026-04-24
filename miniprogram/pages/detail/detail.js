const api = require('../../utils/request');
const fmt = require('../../utils/format');

Page({
  data: {
    code: '',
    fund: null,
    loading: true
  },

  onLoad(query) {
    const code = query.code || '';
    this.setData({ code });
    this.loadDetail(code);
  },

  async loadDetail(code) {
    this.setData({ loading: true });
    try {
      const fund = await api.getFundDetail(code);
      this.setData({ fund, loading: false });
      // 动态标题
      if (fund && fund.name) {
        wx.setNavigationBarTitle({ title: fund.name });
      }
    } catch (e) {
      this.setData({ loading: false });
      wx.showToast({ title: '加载失败', icon: 'none' });
    }
  },

  // 复制基金代码
  copyCode() {
    wx.setClipboardData({
      data: this.data.code,
      success: () => {
        wx.showToast({ title: '已复制代码', icon: 'success' });
      }
    });
  },

  // 返回
  goBack() {
    wx.navigateBack({ delta: 1 });
  },

  // 格式化方法
  formatPrice: fmt.formatPrice,
  formatPremiumRate: fmt.formatPremiumRate,
  getPremiumClass: fmt.getPremiumClass,
  formatAmount: fmt.formatAmount,
  formatChangePct: fmt.formatChangePct,
  formatTime: fmt.formatTime,
  getNavTypeLabel: fmt.getNavTypeLabel,

  // 溢价率颜色
  getPremiumColor(rate) {
    if (rate === null || rate === undefined) return '#333';
    if (rate > 0) return '#e74c3c';
    if (rate < 0) return '#27ae60';
    return '#333';
  }
});
