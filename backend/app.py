# -*- coding: utf-8 -*-
"""
LOF基金数据服务 - RESTful API
场内LOF基金: 实时价格 + 净值/估值 + 溢价率 + 成交额

启动命令: python app.py
依赖: pip install flask requests flask-cors
"""
import sys
# Fix Windows console encoding before any print
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import logging
from datetime import datetime
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from config import Config
from data_fetcher import get_fetcher
from history_db import get_history_db

# ─────────────────────────────────────────────
# 日志配置
# ─────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("lof-api")

# ─────────────────────────────────────────────
# Flask 应用
# ─────────────────────────────────────────────
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*", "methods": ["GET", "POST", "OPTIONS"], "allow_headers": ["Content-Type"]}})  # 允许跨域，支持预检请求


# ══════════════════════════════════════════════════════════════════
# 通用响应构建
# ══════════════════════════════════════════════════════════════════

def ok(data, meta=None, status=200):
    """成功响应: { code: 0, message, data, meta? }"""
    payload = {"code": 0, "message": "success", "data": data}
    if meta:
        payload["meta"] = meta
    return jsonify(payload), status


def err_resp(message, code=1, status=400, details=None):
    """错误响应: { code, message, details? }"""
    payload = {"code": code, "message": message}
    if details:
        payload["details"] = details
    return jsonify(payload), status


# ══════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════

def _is_suspended(fund: dict) -> bool:
    """判断基金是否停牌或无成交"""
    vol = fund.get("volume")
    amt = fund.get("amount")
    # 成交量为0 → 停牌
    if vol is not None and vol == 0:
        return True
    # 成交额为0 → 停牌（SSE 数据有 amount）
    if amt is not None and amt == 0:
        return True
    # SZ 数据可能缺少 volume/amount，但 price≈1.0 且无波动 → 停牌基金典型特征
    price = fund.get("price", 0) or 0
    pct = fund.get("change_pct", 0) or 0
    if abs(price - 1.0) < 0.001 and pct == 0 and (vol is None or vol == 0):
        return True
    return False


def _fmt(fund: dict, detail: bool = False) -> dict:
    """
    统一格式化输出字段
    所有溢价率/溢价状态已在 data_fetcher 中计算完毕
    """
    premium = fund.get("premium_rate")
    nav = fund.get("nav")
    price = fund.get("price", 0) or 0
    change_pct = fund.get("change_pct", 0)

    result = {
        # ── 基础信息 ──
        "code":       fund.get("code"),              # 6位基金代码
        "name":       fund.get("name"),              # 基金名称
        # ── 交易数据 ──
        "price":      fund.get("price"),             # 最新价（元）
        "change_pct": change_pct,                    # 涨跌幅（%）
        "volume":     fund.get("volume"),            # 成交量（股）
        "amount":     fund.get("amount"),            # 成交额（元）
        # ── 净值数据 ──
        "nav":        nav,                          # 当前净值/估算净值（元）
        "nav_date":   fund.get("nav_date"),         # 净值日期/估值时间
        "is_formal_nav": fund.get("is_formal_nav", False),  # 是否盘后正式净值
        # ── 溢价分析 ──
        "premium_rate":  premium,                   # 溢价率（%），正=溢价，负=折价
        "premium_status": fund.get("premium_status"),  # 溢价/折价/平价
        "avg_premium_3d": fund.get("avg_premium_3d"),  # 三日平均溢价率（%）
        # ── 费率数据 ──
        "purchase_fee_rate": fund.get("purchase_fee_rate"),  # 申购优惠费率（%）
        "redemption_fee_rate": fund.get("redemption_fee_rate"),  # 赎回费率最短档（%）
        "purchase_limit": fund.get("purchase_limit"),  # 日累计申购限额（元），None=无限额
        # ── 状态 ──
        "is_suspended": _is_suspended(fund),        # 是否停牌/无成交
        "can_purchase": fund.get("can_purchase"),  # 是否可申购（None=未知）
        "data_date": fund.get("_history_date"),     # 数据日期（历史回填时有值）
        # ── 推导字段 ──
        "change_amount": round(change_pct / 100 * price, 4) if (price and price > 0) else None,
    }

    if detail:
        result.update({
            "prev_nav": fund.get("prev_nav"),        # 昨日净值
            "volume_w": round(fund.get("volume", 0) / 10000, 2),  # 成交量（万手）
            "amount_w": round(fund.get("amount", 0) / 10000, 2),   # 成交额（万元）
        })

    return result


# ══════════════════════════════════════════════════════════════════
# Web 前端静态文件服务
# ══════════════════════════════════════════════════════════════════

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root (backend/../)

@app.route("/")
def index():
    """返回 Web 前端首页"""
    return send_from_directory(BASE_DIR, "index.html")

@app.route("/css/<path:filename>")
def css_files(filename):
    return send_from_directory(os.path.join(BASE_DIR, "css"), filename)

@app.route("/js/<path:filename>")
def js_files(filename):
    return send_from_directory(os.path.join(BASE_DIR, "js"), filename)

@app.route("/assets/<path:filename>")
def assets_files(filename):
    return send_from_directory(os.path.join(BASE_DIR, "assets"), filename)


# ══════════════════════════════════════════════════════════════════
# API 路由
# ══════════════════════════════════════════════════════════════════

# ── 健康检查 ──
@app.route("/health", methods=["GET"])
def health():
    """健康检查: 返回服务状态、缓存数量、最后更新时间"""
    f = get_fetcher()
    hdb = get_history_db()
    available_dates = hdb.get_available_dates()
    cache_count = len(f.get_all())
    return ok({
        "status": "running",
        "data_ready": cache_count > 0,
        "total": cache_count,
        "cache_count": cache_count,
        "last_fetch": f.last_fetch_time.isoformat() if f.last_fetch_time else None,
        "error": f.fetch_error,
        "refresh_interval_sec": Config.REFRESH_INTERVAL_SECONDS,
        "history_dates": available_dates,
        "history_days": len(available_dates),
    })


# ── 手动刷新（慎用） ──
@app.route("/refresh", methods=["POST"])
def refresh():
    """手动触发全量数据刷新"""
    f = get_fetcher()
    success = f.fetch_all()
    if success:
        return ok({"triggered": True, "count": len(f.get_all())})
    return err_resp("刷新失败，请检查网络或稍后重试", code=2, status=500)


# ── 手动补填历史数据 ──
@app.route("/init-history", methods=["POST"])
def init_history():
    """手动触发7天历史数据补填"""
    try:
        days = min(21, max(1, int(request.args.get("days", 7))))
    except ValueError:
        return err_resp("days 必须为正整数", code=10, status=400)
    try:
        from history_fetcher import fetch_historical_data
        rows = fetch_historical_data(days=days)
        hdb = get_history_db()
        # 重新加载缓存
        f = get_fetcher()
        f.load_from_history(hdb)
        # 注入三日均值
        avg_map = hdb.get_all_avg_premium_3d()
        with f._lock:
            for code, fund in f._cache.items():
                fund["avg_premium_3d"] = avg_map.get(code)
        return ok({"rows": rows, "dates": hdb.get_available_dates(), "cache_count": len(f.get_all())})
    except Exception as e:
        return err_resp(f"历史数据补填失败: {e}", code=11, status=500)


# ─────────────────────────────────────────────────────────────────
# 接口1: GET /api/funds
# 获取全量 LOF 基金列表（分页 + 排序 + 搜索 + 筛选）
# ─────────────────────────────────────────────────────────────────

@app.route("/api/funds", methods=["GET"])
def list_funds():
    # 懒更新：用户访问时检查数据是否陈旧，在后台触发刷新
    _trigger_lazy_refresh()
    f = get_fetcher()
    all_data = f.get_all()

    # 服务启动中，数据尚未加载
    if not all_data:
        return err_resp(
            "数据未就绪，服务正在初始化，请稍后重试",
            code=3,
            status=503,
            details={"tip": "首次启动约需 1-2 分钟加载全量数据"}
        )

    # ── 分页参数 ──
    try:
        page     = max(1, int(request.args.get("page", 1)))
        page_size = min(1000, max(1, int(request.args.get("page_size", 100))))
    except ValueError:
        return err_resp("page 和 page_size 必须为正整数", code=4, status=400)

    # ── 排序 ──
    sort_field = request.args.get("sort", "amount")
    sort_order = request.args.get("order", "desc")
    valid_sorts = {"amount", "change_pct", "premium_rate", "price", "code", "name", "avg_premium_3d"}
    if sort_field not in valid_sorts:
        return err_resp(f"sort 可选值: {','.join(valid_sorts)}", code=5, status=400)
    if sort_order not in {"asc", "desc"}:
        return err_resp("order 必须是 asc 或 desc", code=6, status=400)

    reverse = (sort_order == "desc")

    # ── 搜索（按代码或名称） ──
    search = (request.args.get("search") or "").strip()
    if search:
        s = search.upper()
        all_data = {k: v for k, v in all_data.items()
                    if s in k or s in v.get("name", "").upper()}

    # ── 溢价/折价筛选 ──
    filt = request.args.get("filter", "all")
    if filt == "premium":
        all_data = {k: v for k, v in all_data.items()
                    if (v.get("premium_rate") or 0) > 0}
    elif filt == "discount":
        all_data = {k: v for k, v in all_data.items()
                    if (v.get("premium_rate") or 0) < 0}

    # ── 停牌 & 申购状态筛选 ──
    show_suspended = request.args.get("suspended", "0")
    show_unpurchasable = request.args.get("unpurchasable", "0")
    if show_suspended != "1":
        all_data = {k: v for k, v in all_data.items()
                    if not _is_suspended(v)}
    if show_unpurchasable != "1":
        # 过滤掉暂停申购的基金（can_purchase=False）
        # can_purchase=None 表示未知状态，保留显示
        all_data = {k: v for k, v in all_data.items()
                    if v.get("can_purchase") is not False}

    # ── 排序 ──
    items = list(all_data.values())
    if sort_field == "premium_rate":
        items.sort(key=lambda x: x.get("premium_rate") if x.get("premium_rate") is not None else -9999.0, reverse=reverse)
    elif sort_field == "change_pct":
        items.sort(key=lambda x: x.get("change_pct", 0), reverse=reverse)
    elif sort_field == "amount":
        items.sort(key=lambda x: x.get("amount", 0), reverse=reverse)
    elif sort_field == "price":
        items.sort(key=lambda x: x.get("price", 0), reverse=reverse)
    elif sort_field == "code":
        items.sort(key=lambda x: x.get("code", ""), reverse=reverse)
    elif sort_field == "name":
        items.sort(key=lambda x: x.get("name", ""), reverse=reverse)
    elif sort_field == "avg_premium_3d":
        items.sort(key=lambda x: x.get("avg_premium_3d") if x.get("avg_premium_3d") is not None else -9999.0, reverse=reverse)

    total = len(items)
    start = (page - 1) * page_size
    page_items = [_fmt(f) for f in items[start: start + page_size]]

    return ok(
        page_items,
        meta={
            "page":        page,
            "page_size":   page_size,
            "total":       total,
            "total_pages": (total + page_size - 1) // page_size,
            "last_fetch":  f.last_fetch_time.isoformat() if f.last_fetch_time else None,
            "data_source": "东方财富 + 天天基金网",
        }
    )


@app.route("/api/debug/cache/<code>", methods=["GET"])
def debug_cache_raw(code: str):
    """临时调试端点：直接读原始cache，不走_fmt"""
    f = get_fetcher()
    fund = f.get_one(code)
    return ok({"raw": fund, "cache_count": len(f.get_all())})

# ─────────────────────────────────────────────────────────────────
# 接口2: GET /api/funds/<code>
# 获取单只 LOF 基金详情
# ─────────────────────────────────────────────────────────────────

@app.route("/api/funds/<code>", methods=["GET"])
def fund_detail(code: str):
    # 懒更新
    _trigger_lazy_refresh()
    f = get_fetcher()
    fund = f.get_one(code)
    if not fund:
        return err_resp(
            f"未找到基金: {code}",
            code=7,
            status=404,
            details={"code": code, "tip": "请确认基金代码为6位数字，如 166009"}
        )
    return ok(_fmt(fund, detail=True))


# ─────────────────────────────────────────────────────────────────

@app.route("/api/funds/<code>/chart", methods=["GET"])
def fund_chart(code: str):
    """近7个交易日场内价格和场外净值曲线数据"""
    f = get_fetcher()
    fund = f.get_one(code)
    if not fund:
        return err_resp(f"未找到基金: {code}", code=7, status=404)
    hdb = get_history_db()
    history = hdb.get_history(code=code, days=21)
    history.sort(key=lambda x: x["date"])
    return ok({
        "code": code,
        "name": fund.get("name"),
        "chart": [{
            "date": h["date"],
            "price": h["price"],
            "nav": h["nav"],
            "premium_rate": h["premium_rate"],
        } for h in history],
    })

# 接口3: GET /api/rankings
# 溢价率排行榜（溢价 Top / 折价 Top）
# ─────────────────────────────────────────────────────────────────

@app.route("/api/rankings", methods=["GET"])
def rankings():
    # 懒更新
    _trigger_lazy_refresh()
    f = get_fetcher()
    all_data = f.get_all()

    rank_type = request.args.get("type", "premium")
    try:
        limit = min(100, max(1, int(request.args.get("limit", 20))))
    except ValueError:
        return err_resp("limit 必须为正整数", code=8, status=400)

    valid = [v for v in all_data.values()
             if v.get("premium_rate") is not None
             and not _is_suspended(v)
             and v.get("can_purchase") is not False]

    if rank_type == "premium":
        sorted_funds = sorted(valid, key=lambda x: x["premium_rate"], reverse=True)
        label = "溢价率最高"
    else:
        sorted_funds = sorted(valid, key=lambda x: x["premium_rate"])
        label = "折价率最高"

    ranked = [_fmt(f) for f in sorted_funds[:limit]]
    return ok(ranked, meta={"type": rank_type, "label": label, "limit": limit, "total": len(sorted_funds)})


# ══════════════════════════════════════════════════════════════════
# 历史数据 API
# ══════════════════════════════════════════════════════════════════

@app.route("/api/history", methods=["GET"])
def history():
    """
    获取历史溢价率数据
    参数:
      code: 基金代码（可选，不传则返回概览）
      days: 查询天数（默认7，最大7）
    """
    _trigger_lazy_refresh()
    hdb = get_history_db()

    try:
        days = min(21, max(1, int(request.args.get("days", 7))))
    except ValueError:
        return err_resp("days 必须为正整数", code=9, status=400)

    code = request.args.get("code")
    code = code.strip().zfill(6) if code else None

    if code:
        # 单只基金历史
        fund = get_fetcher().get_one(code)
        if not fund:
            return err_resp(f"未找到基金: {code}", code=7, status=404)
        data = hdb.get_history(code=code, days=days)
        avg = hdb.get_avg_premium_3d(code)
        return ok({
            "code": code,
            "name": fund.get("name"),
            "avg_premium_3d": avg,
            "history": data,
        })
    else:
        # 全量概览：返回可用日期列表 + 所有基金的三日均溢
        avg_map = hdb.get_all_avg_premium_3d()
        dates = hdb.get_available_dates()
        return ok({
            "available_dates": dates,
            "avg_premium_3d": avg_map,
        }, meta={
            "history_days": len(dates),
        })


# ══════════════════════════════════════════════════════════════════
# 懒更新机制（替代 APScheduler，适用于 Railway 等休眠平台）
# ══════════════════════════════════════════════════════════════════

import threading

_lazy_refreshing = False   # 防止并发刷新
_lazy_lock = threading.Lock()


def _trigger_lazy_refresh():
    """
    检查数据是否陈旧，若是则在后台线程触发刷新。
    所有 API 请求入口调用此方法，确保数据常新。
    """
    global _lazy_refreshing
    f = get_fetcher()

    # 缓存为空时强制刷新（Railway重启后PostgreSQL丢失场景）
    cache_empty = len(f.get_all()) == 0

    # 检查是否需要刷新
    if not cache_empty and f.last_fetch_time is not None:
        age = (datetime.now() - f.last_fetch_time).total_seconds()
        if age < Config.REFRESH_INTERVAL_SECONDS:
            return  # 数据还新鲜，不用刷新

    # 避免并发刷新
    if _lazy_refreshing:
        return

    with _lazy_lock:
        if _lazy_refreshing:
            return
        _lazy_refreshing = True

    def _do_refresh():
        nonlocal cache_empty
        try:
            logger.info("⏰ 懒更新触发，开始刷新...")
            ok_flag = f.fetch_all()
            if ok_flag:
                # 保存溢价率快照到历史数据库
                try:
                    hdb = get_history_db()
                    hdb.save_snapshot(f.get_all())
                    # 注入三日平均溢价率到缓存
                    avg_map = hdb.get_all_avg_premium_3d()
                    with f._lock:
                        for code, fund in f._cache.items():
                            fund["avg_premium_3d"] = avg_map.get(code)
                except Exception as ex:
                    logger.warning(f"历史数据保存失败: {ex}")
                logger.info(f"✅ 懒更新完成，当前缓存 {len(f.get_all())} 只基金")
            else:
                # 实时抓取失败，尝试从历史数据降级
                if len(f.get_all()) == 0:
                    hdb = get_history_db()
                    hist_ok = f.load_from_history(hdb)
                    if hist_ok:
                        try:
                            avg_map = hdb.get_all_avg_premium_3d()
                            with f._lock:
                                for code, fund in f._cache.items():
                                    fund["avg_premium_3d"] = avg_map.get(code)
                        except Exception as ex:
                            logger.warning(f"历史三日均溢计算失败: {ex}")
                        logger.info(f"✅ 懒更新降级到历史数据，{len(f.get_all())} 只基金")
                    else:
                        logger.warning("⚠️ 懒更新失败且无历史数据可用，稍后重试")
                else:
                    logger.warning("⚠️ 懒更新失败，继续使用当前缓存")
        finally:
            global _lazy_refreshing
            _lazy_refreshing = False

    t = threading.Thread(target=_do_refresh, daemon=True)
    t.start()


# ══════════════════════════════════════════════════════════════════
# 启动初始化（gunicorn兼容 - 模块导入时执行后台初始化）
# ══════════════════════════════════════════════════════════════════

def _startup_init():
    """
    后台初始化线程，模块导入时启动。
    兼容 gunicorn：不依赖 __main__ 块。
    策略：seed文件 → history_db → 实时API（逐级降级）
    """
    f = get_fetcher()
    hdb = get_history_db()

    # ── 第一步：从种子文件加载数据（解决Railway重启PostgreSQL丢失问题）──
    available_dates = hdb.get_available_dates()
    cache_empty = len(f.get_all()) == 0

    if cache_empty and len(available_dates) < 3:
        logger.info("📦 缓存为空且历史数据不足，尝试从种子文件加载...")
        seed_ok = f.load_from_seed()
        if seed_ok:
            # 注入三日平均溢价率
            try:
                avg_map = hdb.get_all_avg_premium_3d()
                with f._lock:
                    for code, fund in f._cache.items():
                        fund["avg_premium_3d"] = avg_map.get(code)
            except Exception as ex:
                logger.warning(f"⚠️ 三日均溢计算失败: {ex}")
            cache_count = len(f.get_all())
            logger.info(f"✅ 种子数据加载完成，{cache_count} 只基金已就绪")
        else:
            logger.info("⚠️ 种子文件不可用，尝试从history_db降级...")
            hist_ok = f.load_from_history(hdb)
            if hist_ok:
                try:
                    avg_map = hdb.get_all_avg_premium_3d()
                    with f._lock:
                        for code, fund in f._cache.items():
                            fund["avg_premium_3d"] = avg_map.get(code)
                except Exception as ex:
                    logger.warning(f"⚠️ 三日均溢计算失败: {ex}")
                logger.info(f"✅ 历史数据降级加载完成，{len(f.get_all())} 只基金")
            else:
                # 尝试从API补填（可能因网络问题失败）
                logger.info("📦 尝试从API补填历史数据...")
                try:
                    from history_fetcher import fetch_historical_data
                    rows = fetch_historical_data(days=7)
                    logger.info(f"✅ 历史数据补填完成，共 {rows} 条记录")
                except Exception as ex:
                    logger.warning(f"⚠️ 历史数据补填失败: {ex}")
    elif cache_empty and len(available_dates) >= 3:
        # PostgreSQL有数据，直接加载
        logger.info(f"📦 从history_db加载（{len(available_dates)}天数据）...")
        hist_ok = f.load_from_history(hdb)
        if hist_ok:
            try:
                avg_map = hdb.get_all_avg_premium_3d()
                with f._lock:
                    for code, fund in f._cache.items():
                        fund["avg_premium_3d"] = avg_map.get(code)
            except Exception as ex:
                logger.warning(f"⚠️ 三日均溢计算失败: {ex}")
            logger.info(f"✅ 历史数据加载完成，{len(f.get_all())} 只基金已就绪")
    else:
        logger.info(f"📦 缓存已有 {len(f.get_all())} 只基金，跳过初始化")

    # ── 第二步：尝试实时数据抓取 ──
    logger.info("📡 正在尝试拉取实时数据...")
    ok_flag = f.fetch_all()
    if ok_flag:
        try:
            hdb.save_snapshot(f.get_all())
            avg_map = hdb.get_all_avg_premium_3d()
            with f._lock:
                for code, fund in f._cache.items():
                    fund["avg_premium_3d"] = avg_map.get(code)
        except Exception as ex:
            logger.warning(f"历史数据保存失败: {ex}")
        logger.info(f"✅ 实时数据刷新完成，{len(f.get_all())} 只基金")
    else:
        logger.info("⚠️ 实时数据抓取失败，继续使用历史数据服务")


# 启动后台初始化线程（gunicorn导入模块时自动触发）
_init_thread = threading.Thread(target=_startup_init, daemon=True)
_init_thread.start()


# ══════════════════════════════════════════════════════════════════
# 本地开发启动入口
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 62)
    print("  LOF基金数据服务  v1.2")
    print("  数据源: 东方财富 + 天天基金网（免费公开，无需Key）")
    print("=" * 62)
    print("✅ 服务已启动（后台初始化中）")
    print(f"   API文档: http://localhost:{Config.PORT}/api/funds")
    print(f"   健康检查: http://localhost:{Config.PORT}/health")
    print(f"   溢价排行: http://localhost:{Config.PORT}/api/rankings")
    print(f"   刷新间隔: {Config.REFRESH_INTERVAL_SECONDS}秒（用户访问时触发）")
    print("=" * 62)

    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=Config.DEBUG,
        use_reloader=False,
        threaded=True,
    )
