# -*- coding: utf-8 -*-
"""
配置文件
"""
import os


class Config:
    """应用配置"""

    # Flask
    # Railway 兼容
    HOST       = os.getenv("HOST", "0.0.0.0")
    PORT       = int(os.getenv("PORT", os.getenv("RAILWAY_PORT", 5000)))
    DEBUG      = os.getenv("DEBUG", "false").lower() == "true"

    # 数据刷新间隔（秒），默认 5 分钟
    REFRESH_INTERVAL_SECONDS = int(os.getenv("REFRESH_INTERVAL", 300))

    # 天天基金网净值/估算净值 API（免费公开，无需Key）
    FUND_NAV_URL = "https://fundgz.1234567.com.cn/js/{code}.js"

    # 东方财富 push2 场内基金行情 API
    # m:0+t:9 = 深交所场内基金, m:1+t:9 = 上交所场内基金
    # 包含 LOF + ETF（需在代码层按代码前缀过滤出真正的LOF）
    MARKET_FUND_BASE = "http://push2.eastmoney.com/api/qt/clist/get"

    # 请求超时（秒）
    REQUEST_TIMEOUT = 10

    # 日志
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
