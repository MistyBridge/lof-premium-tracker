# -*- coding: utf-8 -*-
"""
25个字段白名单 + 元数据 + JSON导出
"""
import json
from typing import Dict, Set, Any

# ============================================================
# 字段白名单（25个，7组）
# ============================================================

ALLOWED_FIELDS: Dict[str, Dict[str, Any]] = {
    # 行情
    "open": {"label": "开盘价", "type": "float", "group": "行情"},
    "high": {"label": "最高价", "type": "float", "group": "行情"},
    "low": {"label": "最低价", "type": "float", "group": "行情"},
    "close": {"label": "收盘价", "type": "float", "group": "行情"},
    "volume": {"label": "成交量（手）", "type": "float", "group": "行情"},
    "amount": {"label": "成交额", "type": "float", "group": "行情"},
    "change_pct": {"label": "涨跌幅(%)", "type": "float", "group": "行情"},
    
    # 净值
    "nav": {"label": "单位净值", "type": "float", "group": "净值"},
    
    # 溢价
    "premium_rate": {"label": "收盘溢价率(%)", "type": "float", "group": "溢价"},
    "realtime_price": {"label": "实时成交价", "type": "float", "group": "溢价"},
    "realtime_nav": {"label": "盘中估值", "type": "float", "group": "溢价"},
    "realtime_premium": {"label": "盘中溢价率(%)", "type": "float", "group": "溢价"},
    "premium_3d": {"label": "三日均溢(%)", "type": "float", "group": "溢价"},
    
    # 流动性
    "turnover_rate": {"label": "换手率(%)", "type": "float", "group": "流动性"},
    "volume_ratio": {"label": "量比", "type": "float", "group": "流动性"},
    "float_share": {"label": "流通份额（万份）", "type": "float", "group": "流动性"},
    "total_share": {"label": "总份额（万份）", "type": "float", "group": "流动性"},
    
    # 涨跌停
    "limit_up": {"label": "涨停价", "type": "float", "group": "涨跌停"},
    "limit_down": {"label": "跌停价", "type": "float", "group": "涨跌停"},
    
    # 基础
    "aum": {"label": "基金规模（亿）", "type": "float", "group": "基础"},
    "redeem_days": {"label": "赎回到账天数", "type": "int", "group": "基础"},
    
    # 费率
    "purchase_fee": {"label": "申购费率(%)", "type": "float", "group": "费率"},
    "redeem_fee": {"label": "赎回费率(%)", "type": "float", "group": "费率"},
    "purchase_limit": {"label": "申购限额", "type": "float", "group": "费率"},
}

# 字段ID集合（用于快速查找）
ALLOWED_FIELD_IDS: Set[str] = set(ALLOWED_FIELDS.keys())

# ============================================================
# 安全函数白名单
# ============================================================

SAFE_FUNCTIONS: Dict[str, Dict[str, Any]] = {
    "abs": {"label": "绝对值", "min_args": 1, "max_args": 1},
    "max": {"label": "最大值", "min_args": 2, "max_args": None},  # None表示不限制
    "min": {"label": "最小值", "min_args": 2, "max_args": None},
    "round": {"label": "四舍五入", "min_args": 1, "max_args": 2},
    "ifnone": {"label": "空值替换", "min_args": 2, "max_args": 2},
}

SAFE_FUNCTION_NAMES: Set[str] = set(SAFE_FUNCTIONS.keys())


def export_fields_json() -> str:
    """
    导出字段定义为JSON字符串
    
    用途：
    - 前端构建时获取字段定义
    - 保证前后端字段定义一致
    """
    export_data = {
        "fields": ALLOWED_FIELDS,
        "functions": SAFE_FUNCTIONS,
    }
    return json.dumps(export_data, ensure_ascii=False, indent=2)


def get_field_group(field_id: str) -> str:
    """获取字段所属分组"""
    field = ALLOWED_FIELDS.get(field_id)
    return field["group"] if field else "未知"


def get_fields_by_group(group: str) -> Dict[str, Dict[str, Any]]:
    """按分组获取字段"""
    return {
        field_id: field_info 
        for field_id, field_info in ALLOWED_FIELDS.items() 
        if field_info["group"] == group
    }
