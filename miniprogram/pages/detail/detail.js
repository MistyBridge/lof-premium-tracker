const api = require('../../utils/request');
const fmt = require('../../utils/format');

Page({
  data: {
    code: '',
    fund: null,
    loading: true,
    chartDays: 7,
    chartData: [],
    chartWidth: 0,
    chartHeight: 400,
  },

  onLoad(query) {
    const code = query.code || '';
    this.setData({ code });
    this.loadDetail(code);
    this.loadChart(code, 7);
    const sysInfo = wx.getSystemInfoSync();
    const rpxRatio = sysInfo.windowWidth / 750;
    this.setData({
      chartWidth: sysInfo.windowWidth - 60 * rpxRatio,
      chartHeight: 400 * rpxRatio,
    });
  },

  async loadDetail(code) {
    this.setData({ loading: true });
    try {
      const fund = await api.getFundDetail(code);
      this.setData({ fund, loading: false });
      if (fund && fund.name) {
        wx.setNavigationBarTitle({ title: fund.name });
      }
    } catch (e) {
      this.setData({ loading: false });
      wx.showToast({ title: '加载失败', icon: 'none' });
    }
  },

  loadChart(code, days) {
    api.getFundChart(code, days).then(result => {
      const chart = result.chart || [];
      this.setData({ chartData: chart, chartDays: days }, () => {
        if (chart.length > 0) {
          this.drawChart();
        }
      });
    }).catch(() => {});
  },

  switchRange(e) {
    const days = parseInt(e.currentTarget.dataset.days);
    if (days === this.data.chartDays) return;
    this.setData({ chartDays: days });
    this.loadChart(this.data.code, days);
  },

  drawChart() {
    const query = wx.createSelectorQuery();
    query.select('#detailChart')
      .fields({ node: true, size: true })
      .exec((res) => {
        if (!res[0] || !res[0].node) return;
        const canvas = res[0].node;
        const ctx = canvas.getContext('2d');
        const dpr = wx.getSystemInfoSync().pixelRatio;
        const width = res[0].width;
        const height = res[0].height;

        canvas.width = width * dpr;
        canvas.height = height * dpr;
        ctx.scale(dpr, dpr);

        this._renderChart(ctx, width, height);
      });
  },

  _renderChart(ctx, w, h) {
    const data = this.data.chartData;
    if (!data || data.length === 0) return;

    const pad = { top: 20, right: 16, bottom: 36, left: 54 };
    const pw = w - pad.left - pad.right;
    const ph = h - pad.top - pad.bottom;

    const prices = data.map(d => d.price != null ? Number(d.price) : null);
    const navs = data.map(d => d.nav != null ? Number(d.nav) : null);
    const allVals = prices.concat(navs).filter(v => v != null);
    if (allVals.length === 0) return;

    const yMin = Math.floor(Math.min(...allVals) * 0.995 * 1000) / 1000;
    const yMax = Math.ceil(Math.max(...allVals) * 1.005 * 1000) / 1000;
    const yRange = yMax - yMin || 1;
    const xStep = pw / Math.max(data.length - 1, 1);

    const xPos = (i) => pad.left + i * xStep;
    const yPos = (v) => pad.top + ph - ((v - yMin) / yRange) * ph;

    // Clear
    ctx.clearRect(0, 0, w, h);

    // Grid lines
    const gridLines = 5;
    ctx.strokeStyle = '#e8e8e8';
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= gridLines; i++) {
      const y = pad.top + (ph / gridLines) * i;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(pad.left + pw, y);
      ctx.stroke();
    }

    // Y-axis labels
    ctx.fillStyle = '#999';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'right';
    for (let i = 0; i <= gridLines; i++) {
      const val = yMin + (yRange / gridLines) * (gridLines - i);
      const y = pad.top + (ph / gridLines) * i;
      ctx.fillText(val.toFixed(3), pad.left - 6, y + 3);
    }

    // X-axis labels (sparse for long range)
    const labelStep = data.length > 60 ? Math.ceil(data.length / 10) : 1;
    ctx.textAlign = 'center';
    ctx.fillStyle = '#999';
    ctx.font = '10px sans-serif';
    for (let i = 0; i < data.length; i += labelStep) {
      const label = data[i].date.slice(5);
      ctx.fillText(label, xPos(i), h - pad.bottom + 16);
    }

    // Draw lines
    this._drawLine(ctx, data, 'price', xPos, yPos, '#ff7a45', pw);
    this._drawLine(ctx, data, 'nav', xPos, yPos, '#40a9ff', pw);
  },

  _drawLine(ctx, data, field, xPos, yPos, color) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < data.length; i++) {
      const val = data[i][field];
      if (val == null) continue;
      const x = xPos(i);
      const y = yPos(Number(val));
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    }
    ctx.stroke();

    // Dots (skip for yearly to avoid clutter)
    if (data.length <= 60) {
      for (let i = 0; i < data.length; i++) {
        const val = data[i][field];
        if (val == null) continue;
        const x = xPos(i);
        const y = yPos(Number(val));
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(x, y, 2.5, 0, 2 * Math.PI);
        ctx.fill();
      }
    }
  },

  // ── Utility methods ──
  copyCode() {
    wx.setClipboardData({
      data: this.data.code,
      success: () => {
        wx.showToast({ title: '已复制代码', icon: 'success' });
      }
    });
  },

  goBack() {
    wx.navigateBack({ delta: 1 });
  },

  formatPrice: fmt.formatPrice,
  formatPremiumRate: fmt.formatPremiumRate,
  getPremiumClass: fmt.getPremiumClass,
  formatAmount: fmt.formatAmount,
  formatChangePct: fmt.formatChangePct,
  formatTime: fmt.formatTime,
  getNavTypeLabel: fmt.getNavTypeLabel,
  formatPurchaseLimit(limit) {
    if (limit == null) return '不限额';
    if (limit >= 10000) return (limit / 10000).toFixed(0) + '万';
    return limit.toFixed(0) + '元';
  },

  getPremiumColor(rate) {
    if (rate === null || rate === undefined) return '#333';
    if (rate > 0) return '#e74c3c';
    if (rate < 0) return '#27ae60';
    return '#333';
  }
});
