// 配置文件
const ENV = 'dev'; // dev | prod

const CONFIG = {
  dev: {
    baseUrl: 'http://66.183.217.91:5000',  // 本机IP调试
    refreshInterval: 300000  // 5分钟
  },
  prod: {
    baseUrl: 'https://your-domain.com',  // 线上域名，部署后替换
    refreshInterval: 300000
  }
};

module.exports = CONFIG[ENV];
