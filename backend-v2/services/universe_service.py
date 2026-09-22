"""
基金名单同步服务 — 从权威源补全/校准 fund_category 表

背景
----
`fund_category` 是采集调度（`scheduler._codes()`）唯一的名单来源，也是
`daily_save` 的名单来源。但历史上它是一次性静态导入的：代码库里没有任何写入路径，
`job_scan_codes` 也只读本地 `all_lof_codes.json` 而不联网、不写库。
结果是名单冻结在某次快照上，之后新上市、转型、更名的基金永远进不来
（例如 169101 东方红睿丰LOF、160632 酒LOF）。

设计文档 `docs/plan/M7_调度层.md` 原本就规定 scan_codes 应当「用 push2 clist
扫描代码列表」，本模块即为该设计意图的实现。

数据源
------
  深市  深圳证券交易所官方接口 CATALOGID=1105（自带权威分类字段 jjlb）
  沪市  东方财富 push2delay / push2 clist（fs=m:1+t:9），按代码段归类
  兜底  已核查补充名单 data/sse_universe_supplement.json

安全约定
--------
只有当某个 (市场, 类别) 的权威名单**完整抓取成功**时，才允许把"名单里没有"
判定为退市并删除。抓取中断会自动降级为"不可判定"，一律保留。
沪市 ETF 未接入权威源，因此永远不会被判定退市（否则会误删数百只存量 ETF）。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from config import settings

logger = logging.getLogger("app")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

_APP_DIR = Path(__file__).resolve().parent.parent

# 深交所 jjlb -> 我们的 category
SZSE_CATEGORY_MAP = {
    "ETF": "ETF",
    "LOF": "LOF",
    "不动产基金": "REITs",
}

# 我们管理的场内基金类别（其余类别如"场内货币基金"不由本模块触碰）
MANAGED_CATEGORIES = ("LOF", "ETF", "REITs")

# 采集名单的类别范围，必须与 scheduler._codes() 保持一致
COLLECT_CATEGORIES = ("LOF", "ETF")

# 权威源对各类别的静态覆盖能力。
# 运行时还会与"本次抓取是否完整"取交集，抓取失败则自动降级为不可判定。
COVERAGE = {
    ("SZ", "LOF"): True,
    ("SZ", "ETF"): True,
    ("SZ", "REITs"): True,
    ("SH", "LOF"): True,
    ("SH", "REITs"): True,
    ("SH", "ETF"): False,   # 沪市 ETF 未接入权威源，永不判退市
}

SSE_HOSTS = ("push2delay.eastmoney.com", "push2.eastmoney.com")

SUPPLEMENT_PATH = _APP_DIR / "data" / "sse_universe_supplement.json"


# ── 结果结构 ──────────────────────────────────────────────────────────

@dataclass
class SyncResult:
    """一次同步的完整结果。"""
    authoritative: int = 0
    szse_count: int = 0
    sse_count: int = 0
    supplement_count: int = 0
    db_total: int = 0
    to_add: list[tuple[str, str]] = field(default_factory=list)
    to_remove: list[tuple[str, str]] = field(default_factory=list)
    conflicts: list[tuple[str, str, str]] = field(default_factory=list)
    uncovered: list[tuple[str, str]] = field(default_factory=list)
    inserted: int = 0
    deleted: int = 0
    applied: bool = False
    pruned: bool = False
    szse_complete: bool = True
    sse_complete: bool = True
    names: dict[str, str] = field(default_factory=dict)


def market_of(code: str) -> str:
    """深市代码以 1 开头（15/16/18），沪市以 5 开头（50/51/58）。"""
    return "SZ" if code.startswith("1") else "SH"


# ── HTTP ──────────────────────────────────────────────────────────────

def _http_json(url: str, referer: str, retries: int = 4,
               base_sleep: float = 1.5) -> dict | None:
    """带退避重试的 JSON GET。全部失败返回 None。"""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Referer": referer,
                "Accept": "application/json,text/plain,*/*",
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001 - 网络层杂错统一重试
            if attempt == retries - 1:
                logger.warning("[UNIVERSE] 请求失败 %s (%s/%s): %s: %s",
                               url.split("/")[2], attempt + 1, retries,
                               type(exc).__name__, str(exc)[:70])
                return None
            time.sleep(base_sleep * (attempt + 1))
    return None


# ── 名单抓取 ──────────────────────────────────────────────────────────

def fetch_szse() -> tuple[dict[str, dict], bool]:
    """深交所官方基金列表（权威分类）。

    返回 (名单, 是否完整抓取)。名单为 {code: {name, category, market}}。
    """
    out: dict[str, dict] = {}
    page, pagecount = 1, 1
    complete = True
    while page <= pagecount:
        url = ("http://www.szse.cn/api/report/ShowReport/data?SHOWTYPE=JSON"
               f"&CATALOGID=1105&TABKEY=tab1&PAGENO={page}&PAGESIZE=100")
        payload = _http_json(url, "https://www.szse.cn/")
        if not payload:
            complete = False
            logger.warning("[UNIVERSE] 深交所第 %d/%d 页失败，已取 %d 条 "
                           "-> 本轮不判定深市退市", page, pagecount, len(out))
            break
        item = payload[0]
        meta = item.get("metadata") or {}
        pagecount = meta.get("pagecount") or 1
        if page == 1:
            logger.info("[UNIVERSE] 深交所 recordcount=%s pagecount=%s",
                        meta.get("recordcount"), pagecount)
        for row in (item.get("data") or []):
            m = re.search(r"code=(\d{6})", row.get("sys_key", ""))
            if not m:
                continue
            category = SZSE_CATEGORY_MAP.get((row.get("jjlb") or "").strip())
            if not category:
                continue
            nm = re.search(r"name=([^&']+)", row.get("jjjcurl", ""))
            out[m.group(1)] = {
                "name": nm.group(1) if nm else "",
                "category": category,
                "market": "SZ",
            }
        page += 1
        time.sleep(0.3)
    logger.info("[UNIVERSE] 深交所取到 %d 只（LOF/ETF/REITs）%s",
                len(out), "" if complete else " [不完整]")
    return out, complete


def _sse_category(code: str) -> str | None:
    """沪市代码段 -> category。只覆盖分类规则明确的段。"""
    if code.startswith(("501", "502", "506")):
        return "LOF"
    if code.startswith("508"):
        return "REITs"
    return None


def fetch_sse(max_pages: int = 20) -> tuple[dict[str, dict], bool]:
    """沪市名单（东财）。只归类代码段规则明确的 LOF / REITs。

    返回 (名单, 是否完整抓取)。
    """
    out: dict[str, dict] = {}
    total = None
    page = 1
    complete = True
    while page <= max_pages:
        payload = None
        for host in SSE_HOSTS:
            url = (f"https://{host}/api/qt/clist/get?"
                   f"pn={page}&pz=100&po=0&np=1&fltt=2&invt=2&fid=f12"
                   "&fs=m:1+t:9&fields=f12,f14")
            payload = _http_json(url, "https://quote.eastmoney.com/",
                                 retries=3, base_sleep=3.0)
            if payload and payload.get("data"):
                break
            payload = None
        if not payload:
            complete = False
            logger.warning("[UNIVERSE] 沪市第 %d 页失败（已取 %d 条）"
                           " -> 本轮不判定沪市退市", page, len(out))
            break
        data = payload["data"]
        if total is None:
            total = data.get("total")
            logger.info("[UNIVERSE] 沪市 total=%s", total)
        diff = data.get("diff") or []
        if not diff:
            break
        for it in diff:
            code = it.get("f12") or ""
            category = _sse_category(code)
            if not category:
                continue
            out[code] = {
                "name": it.get("f14") or "",
                "category": category,
                "market": "SH",
            }
        if total and page * 100 >= total:
            break
        page += 1
        time.sleep(2.5)
    logger.info("[UNIVERSE] 沪市取到 %d 只（LOF/REITs）%s",
                len(out), "" if complete else " [不完整]")
    return out, complete


def load_supplement() -> dict[str, dict]:
    """加载已核查的沪市补充名单（在线源不可用时的兜底）。

    文件缺失或损坏时返回空字典，不影响主流程。
    """
    if not SUPPLEMENT_PATH.exists():
        return {}
    try:
        with open(SUPPLEMENT_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[UNIVERSE] 补充名单读取失败 %s: %s", SUPPLEMENT_PATH, exc)
        return {}
    out: dict[str, dict] = {}
    for entry in payload.get("entries") or []:
        code = entry.get("code")
        category = entry.get("category")
        if not code or not category:
            continue
        out[code] = {
            "name": entry.get("name", ""),
            "category": category,
            "market": entry.get("market", "SH"),
        }
    logger.info("[UNIVERSE] 补充名单载入 %d 条（verified_at=%s）",
                len(out), payload.get("_verified_at", "?"))
    return out


# ── 数据库 ────────────────────────────────────────────────────────────

async def load_db_categories(categories: tuple[str, ...]) -> dict[str, set[str]]:
    """返回 {code: {category, ...}}，只含指定类别。"""
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT code, category FROM fund_category "
                     "WHERE category = ANY(:cats)"),
                {"cats": list(categories)},
            )
            out: dict[str, set[str]] = {}
            for code, category in result.fetchall():
                out.setdefault(code, set()).add(category)
            return out
    finally:
        await engine.dispose()


async def apply_changes(to_add: list[tuple[str, str]],
                        to_remove: list[tuple[str, str]]) -> tuple[int, int]:
    """写入新增、删除移除。返回 (插入数, 删除数)。"""
    engine = create_async_engine(settings.DATABASE_URL)
    inserted = deleted = 0
    try:
        async with engine.begin() as conn:
            if to_add:
                await conn.execute(
                    text("INSERT INTO fund_category (code, category) "
                         "VALUES (:code, :category) "
                         "ON CONFLICT (code, category) DO NOTHING"),
                    [{"code": c, "category": k} for c, k in to_add],
                )
                inserted = len(to_add)
            if to_remove:
                await conn.execute(
                    text("DELETE FROM fund_category "
                         "WHERE code = :code AND category = :category"),
                    [{"code": c, "category": k} for c, k in to_remove],
                )
                deleted = len(to_remove)
    finally:
        await engine.dispose()
    return inserted, deleted


# ── 主流程 ────────────────────────────────────────────────────────────

async def sync_universe(*, apply: bool, prune: bool = False,
                        categories: tuple[str, ...] = MANAGED_CATEGORIES,
                        ) -> SyncResult:
    """拉取权威名单并与 fund_category 做差集。

    Args:
        apply: True 才写入数据库；False 为 dry-run。
        prune: 是否删除官方已无的条目（仅在 apply=True 时生效）。
        categories: 参与同步的类别，默认 LOF/ETF/REITs。

    Returns:
        SyncResult，含差异明细与实际写入数量。
    """
    result = SyncResult(applied=apply, pruned=prune and apply)

    szse, szse_ok = fetch_szse()
    sse, sse_ok = fetch_sse()
    result.szse_count = len(szse)
    result.sse_count = len(sse)
    result.szse_complete = szse_ok
    result.sse_complete = sse_ok

    if not szse_ok and not sse_ok:
        raise RuntimeError("深交所与沪市两个数据源都抓取失败")

    # 运行期覆盖判定 = 静态能力 ∩ 本次抓取完整性
    coverage = dict(COVERAGE)
    if not szse_ok:
        for cat in categories:
            coverage[("SZ", cat)] = False
    if not sse_ok:
        for cat in categories:
            coverage[("SH", cat)] = False

    supplement = load_supplement()
    result.supplement_count = len(supplement)

    authoritative: dict[str, dict] = {}
    authoritative.update(szse)
    authoritative.update(sse)
    authoritative.update(supplement)
    result.authoritative = len(authoritative)
    result.names = {code: info.get("name", "") for code, info in authoritative.items()}

    db = await load_db_categories(categories)
    result.db_total = len(db)

    for code, info in sorted(authoritative.items()):
        existing = db.get(code)
        if not existing:
            result.to_add.append((code, info["category"]))
        elif info["category"] not in existing:
            result.conflicts.append(
                (code, info["category"], "/".join(sorted(existing))))

    for code, cats in sorted(db.items()):
        if code in authoritative:
            continue
        for category in sorted(cats):
            if coverage.get((market_of(code), category), False):
                result.to_remove.append((code, category))
            else:
                result.uncovered.append((code, category))

    if apply:
        result.inserted, result.deleted = await apply_changes(
            result.to_add, result.to_remove if prune else [])

    logger.info(
        "[UNIVERSE] 同步完成: 权威=%d 库内=%d 新增=%d(写入%d) "
        "疑似退市=%d(删除%d) 冲突=%d 不可判定=%d",
        result.authoritative, result.db_total, len(result.to_add),
        result.inserted, len(result.to_remove), result.deleted,
        len(result.conflicts), len(result.uncovered))
    return result


async def collect_codes() -> list[str]:
    """采集名单的代码列表（供 scheduler 复用，条件与 _codes() 一致）。"""
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT code FROM fund_category WHERE category = ANY(:cats) "
                     "ORDER BY code"),
                {"cats": list(COLLECT_CATEGORIES)})
            return [r[0] for r in result.fetchall()]
    finally:
        await engine.dispose()
