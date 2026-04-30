# LOF基金监控 - 微信小程序

> A股场内LOF基金实时行情、净值/估值、溢价率监控小程序

## 📁 项目结构

```
lof-fund-miniprogram/
├── app.js              # 小程序入口
├── app.json            # 全局配置
├── app.wxss            # 全局样式
├── project.config.json # 项目配置
├── sitemap.json        # 搜索索引配置
├── utils/
│   ├── config.js       # 环境配置（dev/prod）
│   ├── request.js      # API 请求封装
│   └── format.js       # 格式化工具
├── pages/
│   ├── index/          # 首页（基金列表）
│   │   ├── index.js
│   │   ├── index.wxml
│   │   ├── index.wxss
│   │   └── index.json
│   └── detail/         # 详情页
│       ├── detail.js
│       ├── detail.wxml
│       ├── detail.wxss
│       └── detail.json
└── README.md           # 本文档
```

## 🚀 本地调试

### 1. 启动后端服务

```bash
# 克隆后端仓库
git clone https://github.com/woredasdnmv/get-lof-test.git
cd get-lof-test

# 安装依赖
pip install flask requests apscheduler flask-cors gunicorn

# 启动服务
python app.py
# 服务运行在 http://127.0.0.1:5000
```

### 2. 配置小程序连接本地服务

> ⚠️ 微信开发者工具不支持 `localhost`，需使用本机 IP 地址

1. 查看本机 IP：在终端运行 `ipconfig`（Windows）或 `ifconfig`（Mac）
2. 修改 `utils/config.js` 中的 `baseUrl`：
   ```javascript
   dev: {
     baseUrl: 'http://192.168.x.x:5000',  // 替换为你的本机IP
     refreshInterval: 300000
   }
   ```

### 3. 导入微信开发者工具

1. 打开 **微信开发者工具**
2. 选择「导入项目」
3. 目录选择本项目的根目录（`lof-fund-miniprogram`）
4. AppID 使用测试号或填入你的小程序 AppID
5. 在「详情」→「本地设置」中勾选 **「不校验合法域名」**（本地调试必须）

### 4. 调试运行

- 首页自动加载全量 LOF 基金数据
- 点击基金行进入详情页
- 支持搜索、排序、下拉刷新、5分钟自动轮询

## 🌐 上线部署

### 第一步：后端 HTTPS 部署

微信小程序要求所有请求必须为 HTTPS，需要在服务器上部署后端并配置 SSL。

**方案一：Nginx 反向代理 + Gunicorn**

```bash
# 1. 服务器上安装依赖
apt update && apt install python3 python3-pip nginx -y
pip3 install flask requests apscheduler flask-cors gunicorn

# 2. 上传代码到服务器
scp -r get-lof-test/ user@your-server:/home/www/lof-fund-service/

# 3. 启动 Gunicorn
cd /home/www/lof-fund-service
gunicorn -w 4 -b 127.0.0.1:5000 app:app --daemon

# 4. 配置 Nginx（/etc/nginx/sites-available/lof-fund）
```

Nginx 配置：
```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate     /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
# 5. 启用站点并重启 Nginx
ln -s /etc/nginx/sites-available/lof-fund /etc/nginx/sites-enabled/
nginx -t && nginx -s reload
```

### 第二步：微信公众平台配置

1. 登录 [微信公众平台](https://mp.weixin.qq.com)
2. 进入「开发」→「开发管理」→「开发设置」
3. 在 **服务器域名** → **request 合法域名** 中添加：
   ```
   https://your-domain.com
   ```
4. 保存（域名必须已备案、已配置 SSL）

### 第三步：修改小程序配置

将 `utils/config.js` 切换到生产环境：

```javascript
const ENV = 'prod';  // 改为 prod
```

确认 `baseUrl` 已替换为线上域名：
```javascript
prod: {
  baseUrl: 'https://your-domain.com',
  refreshInterval: 300000
}
```

### 第四步：提交审核与发布

1. 在微信开发者工具中点击「上传」
2. 登录微信公众平台 → 「版本管理」
3. 将开发版提交审核
4. 审核通过后点击「发布」

## 📋 功能清单

| 功能 | 说明 |
|------|------|
| ✅ 统计卡片 | LOF基金总数、最高溢价率、最低折价率 |
| ✅ 全量基金列表 | 代码、名称、现价、净值、溢价率、成交额 |
| ✅ 溢价率标色 | >0 红色、<0 绿色、=0 黑色 |
| ✅ 下拉刷新 | 手动触发数据刷新 |
| ✅ 自动轮询 | 5分钟自动刷新数据 |
| ✅ 搜索 | 基金代码/名称模糊搜索（本地过滤） |
| ✅ 排序 | 按溢价率/成交额/现价/涨跌幅排序，点击切换升降序 |
| ✅ 详情页 | 完整行情数据、净值信息、溢价分析 |
| ✅ 异常处理 | 空数据、加载失败、网络错误友好提示 |
| ✅ 数据过滤 | 自动过滤溢价率 >50% 或 <-30% 的异常数据 |

## 🔑 关键文件说明

| 文件 | 功能 |
|------|------|
| `utils/config.js` | 环境切换（dev/prod）、API地址、刷新间隔 |
| `utils/request.js` | 统一请求封装、错误处理、所有 API 方法 |
| `utils/format.js` | 价格/溢价率/成交额格式化、颜色判断 |
| `pages/index/index.js` | 首页逻辑：数据加载、搜索排序、自动刷新 |
| `pages/detail/detail.js` | 详情页逻辑：单只基金数据加载、复制代码 |

## ⚠️ 注意事项

1. **本地调试**必须关闭「校验合法域名」（开发者工具 → 详情 → 本地设置）
2. **上线前**必须将 `config.js` 的 `ENV` 改为 `'prod'`
3. 后端 API 默认每5分钟自动刷新数据（由 APScheduler 控制）
4. 小程序端也有5分钟轮询，双重保障数据时效性
5. 溢价率超过 ±50% 的数据会被前端自动过滤，避免异常值干扰
