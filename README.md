# LOF 基金折溢价监控 - 用户端代码

<div align="center">

![Version](https://img.shields.io/badge/version-1.2.0-blue.svg)
![Platform](https://img.shields.io/badge/platform-Web%20%7C%20MiniProgram-green.svg)

**多端监控 LOF 基金溢价率，发现套利机会**

[在线演示](https://lof-fund-monitor.pages.dev) · [本地部署](./local/README.md)

</div>

---

## 📖 目录

- [项目简介](#项目简介)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [各端说明](#各端说明)
- [技术栈](#技术栈)
- [部署指南](#部署指南)

---

## 项目简介

本仓库包含 LOF 基金折溢价监控系统的所有用户端代码，支持多种访问方式：

| 端 | 目录 | 说明 |
|---|------|------|
| **PC Web** | `web/` | 完整功能版，适合桌面浏览器 |
| **本地 HTML** | `local/` | 无需服务器，直接打开 HTML |
| **小程序** | `miniprogram/` | 微信小程序版本 |

---

## 目录结构

```
lof-premium-tracker/
├── web/                    # PC端前端
│   ├── index.html
│   ├── css/
│   └── js/
├── local/                  # 本地HTML访问版本
│   ├── index.html
│   ├── css/
│   └── js/
├── miniprogram/            # 微信小程序
│   ├── pages/
│   ├── utils/
│   ├── app.js
│   └── app.json
└── README.md
```

---

## 快速开始

### 在线访问
直接访问：https://lof-fund-monitor.pages.dev

### 本地使用
1. 下载 `local/` 目录
2. 用浏览器打开 `index.html`
3. 需要后端服务支持（见 [本地服务仓库](https://github.com/woredasdnmv/get-lof-test)）

---

## 各端说明

### 🖥️ PC Web（web/）
- 完整表格展示
- 排序、搜索、筛选
- PC端双栏排行
- 5分钟自动刷新

### 📄 本地 HTML（local/）
- 纯静态文件
- 无需构建
- 直接双击打开
- 适合离线使用

### 📱 小程序（miniprogram/）
- 微信小程序版本
- 移动端优化
- 触屏交互友好

---

## 技术栈

| 端 | 技术 |
|---|------|
| Web | HTML5 + CSS3 + Vanilla JS |
| 小程序 | 微信小程序原生框架 |

---

## 部署指南

### Cloudflare Pages 部署
```bash
cd web/
npx wrangler pages deploy . --project-name=lof-fund-monitor
```

### 本地使用
直接下载 `local/` 目录，双击 `index.html` 即可。

---

## 相关仓库

- **本地服务端**：[get-lof-test](https://github.com/woredasdnmv/get-lof-test) - 后端代码 + 本地部署

---

## License

MIT © 2026
