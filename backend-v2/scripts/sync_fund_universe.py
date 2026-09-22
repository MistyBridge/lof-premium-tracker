#!/usr/bin/env python3
"""
基金名单同步 — 从权威源补全 fund_category 表

背景
----
`fund_category` 是采集调度（`scheduler._codes()`）唯一的名单来源，但历史上它是
一次性静态导入的，代码库里没有任何写入路径，`job_scan_codes` 也只读本地
`all_lof_codes.json` 而不联网、不写库。结果是名单冻结在某次快照上：之后新上市、
转型、更名的基金永远进不来（例如 169101 东方红睿丰LOF、160632 酒LOF）。

本脚本拉取权威名单并与库内现状做差集，把缺失的补进 `fund_category`。

数据源
------
  深市  深圳证券交易所官方接口 CATALOGID=1105（自带权威分类字段 jjlb）
  沪市  东方财富 push2delay / push2 clist（fs=m:1+t:9），按代码段归类

安全约定
--------
只有当某个 (市场, 类别) 的权威名单**完整抓取成功**时，才允许把"名单里没有"
判定为退市并用 --prune 删除。抓取中断时对应组合自动降级为"不可判定"，一律保留。
例如沪市 ETF 目前没有接入权威源，永远不会被判定退市。

用法
----
    python3 scripts/sync_fund_universe.py                # dry-run，只报告差异
    python3 scripts/sync_fund_universe.py --apply        # 把缺失条目写入数据库
    python3 scripts/sync_fund_universe.py --apply --prune # 额外移除官方已无的条目

退出码
------
    0  成功（含 dry-run）
    1  两个数据源都失败，或数据库错误
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
import urllib.request

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP_DIR)
os.chdir(_APP_DIR)

from config import settings  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

log = logging.getLogger("sync_universe")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 深交所 jjlb -> 我们的 category
SZSE_CATEGORY_MAP = {
    "ETF": "ETF",
    "LOF": "LOF",
    "不动产基金": "REITs",
}

# 我们管理的场内基金类别（其余类别如"场内货币基金"不由本脚本触碰）
MANAGED_CATEGORIES = ("LOF", "ETF", "REITs")

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

# 已核查的沪市补充名单：在线源不可用时的兜底（东财对该接口做过统一限流）
SUPPLEMENT_PATH = os.path.join(_APP_DIR, "data", "sse_universe_supplement.json")


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
                log.warning("请求失败 %s (%s/%s): %s: %s",
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
            log.warning("深交所第 %d/%d 页失败，已取 %d 条 -> 本轮不判定深市退市",
                        page, pagecount, len(out))
            break
        item = payload[0]
        meta = item.get("metadata") or {}
        pagecount = meta.get("pagecount") or 1
        if page == 1:
            log.info("深交所: recordcount=%s pagecount=%s",
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
    log.info("深交所: 取到 %d 只（LOF/ETF/REITs）%s",
             len(out), "" if complete else "[不完整]")
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
            log.warning("沪市第 %d 页失败（已取 %d 条）-> 本轮不判定沪市退市",
                        page, len(out))
            break
        data = payload["data"]
        if total is None:
            total = data.get("total")
            log.info("沪市: total=%s", total)
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
    log.info("沪市: 取到 %d 只（LOF/REITs）%s",
             len(out), "" if complete else "[不完整]")
    return out, complete


# ── 补充名单 ──────────────────────────────────────────────────────────

def load_supplement() -> dict[str, dict]:
    """加载已核查的沪市补充名单（在线源不可用时的兜底）。

    文件缺失或损坏时返回空字典，不影响主流程。
    """
    if not os.path.exists(SUPPLEMENT_PATH):
        return {}
    try:
        with open(SUPPLEMENT_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:  # noqa: BLE001
        log.warning("补充名单读取失败 %s: %s", SUPPLEMENT_PATH, exc)
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
    log.info("补充名单: 载入 %d 条（verified_at=%s）",
             len(out), payload.get("_verified_at", "?"))
    return out


# ── 数据库 ────────────────────────────────────────────────────────────

async def load_db(categories: tuple[str, ...]) -> dict[str, set[str]]:
    """返回 {code: {category, ...}}，只含我们管理的类别。"""
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

def _emit(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


async def run(apply: bool, prune: bool) -> int:
    _emit("【1】拉取权威名单")
    szse, szse_ok = fetch_szse()
    sse, sse_ok = fetch_sse()

    if not szse_ok and not sse_ok:
        log.error("深交所与沪市两个数据源都抓取失败，终止")
        return 1

    # 运行期覆盖判定 = 静态能力 ∩ 本次抓取完整性
    coverage = dict(COVERAGE)
    if not szse_ok:
        for cat in MANAGED_CATEGORIES:
            coverage[("SZ", cat)] = False
    if not sse_ok:
        for cat in ("LOF", "REITs"):
            coverage[("SH", cat)] = False

    def is_covered(code: str, category: str) -> bool:
        return coverage.get((market_of(code), category), False)

    authoritative: dict[str, dict] = {}
    authoritative.update(szse)
    authoritative.update(sse)
    supplement = load_supplement()
    authoritative.update(supplement)

    db = await load_db(MANAGED_CATEGORIES)

    to_add: list[tuple[str, str]] = []
    conflicts: list[tuple[str, str, str]] = []
    for code, info in sorted(authoritative.items()):
        existing = db.get(code)
        if not existing:
            to_add.append((code, info["category"]))
        elif info["category"] not in existing:
            conflicts.append((code, info["category"], "/".join(sorted(existing))))

    to_remove: list[tuple[str, str]] = []
    uncovered: list[tuple[str, str]] = []
    for code, cats in sorted(db.items()):
        if code in authoritative:
            continue
        for category in sorted(cats):
            (to_remove if is_covered(code, category) else uncovered).append(
                (code, category))

    _emit("【2】差异分析")
    print(f"  权威名单(我们管理的类别): {len(authoritative)} 只"
          f"  [深交所 {len(szse)} + 沪市在线 {len(sse)} + 补充名单 {len(supplement)}]")
    print(f"  库内现有               : {len(db)} 只")
    print(f"  待新增                 : {len(to_add)} 只")
    print(f"  类别不一致(仅报告)     : {len(conflicts)} 只")
    print(f"  官方已无(疑似退市)     : {len(to_remove)} 只")
    print(f"  无法判定(源未覆盖)     : {len(uncovered)} 只")

    if to_add:
        print("\n  ── 待新增明细 ──")
        by_cat: dict[str, list[str]] = {}
        for code, category in to_add:
            by_cat.setdefault(category, []).append(code)
        for category in sorted(by_cat):
            codes = by_cat[category]
            print(f"    [{category}] {len(codes)} 只")
            for code in codes:
                print(f"        {code}  {authoritative[code]['name']}")

    if conflicts:
        print("\n  ── 类别不一致（需人工确认，本脚本不自动改）──")
        for code, official, mine in conflicts:
            print(f"    {code}  官方={official}  库内={mine}  "
                  f"{authoritative[code]['name']}")

    if to_remove:
        print("\n  ── 官方已无（疑似退市/终止上市）──")
        for code, category in to_remove:
            print(f"    {code}  [{category}]")

    if uncovered:
        print(f"\n  ── 源未覆盖、无法判定（保留不删，共 {len(uncovered)} 条）──")
        for code, category in uncovered[:6]:
            print(f"    {code}  [{category}]")
        if len(uncovered) > 6:
            print(f"    ... 其余 {len(uncovered) - 6} 条省略")

    if not apply:
        _emit("【3】DRY-RUN（未写入）")
        print("  加 --apply 才会写入数据库；加 --apply --prune 会同时删除疑似退市条目。")
        return 0

    _emit("【3】写入数据库")
    inserts, deletes = await apply_changes(to_add, to_remove if prune else [])
    print(f"  新增 fund_category 记录: {inserts} 条")
    if prune:
        print(f"  删除 fund_category 记录: {deletes} 条")
    else:
        print(f"  跳过删除（未指定 --prune），疑似退市 {len(to_remove)} 条保持不变")
    print("\n  提示: 名单变更将在下一次 fetch_realtime（每 5 分钟）自动生效。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="从权威源同步沪深场内基金名单到 fund_category 表")
    parser.add_argument("--apply", action="store_true",
                        help="真正写入数据库（默认仅 dry-run）")
    parser.add_argument("--prune", action="store_true",
                        help="同时删除官方已无的条目（需配合 --apply）")
    parser.add_argument("--verbose", action="store_true", help="输出调试日志")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    return asyncio.run(run(apply=args.apply, prune=args.prune))


if __name__ == "__main__":
    raise SystemExit(main())
