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
    tencent_count: int = 0
    tencent_idle: int = 0
    tencent_gone: int = 0
    tencent_exists: int = 0
    money_market_filtered: int = 0
    money_market_by_type: int = 0
    db_total: int = 0
    to_add: list[tuple[str, str]] = field(default_factory=list)
    to_remove: list[tuple[str, str]] = field(default_factory=list)
    stale: list[tuple[str, str]] = field(default_factory=list)
    non_exchange: list[tuple[str, str]] = field(default_factory=list)
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


def is_exchange_listed(code: str) -> bool:
    """场内基金代码只可能是沪市 5 开头或深市 1 开头。

    0 开头的一律是场外基金。库里混进过 51 条这类条目，它们的名称里
    带 "ETF"（如"…基金中基金(ETF-FOF)"）或本身就是场内货币基金的
    场外份额，被名称规则误判成了 ETF/REITs。这类代码在任何行情源上
    都查不到，却会占用采集名额、在快照里留下空行误导用户。
    """
    return code[:1] in ("1", "5")


# 场内货币基金的名称特征。它们虽然是 511xxx/159xxx 的场内代码，但**不是
# 溢价率标的**：
#   * 行情"收盘价"是 100 元面值（每百份），不是可套利的交易价格；
#   * 数据源在 lsjz 接口给出的"净值"其实是每份日收益（0.2 上下），
#     与面值不在同一量纲。
# 两者套用 (close-nav)/nav 公式会得到几万 % 的荒谬溢价率。
# 这类基金在我们库里已有独立的受管外类别 `场内货币基金`。
#
# 关键词只取"货币"：货币基金的**全称**里必然带"货币市场基金"。
# 绝对不要加"现金" —— "招商中证800自由现金流交易型开放式指数证券投资基金"
# 这类**股票型 ETF** 的名称里含"自由现金流"，会被误判成货币基金而错踢出名单。
MONEY_MARKET_KEYWORDS = ("货币",)


def is_money_market(name: str) -> bool:
    """名称是否像场内货币基金（不适用溢价率公式）。"""
    return any(k in (name or "") for k in MONEY_MARKET_KEYWORDS)


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


# ── 腾讯行情反推扫描 ──────────────────────────────────────────────────
# 不依赖任何"名单接口"：直接批量查询代码段，由行情反推真实存在的场内基金。
# 这是最可靠的兜底源 —— 只要基金还在上市交易，腾讯就一定有行情记录；
# 已删除的代码则完全不返回。实测扫描约 12 万个代码需 1.5-2 分钟。
TENCENT_QT_URL = "https://qt.gtimg.cn/q="
TENCENT_SCAN_BATCH = 400          # 单次批量（URL 长度安全上限内）
TENCENT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 需扫描的场内基金代码段。
# 注意沪市必须一直覆盖到 589999：实测 52/53/55/56/58 段（港股通 ETF、
# 科创债 ETF、科创50 ETF 等）都是活跃品种，范围写到 519999 会漏掉
# 460 只真实在交易的 ETF。深市 15x/16x 与 18x 两段已足够。
TENCENT_SCAN_RANGES = (
    ("sh", 500000, 589999),   # 沪市：老封闭 500、LOF 501/502/506、REITs 508、ETF 51x-58x
    ("sz", 150000, 169999),   # 深市：ETF 15x、LOF 16x
    ("sz", 180000, 189999),   # 深市：REITs 18x
)

# 腾讯 qt 字段索引（沪深布局一致，各 88 字段）
_QT_NAME, _QT_PRICE, _QT_VOLUME = 1, 3, 6
_QT_TIME, _QT_AMOUNT = 30, 37


def _qt_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _qt_batch(codes: list[str], retries: int = 3) -> dict[str, list[str]]:
    """批量查询腾讯行情，返回 {sh510050: [字段...]}。"""
    url = TENCENT_QT_URL + ",".join(codes)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": TENCENT_UA,
                "Referer": "https://qt.gtimg.cn/",
            })
            with urllib.request.urlopen(req, timeout=25) as resp:
                text = resp.read().decode("gbk", "replace")
            out: dict[str, list[str]] = {}
            for line in text.split(";"):
                line = line.strip()
                if not line or "=" not in line:
                    continue
                key = line.split("=")[0].replace("v_", "")
                out[key] = line.split('="', 1)[1].rstrip('"').split("~")
            return out
        except Exception:  # noqa: BLE001 - 网络层杂错统一重试
            if attempt == retries - 1:
                return {}
            time.sleep(1.5 * (attempt + 1))
    return {}


def _classify_by_name(code: str, name: str) -> str | None:
    """按名称 + 代码段归类。返回 None 表示不纳入管理范围。

    判定顺序 LOF > REITs > ETF 是有意为之：有一批基金的名称同时含多个
    关键词，但实际类别是 LOF —— "500ETF联接LOF"、"美国REIT精选LOF"
    都是场内可申赎的上市开放式基金，不是 ETF / REITs。反过来真正的
    REITs（如"华夏金茂消费REIT"）与 ETF（如"沪深300ETF"）名称里不会
    出现 LOF，所以 LOF 放最前不会误伤。

    Args:
        code: 带市场前缀的代码，如 "sh520500"。
        name: 基金名称。
    """
    six = code[2:]
    # 场内代码是前置条件：0 开头的场外基金即使名字里带 "ETF" 也不是场内
    # 品种 —— "…基金中基金(ETF-FOF)" 就是典型，名称规则会把它误判成 ETF。
    if not is_exchange_listed(six):
        return None
    upper = name.upper()
    if "LOF" in upper:
        return "LOF"
    if "REIT" in upper:
        return "REITs"
    if "ETF" in upper:
        return "ETF"
    # 场内货币基金（华宝添益 511990 这类）不属于受管类别，但它们的代码段
    # 落在 ETF 区间里，必须先拦掉，否则会被下面的代码段兜底误判成 ETF。
    if "货币" in name or "现金" in name:
        return None
    if six[:3] in ("501", "502", "506") or six[:2] == "16":
        return "LOF"
    if six[:3] in ("508", "180"):
        return "REITs"
    if six[:2] in ("15", "51", "52", "53", "55", "56", "58"):
        return "ETF"
    return None


def fetch_by_tencent_scan() -> tuple[dict[str, dict], dict[str, dict], set[str], bool]:
    """扫描代码段反推场内基金名单。

    返回 (在交易名单, 无交易名单, 腾讯已删除的代码集合, 扫描是否完整)。

    判定"是否仍在上市交易"用的是成交额/成交量与时间戳，而不是价格 ——
    退市的老封闭基金（如 500001 国泰金泰封闭）腾讯依然保留最后价格，
    但其时间戳会停在 09:00:00 且成交额为 0。

    三档含义:
      active  有成交, 或时间戳晚于 09:00:00  -> 确定仍在上市交易
      idle    时间戳停在 09:00:00 且无成交    -> 疑似退市/长期停牌, 仅报告不自动删
      gone    扫描过但腾讯完全不返回          -> 代码已从腾讯库中删除, 强退市证据

    gone 是**逐代码**的精确覆盖信息：只有真的被扫过且腾讯不返回的代码才在内，
    因此调用方可以据此判定退市而不必关心扫描段之外的代码。反过来，
    active/idle 之外的未扫描代码不会出现在任何一档里，调用方必须把它们
    当作"不可判定"而非"退市"。

    无交易与已删除名单只用于识别退市候选，不作为新增来源。
    第四个返回值表示所有批次是否都成功 —— 有批次失败时 gone 不可信，
    调用方不得据此判断"退市"（否则网络抖动会被误当成退市证据）。
    """
    active: dict[str, dict] = {}
    idle: dict[str, dict] = {}
    scanned_codes: set[str] = set()
    failed_batches = 0

    for prefix, start, end in TENCENT_SCAN_RANGES:
        nums = list(range(start, end + 1))
        batches = (len(nums) + TENCENT_SCAN_BATCH - 1) // TENCENT_SCAN_BATCH
        for bi in range(batches):
            chunk = nums[bi * TENCENT_SCAN_BATCH:(bi + 1) * TENCENT_SCAN_BATCH]
            codes = [f"{prefix}{n:06d}" for n in chunk]
            scanned_codes.update(c[2:] for c in codes)
            rows = _qt_batch(codes)
            if not rows:
                failed_batches += 1
            for key, fields in rows.items():
                if len(fields) <= _QT_TIME:
                    continue
                code = key[2:]
                name = fields[_QT_NAME]
                category = _classify_by_name(key, name)
                if not category:
                    continue
                market = "SH" if prefix == "sh" else "SZ"
                entry = {"name": name, "category": category, "market": market}
                amount = _qt_float(fields[_QT_AMOUNT])
                volume = _qt_float(fields[_QT_VOLUME])
                stamp = fields[_QT_TIME]
                # 有成交, 或时间戳晚于 09:00:00（集合竞价初始值）→ 仍在交易
                if amount > 0 or volume > 0 or not stamp.endswith("090000"):
                    active[code] = entry
                else:
                    idle[code] = entry
            time.sleep(0.12)
        logger.info("[UNIVERSE] 腾讯扫描 %s %d-%d 完成，累计在交易 %d",
                    prefix, start, end, len(active))

    gone = scanned_codes - set(active) - set(idle)
    complete = failed_batches == 0
    logger.info("[UNIVERSE] 腾讯扫描共 %d 个代码：在交易 %d，无交易 %d，已删除 %d，"
                "失败批次 %d%s",
                len(scanned_codes), len(active), len(idle), len(gone),
                failed_batches, "" if complete else " [不完整]")
    return active, idle, gone, complete


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

async def load_money_market_codes() -> set[str]:
    """库里已确认为货币基金的代码（`fund_info.fund_type` 以"货币"开头）。

    为什么不能只靠名称：
      场内货币基金的**行情名**通常不含"货币"二字 —— 腾讯给的是
      "招商快线ETF""华宝添益ETF""银华日利ETF""鹏华添利ETF"。用名称关键词
      去拦，这 8 只会被当成"新增 ETF"写进采集名单，而它们的"收盘价"是
      100 元面值、数据源给的"净值"是每份日收益，量纲不同 —— 套溢价率公式
      会算出几万 % 并冲上榜首（#205 修过一轮）。而 `fund_info.fund_type`
      是东方财富给的权威口径（"货币型-普通货币"），可以精确识别。

    库不可用时返回空集合（宁可不拦，也不要让同步整体失败）。
    """
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(
                "SELECT code FROM fund_info WHERE fund_type LIKE '货币%'"))
            return {r[0] for r in result.fetchall()}
    except Exception as exc:  # noqa: BLE001 - 兜底过滤失败不阻断同步
        logger.warning("[UNIVERSE] 读取货币基金名单失败，跳过该道过滤: %s", exc)
        return set()
    finally:
        await engine.dispose()


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
    try:
        qt_active, qt_idle, qt_gone, qt_complete = fetch_by_tencent_scan()
    except Exception as exc:  # noqa: BLE001 - 扫描失败不阻断其它源
        logger.warning("[UNIVERSE] 腾讯扫描失败，跳过该源: %s", exc)
        qt_active, qt_idle, qt_gone, qt_complete = {}, {}, set(), False

    result.szse_count = len(szse)
    result.sse_count = len(sse)
    result.tencent_count = len(qt_active)
    result.tencent_idle = len(qt_idle)
    result.tencent_gone = len(qt_gone)
    result.szse_complete = szse_ok
    result.sse_complete = sse_ok

    if not szse_ok and not sse_ok and not qt_active:
        raise RuntimeError("深交所、沪市、腾讯扫描三个数据源全部失败")

    # 运行期覆盖判定 = 静态能力 ∩ 本次抓取完整性。
    # 这里只表达"交易所官方源"的覆盖能力；腾讯扫描的覆盖是逐代码的精确
    # 信息（见下面的 qt_gone / qt_exists），不做 (市场, 类别) 级别的粗糙提升。
    #
    # 历史教训：曾经在 qt_complete 时把 coverage[("SH", 类别)] 一律提升为
    # True，结果把 462 只从未被扫描到的沪市 ETF（52/53/55/56/58 段）和
    # 51 条 0 开头的场外代码一起判成了"疑似退市"。市场级布尔量根本表达不了
    # "只扫了 500000-519999"这种局部覆盖。
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
    # 腾讯扫描放最后: 它是"有行情"的直接证据, 覆盖最完整, 名称也最新
    authoritative.update(qt_active)
    # 兜底过滤：场内货币基金不是溢价率标的（收盘价是 100 元面值，数据源给的
    # "净值"是每份日收益），绝不能作为 LOF/ETF 进入采集名单。各源的分类规则
    # 都已有各自的拦截，这里再做一次统一把关，避免任何一条通路漏网。
    mm = [c for c, i in authoritative.items()
          if is_money_market(i.get("name", ""))]
    for code in mm:
        authoritative.pop(code, None)
    result.money_market_filtered = len(mm)
    if mm:
        logger.info("[UNIVERSE] 过滤场内货币基金 %d 只（不适用溢价率公式）",
                    len(mm))

    # 名称规则**拦不住**的那一批：场内货币基金的行情名通常不含"货币"二字。
    # 腾讯给的名字是"招商快线ETF""华宝添益ETF""银华日利ETF""鹏华添利ETF"
    # 这种，名称里没有关键词；但东方财富的 fund_info.fund_type 是
    # "货币型-普通货币"，这是权威口径。必须拿它再拦一道。
    #
    # 实测（2026-09-22 同步 dry-run）：只看名称的话，同步会把 8 只场内货币
    # 基金当成"新增 ETF"重新写进采集名单 —— #205 刚修掉的 5 万% 溢价率
    # 会原样回来，并重新冲上 ETF 板块榜首。
    db_mm = await load_money_market_codes()
    mm_by_type = [c for c in authoritative if c in db_mm]
    for code in mm_by_type:
        authoritative.pop(code, None)
    result.money_market_by_type = len(mm_by_type)
    if mm_by_type:
        logger.info("[UNIVERSE] 按 fund_type 过滤货币基金 %d 只（名称里无"
                    "\"货币\"字样，只能靠库里口径识别）: %s",
                    len(mm_by_type), ",".join(sorted(mm_by_type)[:10]))
    result.money_market_filtered += len(mm_by_type)

    result.authoritative = len(authoritative)
    result.names = {code: info.get("name", "") for code, info in authoritative.items()}

    # 腾讯"有记录"（在交易 ∪ 无交易）= 代码仍存在于腾讯库中, 构成存续证据。
    qt_exists = set(qt_active) | set(qt_idle)
    result.tencent_exists = len(qt_exists)
    # gone = 扫过但腾讯完全不返回。扫描不完整时"没返回"可能只是批次失败,
    # 不能当退市证据, 直接弃用。
    qt_gone_trusted = qt_gone if qt_complete else set()
    if not qt_complete:
        logger.warning("[UNIVERSE] 腾讯扫描不完整(%d 条 gone 不可信)，"
                       "本轮不据此判定退市", len(qt_gone))

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
        # 非场内代码（0 开头的场外基金、ETF-FOF、场内货币基金场外份额）:
        # 任何行情源都查不到它们, 单列出来供人工清理, 不参与退市判定。
        if not is_exchange_listed(code):
            for category in sorted(cats):
                result.non_exchange.append((code, category))
            continue
        # 腾讯仍有行情记录（只是当天没成交）→ 不能当退市删掉, 单独报告。
        # 这正是 fetch_by_tencent_scan 文档里说的"idle 仅报告不自动删"。
        if code in qt_exists:
            for category in sorted(cats):
                result.stale.append((code, category))
            continue
        for category in sorted(cats):
            # 腾讯扫过且完全不返回 -> 强退市证据（与官方源覆盖无关）
            if code in qt_gone_trusted:
                result.to_remove.append((code, category))
            elif coverage.get((market_of(code), category), False):
                result.to_remove.append((code, category))
            else:
                result.uncovered.append((code, category))

    if apply:
        result.inserted, result.deleted = await apply_changes(
            result.to_add, result.to_remove if prune else [])

    logger.info(
        "[UNIVERSE] 同步完成: 权威=%d 库内=%d 新增=%d(写入%d) "
        "疑似退市=%d(删除%d) 有记录但无成交=%d 非场内=%d 冲突=%d 不可判定=%d",
        result.authoritative, result.db_total, len(result.to_add),
        result.inserted, len(result.to_remove), result.deleted,
        len(result.stale), len(result.non_exchange),
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
