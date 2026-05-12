# -*- coding: utf-8 -*-
"""
数据源插件包
"""
from datasource.base import LOFDataSource
from datasource.legacy import LegacySource
from datasource.ak_share import AkShareSource
from datasource.manager import DataSourceManager, get_datasource_manager

__all__ = [
    "LOFDataSource",
    "LegacySource",
    "AkShareSource",
    "DataSourceManager",
    "get_datasource_manager",
]
