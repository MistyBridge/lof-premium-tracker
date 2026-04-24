# LOF基金服务 - Windows 安装包

本目录包含 Windows 安装包的构建脚本和配置文件。

## 📦 已生成的分发包

### ZIP便携版（已生成）
- **文件**: `dist/LOF基金服务_v1.0.0_Windows.zip`
- **大小**: ~18.6 MB
- **特点**: 解压即用，无需安装

### 专业安装包（需安装Inno Setup）
- **脚本**: `installer/setup.iss`
- **要求**: [Inno Setup 6](https://jrsoftware.org/isdownload.php)

## 🚀 快速使用

### 方式一：使用ZIP便携版
1. 解压 `LOF基金服务_v1.0.0_Windows.zip` 到任意目录
2. 双击 `启动服务.bat`
3. 浏览器自动打开 http://localhost:5000

### 方式二：创建专业安装包
1. 下载安装 [Inno Setup 6](https://jrsoftware.org/isdownload.php)
2. 双击打开 `installer/setup.iss`
3. 按 F9 编译生成安装包
4. 输出目录: `installer/output/`

## 📁 目录结构

```
installer/
├── lof_service.spec   # PyInstaller配置
├── setup.iss          # Inno Setup脚本
├── build.bat          # 一键构建脚本
├── 启动服务.bat        # 用户启动脚本
├── 停止服务.bat        # 停止服务脚本
├── 安装说明.txt        # 安装前须知
├── 使用说明.txt        # 安装后指南
└── README.md          # 本文档

dist/
├── LOF基金服务.exe              # 打包后的后端服务
├── LOF基金服务/                 # 完整分发包目录
│   ├── LOF基金服务.exe
│   ├── 启动服务.bat
│   ├── 停止服务.bat
│   ├── 使用说明.txt
│   ├── 安装说明.txt
│   ├── sz_lof_codes.json
│   ├── web/
│   │   ├── index.html
│   │   ├── css/
│   │   └── js/
│   └── docs/
│       ├── README.md
│       └── API文档-*.md
└── LOF基金服务_v1.0.0_Windows.zip  # ZIP分发包
```

## ⚠️ 微信小程序说明

安装包**不包含**微信小程序代码，原因：
- 小程序需通过微信开发者工具上传
- 需在微信后台审核发布

**小程序部署方法**：
1. 用微信开发者工具打开项目根目录的 `miniprogram` 文件夹
2. 修改 `utils/config.js` 中的服务器地址
3. 上传代码并提交审核

## 🔧 开发者信息

### 重新打包
```powershell
# 在项目根目录执行
.\installer\build.bat
```

### 仅打包后端
```powershell
py -m PyInstaller installer/lof_service.spec --noconfirm --clean
```

### 仅创建安装包（需Inno Setup）
```powershell
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer/setup.iss
```

## 📋 系统要求

- Windows 10 或更高版本
- 无需安装 Python（已内置）
- 需要网络连接
- 首次运行需允许防火墙访问

## 📄 License

MIT License
