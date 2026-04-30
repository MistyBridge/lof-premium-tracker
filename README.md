# LOF基金数据服务

> A股场内LOF基金实时行情 + 净值/估值 + 溢价率分析 RESTful API

## 功能特性

| 功能 | 说明 |
|------|------|
| 全量LOF基金列表 | 采集沪深两市所有场内LOF基金 |
| 实时交易价格 | 东方财富实时行情推送 |
| 估算净值/正式净值 | 天天基金网盘后估值（15:30前）+ 盘后正式净值（15:30后） |
| 溢价率自动计算 | `(现价-净值)/净值×100%`，精确到小数点后3位 |
| 5分钟级定时刷新 | APScheduler 后台定时，数据稳定更新 |
| RESTful API | JSON格式输出，支持分页/排序/筛选/搜索 |

## 数据源（全部免费·无需Key·无需翻墙）

- **沪市LOF 实时价格**: `push2delay.eastmoney.com`（东方财富行情延迟API，`m:1+t:9`）
- **深市LOF 实时价格**: `qt.gtimg.cn`（腾讯行情，支持沪深全量基金代码）
- **基金净值/估算净值**: `fundgz.1234567.com.cn`（天天基金网）

---

## 📦 Windows 安装包

现已支持 Windows 10 一键安装！

### 下载地址
- **ZIP便携版**: `dist/LOF基金服务_v1.0.0_Windows.zip` (~18.6MB)
- **专业安装包**: 需先安装 [Inno Setup 6](https://jrsoftware.org/isdownload.php)，然后运行 `installer/setup.iss`

### 安装方法
1. 解压ZIP文件到任意目录
2. 双击 `启动服务.bat`
3. 浏览器自动打开前端页面

详见 [installer/README.md](installer/README.md)

---

## 快速启动

### 1. 安装依赖

```bash
pip install flask requests apscheduler flask-cors
```

> 如果 `pip` 命令不可用，使用：
> ```bash
> py -3 -m pip install flask requests apscheduler flask-cors
> ```

### 2. 启动服务

```bash
cd lof-fund-service
python app.py
```

首次启动会自动拉取全量数据（约需1-2分钟），之后服务立即可用。

### 3. 访问地址

```
服务地址:   http://localhost:5000
健康检查:   http://localhost:5000/health
全量列表:   http://localhost:5000/api/funds
单只详情:   http://localhost:5000/api/funds/166009
溢价排行:   http://localhost:5000/api/rankings
```

---

## 接口文档

### 接口1: 获取全量LOF基金列表

```
GET /api/funds
```

**请求参数**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page` | int | 1 | 页码 |
| `page_size` | int | 100 | 每页数量（最大500） |
| `sort` | string | amount | 排序字段：`amount`/`change_pct`/`premium_rate`/`price`/`code`/`name` |
| `order` | string | desc | 排序方向：`asc`/`desc` |
| `search` | string | - | 按基金代码或名称模糊搜索 |
| `filter` | string | all | 筛选条件：`all`/`premium`/`discount` |

**示例请求**

```bash
# 获取溢价率最高的20只基金
curl "http://localhost:5000/api/funds?sort=premium_rate&order=desc&page_size=20"

# 搜索名称含"中概"的基金
curl "http://localhost:5000/api/funds?search=中概&page_size=50"

# 获取折价基金（第2页，每页50条）
curl "http://localhost:5000/api/funds?filter=discount&sort=premium_rate&order=asc&page=2&page_size=50"
```

**响应示例**

```json
{
  "code": 0,
  "message": "success",
  "data": [
    {
      "code": "166009",
      "name": "中欧盛世成长混合(LOF)",
      "price": 1.856,
      "change_pct": 2.31,
      "volume": 2847391,
      "amount": 5238741.65,
      "nav": 1.8234,
      "nav_date": "2024-01-15 15:30",
      "is_formal_nav": true,
      "premium_rate": 1.789,
      "premium_status": "溢价",
      "change_amount": 0.0421
    }
  ],
  "meta": {
    "page": 1,
    "page_size": 100,
    "total": 486,
    "total_pages": 5,
    "last_fetch": "2024-01-15T14:32:10.123456",
    "data_source": "东方财富 + 天天基金网"
  }
}
```

---

### 接口2: 单只基金详情

```
GET /api/funds/<code>
```

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `code` | string | 6位基金代码，如 `166009` |

**示例请求**

```bash
curl "http://localhost:5000/api/funds/166009"
```

**响应示例**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "code": "166009",
    "name": "中欧盛世成长混合(LOF)",
    "price": 1.856,
    "change_pct": 2.31,
    "volume": 2847391,
    "amount": 5238741.65,
    "volume_w": 28.47,
    "amount_w": 523.87,
    "nav": 1.8234,
    "nav_date": "2024-01-15 15:30",
    "is_formal_nav": true,
    "premium_rate": 1.789,
    "premium_status": "溢价",
    "prev_nav": 1.7823,
    "change_amount": 0.0421
  }
}
```

---

### 接口3: 溢价率排行榜

```
GET /api/rankings
```

**请求参数**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `type` | string | premium | 榜单类型：`premium`=溢价排行 / `discount`=折价排行 |
| `limit` | int | 20 | 返回数量（最大100） |

**示例请求**

```bash
# 溢价率Top10
curl "http://localhost:5000/api/rankings?type=premium&limit=10"

# 折价率Top10
curl "http://localhost:5000/api/rankings?type=discount&limit=10"
```

---

### 接口4: 健康检查

```
GET /health
```

返回服务状态、缓存数量、最后更新时间、错误信息。

### 接口5: 手动触发刷新

```
POST /refresh
```

> ⚠️ 频繁调用可能导致数据源限流，建议通过定时任务自动刷新。

---

## 核心字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | string | 6位基金代码 |
| `name` | string | 基金名称 |
| `price` | float | 最新成交价（元） |
| `change_pct` | float | 涨跌幅（%），正数红色，负数绿色 |
| `volume` | int | 成交量（股） |
| `amount` | float | 成交额（元） |
| `nav` | float | 当前净值（估算净值或盘后正式净值） |
| `nav_date` | string | 净值日期/估算时间 |
| `is_formal_nav` | bool | 是否为盘后正式净值（15:30后为true） |
| `premium_rate` | float | 溢价率（%），正=溢价，负=折价 |
| `premium_status` | string | 溢价状态：`溢价`/`折价`/`平价` |
| `change_amount` | float | 涨跌额（元） |

---

## 溢价率计算公式

```
溢价率 = (现价 - 净值) / 净值 × 100%

示例：
  现价 = 1.856元，净值 = 1.8234元
  溢价率 = (1.856 - 1.8234) / 1.8234 × 100% = +1.789%
  → 溢价状态：溢价

  现价 = 1.800元，净值 = 1.8234元
  溢价率 = (1.800 - 1.8234) / 1.8234 × 100% = -1.283%
  → 溢价状态：折价
```

---

## 定时刷新说明

- 默认刷新间隔：**300秒（5分钟）**
- 修改方法：设置环境变量 `REFRESH_INTERVAL`
  ```bash
  # 设为3分钟（180秒）
  set REFRESH_INTERVAL=180
  python app.py
  ```
- 数据新鲜度：
  - **交易时段（9:30-15:00）**：价格实时，净值为上一交易日收盘净值+估算涨跌幅
  - **盘后（15:00-15:30）**：价格实时，净值更新为当日正式净值
  - **非交易时段**：价格停止更新，净值数据为最新可用

---

## 错误码

| code | 说明 |
|------|------|
| 0 | 成功 |
| 1 | 通用错误 |
| 2 | 数据刷新失败 |
| 3 | 数据未就绪（服务启动中） |
| 4 | 参数错误（分页参数） |
| 5 | 参数错误（sort字段不合法） |
| 6 | 参数错误（order字段不合法） |
| 7 | 基金代码不存在 |
| 8 | 参数错误（limit字段不合法） |

---

## 部署方式

### 方式1：直接运行（开发/测试）
```bash
python app.py
```

### 方式2：生产环境（Gunicorn）
```bash
pip install gunicorn
gunicorn -w 2 -b 0.0.0.0:5000 app:app
```

### 方式3：Docker 部署
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt --no-cache-dir
COPY . .
CMD ["python", "app.py"]
```

### 方式4：Windows 计划任务（定时启动）
```powershell
# 创建启动脚本 run.bat
@echo off
cd /d "%~dp0"
py -3 app.py
```

---

## 项目结构

```
lof-fund-service/
├── app.py            # Flask应用 + API路由 + 定时调度
├── data_fetcher.py   # 数据采集模块（东方财富 + 天天基金网）
├── config.py         # 配置文件（URL、超时、间隔等）
├── requirements.txt  # Python依赖
└── README.md         # 本文档
```

---

## 注意事项

1. **首次启动慢**：全量拉取约需1-2分钟，接口返回503是正常的，稍后重试即可
2. **数据源限流**：东方财富API有频率限制，不要频繁手动调用 `/refresh`
3. **非交易时段**：价格停止更新，但净值/估值数据持续可用
4. **数据准确性**：估算净值仅供参考，正式净值以基金公司披露为准
5. **无防火墙拦截**：东方财富和天天基金网API无需认证，无CORS限制
