# -*- coding: utf-8 -*-
"""
数据源抽象基类
所有数据源插件必须实现此接口
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any


class LOFDataSource(ABC):
    """LOF 基金数据源抽象基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """数据源名称，用于日志标识"""
        ...

    @abstractmethod
    def fetch_all_prices(self) -> Dict[str, dict]:
        """
        获取全市场 LOF 基金实时行情。
        返回: {code: {code, name, price, change_pct, volume, amount}, ...}
        """
        ...

    @abstractmethod
    def fetch_single_nav(self, code: str) -> Dict[str, Any]:
        """
        获取单只基金净值/估算净值。
        返回: {nav: float|None, nav_date: str|None, prev_nav: float|None,
               is_formal_nav: bool, can_purchase: bool|None}
        """
        ...

    @abstractmethod
    def fetch_nav_batch(self, funds: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        批量获取基金净值/估算净值。
        funds: [{code, name, price, ...}, ...]
        返回: {code: {**fund, nav, nav_date, prev_nav, is_formal_nav, can_purchase}, ...}
        """
        ...

    @abstractmethod
    def fetch_kline(self, code: str, start_date: str, end_date: str) -> Dict[str, dict]:
        """
        获取单只基金日K线数据。
        start_date/end_date: YYYYMMDD 格式
        返回: {date: {price, amount, change_pct, name}, ...}
        """
        ...

    @abstractmethod
    def fetch_nav_history(self, code: str, start_date: str, end_date: str) -> Dict[str, float]:
        """
        获取单只基金历史净值。
        start_date/end_date: YYYY-MM-DD 格式
        返回: {date: nav_value, ...}
        """
        ...

    def health_check(self) -> bool:
        """检查数据源是否可用，默认返回 True"""
        return True
