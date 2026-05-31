"""
ORM 模型 — 16 张表
PostgreSQL 14 + SQLAlchemy 2.0 async
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BIGINT, BOOLEAN, CHAR, DATE, INTEGER, NUMERIC, TEXT,
    TIMESTAMP, VARCHAR, ForeignKey, Index, PrimaryKeyConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ── 1. fund_info ────────────────────────────────────────────

class FundInfo(Base):
    """基金基础信息（每日更新）"""
    __tablename__ = "fund_info"

    code: Mapped[str] = mapped_column(VARCHAR(6), primary_key=True)
    name: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    fund_type: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    index_code: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    market: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    aum: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(16, 2))
    listing_date: Mapped[Optional[date]] = mapped_column(DATE)
    redeem_days: Mapped[int] = mapped_column(INTEGER, default=2)
    qdii_quota_status: Mapped[str] = mapped_column(VARCHAR(20), default="open")
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow
    )


# ── 2. fund_daily ───────────────────────────────────────────

class FundDaily(Base):
    """日线数据（保留365天）"""
    __tablename__ = "fund_daily"
    __table_args__ = (
        PrimaryKeyConstraint("code", "trade_date"),
        Index("idx_daily_code_date", "code", "trade_date"),
        Index("idx_daily_date", "trade_date"),
    )

    code: Mapped[str] = mapped_column(VARCHAR(6), nullable=False)
    trade_date: Mapped[date] = mapped_column(DATE, nullable=False)
    open: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(12, 4))
    high: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(12, 4))
    low: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(12, 4))
    close: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(12, 4))
    volume: Mapped[Optional[int]] = mapped_column(BIGINT)
    amount: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(16, 2))
    nav: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(12, 4))
    nav_date: Mapped[Optional[date]] = mapped_column(DATE)
    nav_type: Mapped[str] = mapped_column(VARCHAR(20), default="confirmed")
    nav_source: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    data_source: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    float_share: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(16, 2))
    total_share: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(16, 2))
    premium_rate: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(10, 4))
    turnover_rate: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(10, 4))
    change_pct: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(10, 4))
    suspension_status: Mapped[str] = mapped_column(
        VARCHAR(20), default="unknown"
    )  # trading / suspended / unknown
    fetch_batch_id: Mapped[Optional[str]] = mapped_column(VARCHAR(36))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow
    )


# ── 3. fund_fee ─────────────────────────────────────────────

class FundFee(Base):
    """费率+申赎状态"""
    __tablename__ = "fund_fee"

    code: Mapped[str] = mapped_column(VARCHAR(6), primary_key=True)
    purchase_fee_rate: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(10, 4))
    redemption_fee_rate: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(10, 4))
    purchase_limit: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(16, 2))
    purchase_status: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    redeem_status: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    fetched_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)


# ── 4. fund_holdings ────────────────────────────────────────

class FundHoldings(Base):
    """十大持仓"""
    __tablename__ = "fund_holdings"
    __table_args__ = (Index("idx_holdings_code", "code"),)

    code: Mapped[str] = mapped_column(VARCHAR(6), primary_key=True)
    quarter: Mapped[str] = mapped_column(VARCHAR(10))
    report_date: Mapped[Optional[date]] = mapped_column(DATE)
    holdings: Mapped[list] = mapped_column(JSONB, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow
    )


# ── 5. fund_code_list ───────────────────────────────────────

class FundCodeList(Base):
    """LOF 代码列表（每日更新）"""
    __tablename__ = "fund_code_list"

    code: Mapped[str] = mapped_column(VARCHAR(6), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    market: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    last_seen: Mapped[date] = mapped_column(DATE, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow
    )


# ── 5b. fund_category ───────────────────────────────────────

class FundCategory(Base):
    """基金品类（每只基金可属于多个品类）"""
    __tablename__ = "fund_category"
    __table_args__ = (PrimaryKeyConstraint("code", "category"),)

    code: Mapped[str] = mapped_column(VARCHAR(6), nullable=False)
    category: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)  # LOF/ETF/QDII/REITs


# ── 6. asset_master ─────────────────────────────────────────

class AssetMaster(Base):
    """底层资产主表"""
    __tablename__ = "asset_master"

    code: Mapped[str] = mapped_column(VARCHAR(12), primary_key=True)
    name: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    asset_type: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    market: Mapped[Optional[str]] = mapped_column(CHAR(2))
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow
    )


# ── 7. asset_daily ──────────────────────────────────────────

class AssetDaily(Base):
    """资产日线（按月分区）"""
    __tablename__ = "asset_daily"
    __table_args__ = (PrimaryKeyConstraint("code", "trade_date"),)

    code: Mapped[str] = mapped_column(VARCHAR(12), nullable=False)
    trade_date: Mapped[date] = mapped_column(DATE, nullable=False)
    close: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(12, 4))
    change_pct: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(10, 4))
    volume: Mapped[Optional[int]] = mapped_column(BIGINT)
    amount: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(16, 2))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)


# ── 8. fund_asset_map ───────────────────────────────────────

class FundAssetMap(Base):
    """基金-资产关联"""
    __tablename__ = "fund_asset_map"
    __table_args__ = (
        PrimaryKeyConstraint("fund_code", "asset_code", "report_date"),
        Index("idx_fam_fund", "fund_code"),
        Index("idx_fam_asset", "asset_code"),
    )

    fund_code: Mapped[str] = mapped_column(VARCHAR(6), nullable=False)
    asset_code: Mapped[str] = mapped_column(VARCHAR(12), nullable=False)
    report_date: Mapped[date] = mapped_column(DATE, nullable=False)
    weight: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(8, 4))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)


# ── 9. trade_calendar ───────────────────────────────────────

class TradeCalendar(Base):
    """交易日历"""
    __tablename__ = "trade_calendar"

    trade_date: Mapped[date] = mapped_column(DATE, primary_key=True)
    is_trading: Mapped[bool] = mapped_column(BOOLEAN, nullable=False, default=True)


# ── 10. fetch_progress ──────────────────────────────────────

class FetchProgress(Base):
    """分批进度"""
    __tablename__ = "fetch_progress"

    task_name: Mapped[str] = mapped_column(VARCHAR(50), primary_key=True)
    last_code: Mapped[Optional[str]] = mapped_column(VARCHAR(12))
    completed: Mapped[int] = mapped_column(INTEGER, default=0)
    total: Mapped[int] = mapped_column(INTEGER, default=0)
    failed_codes: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow
    )


# ── 11. job_log ─────────────────────────────────────────────

class JobLog(Base):
    """定时任务执行记录"""
    __tablename__ = "job_log"
    __table_args__ = (Index("idx_job_name", "job_name", "started_at"),)

    id: Mapped[int] = mapped_column(INTEGER, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    status: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    duration_ms: Mapped[Optional[int]] = mapped_column(INTEGER)
    detail: Mapped[Optional[str]] = mapped_column(TEXT)
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_utcnow
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))


# ── 12. admin_audit_log ─────────────────────────────────────

class AdminAuditLog(Base):
    """管理员操作审计"""
    __tablename__ = "admin_audit_log"

    id: Mapped[int] = mapped_column(INTEGER, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(VARCHAR(64), nullable=False)
    action: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    target: Mapped[Optional[str]] = mapped_column(VARCHAR(200))
    detail: Mapped[Optional[str]] = mapped_column(TEXT)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)


# ── 13. user_formula ────────────────────────────────────────

class UserFormula(Base):
    """用户自定义公式（乐观锁: version 字段）"""
    __tablename__ = "user_formula"

    id: Mapped[int] = mapped_column(INTEGER, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(VARCHAR(64), nullable=False)
    group_id: Mapped[Optional[int]] = mapped_column(
        INTEGER, ForeignKey("user_formula_group.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    expression: Mapped[str] = mapped_column(TEXT, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(VARCHAR(500))
    sort_order: Mapped[int] = mapped_column(INTEGER, default=0)
    version: Mapped[int] = mapped_column(INTEGER, default=1)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow
    )


# ── 14. user_formula_group ──────────────────────────────────

class UserFormulaGroup(Base):
    """用户公式组"""
    __tablename__ = "user_formula_group"

    id: Mapped[int] = mapped_column(INTEGER, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(VARCHAR(64), nullable=False)
    name: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(VARCHAR(500))
    sort_order: Mapped[int] = mapped_column(INTEGER, default=0)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow
    )


# ── 15. user_watchlist ──────────────────────────────────────

class UserWatchlist(Base):
    """用户自选"""
    __tablename__ = "user_watchlist"
    __table_args__ = (PrimaryKeyConstraint("user_id", "fund_code"),)

    user_id: Mapped[str] = mapped_column(VARCHAR(64), nullable=False)
    fund_code: Mapped[str] = mapped_column(VARCHAR(6), nullable=False)
    sort_order: Mapped[int] = mapped_column(INTEGER, default=0)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)


# ── 16. user_alert ──────────────────────────────────────────

class UserAlert(Base):
    """用户预警规则"""
    __tablename__ = "user_alert"
    __table_args__ = (
        Index("idx_alerts_active", "user_id",
              postgresql_where="is_active = TRUE"),
    )

    id: Mapped[int] = mapped_column(INTEGER, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(VARCHAR(64), nullable=False)
    name: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    fund_code: Mapped[Optional[str]] = mapped_column(VARCHAR(6))
    condition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(BOOLEAN, default=True)
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow
    )
