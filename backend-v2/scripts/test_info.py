"""
fetch_info 诊断工具
用法:
  python scripts/test_info.py 161725          # 逐步诊断单只基金
  python scripts/test_info.py --batch         # 批量诊断全部基金
"""
import asyncio
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.WARNING, format="%(message)s")


async def main():
    code = sys.argv[1] if len(sys.argv) > 1 else "161725"

    import httpx
    from fetchers.info import (
        _fetch_fee, _fetch_holdings, _fetch_basic_info,
        _parse_fee, _parse_holdings, _parse_info,
        _F10_HEADERS, FEE_URL, HOLDINGS_URL, INFO_URL,
    )

    print(f"=== 逐步诊断 {code} ===\n")

    async with httpx.AsyncClient(timeout=20) as client:
        # Step 1: 测试费率页面
        print("[1/6] 费率页面 HTTP 请求...")
        try:
            r = await client.get(FEE_URL.format(code=code), headers=_F10_HEADERS, timeout=15)
            print(f"  status={r.status_code} len={len(r.text)}")
            fee = _parse_fee(r.text)
            print(f"  解析结果: {fee}")
        except Exception as e:
            print(f"  异常: {e}")

        # Step 2: 测试持仓页面
        print("\n[2/6] 持仓页面 HTTP 请求...")
        try:
            r = await client.get(HOLDINGS_URL.format(code=code), headers=_F10_HEADERS, timeout=15)
            print(f"  status={r.status_code} len={len(r.text)}")
            holdings = _parse_holdings(r.text)
            h_list = holdings.get("holdings", [])
            print(f"  解析结果: {len(h_list)} 只持仓, quarter={holdings.get('quarter')}")
            if h_list:
                print(f"  第1只: {h_list[0]}")
        except Exception as e:
            print(f"  异常: {e}")

        # Step 3: 测试概况页面
        print("\n[3/6] 概况页面 HTTP 请求...")
        try:
            r = await client.get(INFO_URL.format(code=code), headers=_F10_HEADERS, timeout=15)
            print(f"  status={r.status_code} len={len(r.text)}")
            info = _parse_info(r.text)
            print(f"  解析结果: {info}")
        except Exception as e:
            print(f"  异常: {e}")

        # Step 4: 测试 _fetch_* 函数（带 retry）
        print("\n[4/6] _fetch_fee (带 retry)...")
        fee_result = await _fetch_fee(client, code)
        print(f"  返回: type={type(fee_result).__name__} len={len(fee_result) if isinstance(fee_result, dict) else 'N/A'}")
        if isinstance(fee_result, dict):
            for k, v in fee_result.items():
                print(f"    {k}: {v}")

        print("\n[5/6] _fetch_holdings (带 retry)...")
        hold_result = await _fetch_holdings(client, code)
        print(f"  返回: type={type(hold_result).__name__}")
        if isinstance(hold_result, dict):
            print(f"    holdings: {len(hold_result.get('holdings', []))} 只")
            print(f"    quarter: {hold_result.get('quarter')}")
        elif isinstance(hold_result, list):
            print(f"    list len: {len(hold_result)}")

        print("\n[6/6] _fetch_basic_info (带 retry)...")
        basic_result = await _fetch_basic_info(client, code)
        print(f"  返回: type={type(basic_result).__name__} len={len(basic_result) if isinstance(basic_result, dict) else 'N/A'}")
        if isinstance(basic_result, dict):
            for k, v in basic_result.items():
                print(f"    {k}: {v}")

    print("\n=== 诊断完成 ===")


async def batch_diagnose():
    """批量诊断：测试数据库中缺失数据的基金"""
    from dotenv import load_dotenv
    load_dotenv()

    from config import Settings
    from database import init_engine
    settings = Settings()
    init_engine(settings)

    from database import async_session_factory
    from sqlalchemy import text

    # 找出缺失 fund_type 的基金
    async with async_session_factory() as session:
        result = await session.execute(text("""
            SELECT fd.code FROM fund_daily fd
            LEFT JOIN fund_info fi ON fd.code = fi.code
            WHERE fi.code IS NULL OR fi.fund_type IS NULL
            GROUP BY fd.code
            ORDER BY fd.code
        """))
        missing_codes = [r[0] for r in result.fetchall()]

    if not missing_codes:
        print("所有基金都有 fund_type，无需诊断")
        return

    print(f"=== 批量诊断 {len(missing_codes)} 只缺失基金 ===\n")

    import httpx
    from fetchers.info import _fetch_fee, _fetch_holdings, _fetch_basic_info

    fee_ok = 0
    fee_fail = 0
    hold_ok = 0
    hold_fail = 0
    basic_ok = 0
    basic_fail = 0
    failed_codes = []

    async with httpx.AsyncClient(timeout=20) as client:
        for i, code in enumerate(missing_codes):
            fee = await _fetch_fee(client, code)
            hold = await _fetch_holdings(client, code)
            basic = await _fetch_basic_info(client, code)

            f_ok = isinstance(fee, dict) and bool(fee)
            h_ok = isinstance(hold, dict) and bool(hold.get("holdings"))
            b_ok = isinstance(basic, dict) and bool(basic)

            if f_ok: fee_ok += 1
            else: fee_fail += 1
            if h_ok: hold_ok += 1
            else: hold_fail += 1
            if b_ok: basic_ok += 1
            else: basic_fail += 1

            if not f_ok or not b_ok:
                failed_codes.append(code)
                print(f"  ✗ {code}: fee={'✓' if f_ok else '✗'} hold={'✓' if h_ok else '✗'} basic={'✓' if b_ok else '✗'}")

            if i < len(missing_codes) - 1:
                await asyncio.sleep(2)

    print(f"\n=== 结果 ===")
    print(f"  费率: {fee_ok}✓ {fee_fail}✗")
    print(f"  持仓: {hold_ok}✓ {hold_fail}✗")
    print(f"  概况: {basic_ok}✓ {basic_fail}✗")
    if failed_codes:
        print(f"\n  失败代码: {','.join(failed_codes[:20])}")

    from database import dispose_engine
    await dispose_engine()


if __name__ == "__main__":
    if "--batch" in sys.argv:
        asyncio.run(batch_diagnose())
    else:
        asyncio.run(main())
