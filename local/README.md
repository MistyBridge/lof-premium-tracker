# 本地 HTML 访问版本

这是 LOF 基金监控系统的本地版本，可以直接在浏览器中打开使用。

## 使用方法

### 方式1：独立使用（需要后端服务）
1. 双击 `index.html` 打开
2. 系统会自动检测本地环境并连接到 `http://localhost:5000`
3. 需要先启动后端服务

### 方式2：配合后端使用
1. 下载 [get-lof-test](https://github.com/woredasdnmv/get-lof-test) 仓库
2. 启动后端服务：
   ```bash
   cd backend/
   python app.py
   ```
3. 打开本目录的 `index.html`

## 配置说明

`js/config.js` 已配置为自动检测：
- 本地环境（localhost/127.0.0.1）→ 连接 `http://localhost:5000`
- 其他环境 → 使用同源代理

## 自定义后端地址

可以通过 URL 参数指定后端地址：
```
index.html?api=http://192.168.1.100:5000
```

## 文件结构

```
local/
├── index.html      # 主页面
├── css/
│   └── style.css   # 样式
└── js/
    ├── config.js   # 配置（自动检测环境）
    ├── api.js      # API封装
    └── app.js     # 主逻辑
```
