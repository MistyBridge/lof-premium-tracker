"""
请求参数 Pydantic 模型 — 9 个模型 + 排序白名单 + 代码清洗 + 日期校验
"""
from datetime import date, datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from constants import BATCH_CODES_MAX, PAGE_SIZE_MAX, DAILY_QUERY_LIMIT_MAX

# 排序白名单
SORT_WHITELIST = frozenset([
    "premium_rate", "close", "amount", "turnover_rate", "change_pct",
    "nav", "volume", "float_share", "aum", "code", "name",
])


def clean_fund_code(code: str) -> str:
    """基金代码清洗: strip + 去逗号/zfill(6)"""
    code = code.strip().replace(" ", "").replace(",", "").replace("，", "")
    code = code.lstrip("0") or "0"
    return code.zfill(6)


# ── 基金列表 ────────────────────────────────────────────────


class FundListRequest(BaseModel):
    page: int = Field(1, ge=1, description="页码")
    size: int = Field(50, ge=1, le=PAGE_SIZE_MAX, description="每页条数")
    sort: str = Field("amount", description="排序字段")
    order: str = Field("desc", description="排序方向")
    premium_min: Optional[float] = Field(None, description="最低溢价率")
    premium_max: Optional[float] = Field(None, description="最高溢价率")
    amount_min: Optional[float] = Field(None, description="最低成交额")
    amount_max: Optional[float] = Field(None, description="最高成交额")
    fund_type: Optional[str] = Field(None, description="基金类型")
    turnover_min: Optional[float] = Field(None, description="最低换手率")
    filter: Optional[str] = Field(None, description="watchlist=只看自选")
    search: Optional[str] = Field(None, description="代码或名称搜索")

    @field_validator("sort")
    @classmethod
    def validate_sort(cls, v: str) -> str:
        return v if v in SORT_WHITELIST else "amount"

    @field_validator("order")
    @classmethod
    def validate_order(cls, v: str) -> str:
        return v if v.lower() in ("asc", "desc") else "desc"


# ── 批量查询 ────────────────────────────────────────────────


class FundBatchRequest(BaseModel):
    codes: str = Field(..., description="逗号分隔的基金代码")

    @field_validator("codes")
    @classmethod
    def validate_codes(cls, v: str) -> str:
        code_list = [c.strip() for c in v.split(",") if c.strip()]
        if len(code_list) > BATCH_CODES_MAX:
            raise ValueError(f"最多 {BATCH_CODES_MAX} 只基金")
        if not code_list:
            raise ValueError("codes 不能为空")
        return ",".join(code_list)

    def get_codes(self) -> list[str]:
        return [clean_fund_code(c) for c in self.codes.split(",")]


# ── 图表请求 ────────────────────────────────────────────────


class ChartRequest(BaseModel):
    days: int = Field(30, ge=1, le=365, description="天数")


# ── 日线查询 ────────────────────────────────────────────────


class DataQueryRequest(BaseModel):
    fields: Optional[str] = Field(None, description="逗号分隔的字段名")
    from_date: Optional[date] = Field(None, description="开始日期")
    to_date: Optional[date] = Field(None, description="结束日期")
    limit: int = Field(60, ge=1, le=DAILY_QUERY_LIMIT_MAX)

    @field_validator("to_date")
    @classmethod
    def clamp_to_date(cls, v: Optional[date]) -> Optional[date]:
        if v:
            today = datetime.now(timezone.utc).date()
            return min(v, today)
        return v

    def get_fields(self) -> Optional[list[str]]:
        if self.fields:
            return [f.strip() for f in self.fields.split(",") if f.strip()]
        return None


class BatchQueryRequest(BaseModel):
    codes: str = Field(..., description="逗号分隔的基金代码")
    type: str = Field("fund", description="fund/asset")
    fields: Optional[str] = Field(None)
    from_date: Optional[date] = Field(None)
    to_date: Optional[date] = Field(None)

    @field_validator("codes")
    @classmethod
    def validate_codes(cls, v: str) -> str:
        code_list = [c.strip() for c in v.split(",") if c.strip()]
        if len(code_list) > 20:
            raise ValueError("批量查询最多 20 只")
        return ",".join(code_list)

    def get_codes(self) -> list[str]:
        return [clean_fund_code(c) for c in self.codes.split(",")]


# ── 公式 ────────────────────────────────────────────────────


class FormulaCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="公式名称")
    expression: str = Field(..., min_length=1, max_length=1000, description="表达式")
    description: Optional[str] = Field(None, max_length=500)
    group_id: Optional[int] = Field(None)
    sort_order: int = Field(0)


class FormulaUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    expression: Optional[str] = Field(None, min_length=1, max_length=1000)
    description: Optional[str] = Field(None, max_length=500)
    group_id: Optional[int] = None
    sort_order: Optional[int] = None


# ── 自选 ────────────────────────────────────────────────────


class WatchlistRequest(BaseModel):
    fund_code: str = Field(..., description="基金代码")

    @field_validator("fund_code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return clean_fund_code(v)


# ── 预警 ────────────────────────────────────────────────────


class AlertCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    fund_code: Optional[str] = Field(None, description="为空则全局预警")
    condition: dict = Field(..., description="条件 JSON")
    is_active: bool = Field(True)

    @field_validator("fund_code")
    @classmethod
    def validate_code(cls, v: Optional[str]) -> Optional[str]:
        return clean_fund_code(v) if v else None
