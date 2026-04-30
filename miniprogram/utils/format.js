/**
 * LOF基金监控 - 格式化工具
 */

/**
 * 格式化价格（保留2位小数）
 */
function formatPrice(val) {
  if (val === null || val === undefined) return '--';
  return Number(val).toFixed(2);
}

/**
 * 格式化溢价率（保留2位小数，带百分号）
 */
function formatPremiumRate(rate) {
  if (rate === null || rate === undefined) return '--';
  const val = Number(rate).toFixed(2);
  return (rate > 0 ? '+' : '') + val + '%';
}

/**
 * 溢价率颜色 class
 */
function getPremiumClass(rate) {
  if (rate === null || rate === undefined) return '';
  if (rate > 0) return 'premium-positive';
  if (rate < 0) return 'premium-negative';
  return 'premium-zero';
}

/**
 * 格式化成交额
 */
function formatAmount(amountW) {
  if (amountW === null || amountW === undefined) return '--';
  if (amountW >= 10000) {
    return (amountW / 10000).toFixed(2) + '亿';
  }
  return Number(amountW).toFixed(2) + '万';
}

/**
 * 格式化涨跌幅（带符号和百分号）
 */
function formatChangePct(pct) {
  if (pct === null || pct === undefined) return '--';
  const val = Number(pct).toFixed(2);
  return (pct >= 0 ? '+' : '') + val + '%';
}

/**
 * 格式化时间
 */
function formatTime(isoStr) {
  if (!isoStr) return '--';
  return isoStr.replace('T', ' ').substring(0, 16);
}

/**
 * 净值类型标签
 */
function getNavTypeLabel(isFormalNav) {
  if (isFormalNav === true) return '正式净值';
  if (isFormalNav === false) return '估算净值';
  return '--';
}

module.exports = {
  formatPrice,
  formatPremiumRate,
  getPremiumClass,
  formatAmount,
  formatChangePct,
  formatTime,
  getNavTypeLabel
};
