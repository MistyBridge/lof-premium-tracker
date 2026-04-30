const config = require('./config');

/**
 * LOF基金监控 - 请求封装
 * 开发环境：使用本地服务器 IP 地址（小程序不支持 localhost）
 */
const BASE_URL = config.baseUrl;

/**
 * 通用请求方法
 * @param {string} path - 接口路径（如 /api/funds）
 * @param {object} params - query 参数对象
 * @param {string} method - GET | POST
 * @returns {Promise}
 */
function request(path, params = {}, method = 'GET') {
  return new Promise((resolve, reject) => {
    const url = BASE_URL + path;
    wx.request({
      url,
      method,
      data: params,
      header: {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
      },
      success(res) {
        if (res.statusCode === 200) {
          const body = res.data;
          if (body.code === 0) {
            resolve(body.data);
          } else {
            wx.showToast({ title: body.message || '数据加载失败', icon: 'none' });
            reject(body);
          }
        } else {
          wx.showToast({ title: '服务器异常', icon: 'none' });
          reject(res);
        }
      },
      fail(err) {
        wx.showToast({ title: '请求失败，请检查网络', icon: 'none' });
        reject(err);
      }
    });
  });
}

// 导出接口方法
module.exports = {
  BASE_URL,
  // 健康检查
  getHealth: () => request('/health'),
  // 全量基金列表
  getFunds: (page = 1, pageSize = 50, sort = 'premium_rate', order = 'desc', search = '') => {
    const params = { page, page_size: pageSize, sort, order };
    if (search) params.search = search;
    return request('/api/funds', params);
  },
  // 单只基金详情
  getFundDetail: (code) => request(`/api/funds/${code}`),
  // 排行榜
  getRankings: (type = 'premium', limit = 20) =>
    request('/api/rankings', { type, limit }),
  // 折价排行
  getDiscountRankings: (limit = 20) =>
    request('/api/rankings', { type: 'discount', limit }),
  // 手动刷新数据
  refresh: () => request('/refresh', {}, 'POST'),
};
