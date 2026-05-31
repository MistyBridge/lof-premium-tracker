"""快速诊断 fetch_info 单只基金"""
import asyncio, sys, logging, httpx
sys.path.insert(0, ".")
logging.basicConfig(level=logging.WARNING, format="%(message)s")

async def main():
    code = sys.argv[1] if len(sys.argv) > 1 else "161725"
    from fetchers.info import (
        _fetch_fee, _fetch_holdings, _fetch_basic_info, _F10_HEADERS,
        FEE_URL, HOLDINGS_URL, INFO_URL, _parse_fee, _parse_holdings, _parse_info,
    )
    print(f"=== 诊断 {code} ===")
    async with httpx.AsyncClient(timeout=20) as c:
        # 1. 费率页面
        print("\n[1] 费率页面:")
        try:
            r = await c.get(FEE_URL.format(code=code), headers=_F10_HEADERS, timeout=15)
            print(f"  HTTP {r.status_code}, {len(r.text)} bytes")
            fee = _parse_fee(r.text)
            for k,v in fee.items(): print(f"  {k}: {v}")
        except Exception as e: print(f"  异常: {e}")

        # 2. 持仓页面
        print("\n[2] 持仓页面:")
        try:
            r = await c.get(HOLDINGS_URL.format(code=code), headers=_F10_HEADERS, timeout=15)
            print(f"  HTTP {r.status_code}, {len(r.text)} bytes")
            h = _parse_holdings(r.text)
            hl = h.get("holdings", [])
            print(f"  {len(hl)} 只持仓, quarter={h.get('quarter')}")
            if hl: print(f"  第1只: {hl[0]}")
        except Exception as e: print(f"  异常: {e}")

        # 3. 概况页面
        print("\n[3] 概况页面:")
        try:
            r = await c.get(INFO_URL.format(code=code), headers=_F10_HEADERS, timeout=15)
            print(f"  HTTP {r.status_code}, {len(r.text)} bytes")
            info = _parse_info(r.text)
            for k,v in info.items(): print(f"  {k}: {v}")
        except Exception as e: print(f"  异常: {e}")

        # 4. _fetch_fee (带retry)
        print("\n[4] _fetch_fee:")
        fee = await _fetch_fee(c, code)
        print(f"  type={type(fee).__name__}, keys={list(fee.keys()) if isinstance(fee, dict) else 'N/A'}")

        # 5. _fetch_holdings
        print("\n[5] _fetch_holdings:")
        h = await _fetch_holdings(c, code)
        print(f"  type={type(h).__name__}, len={len(h.get('holdings',[])) if isinstance(h,dict) else len(h) if isinstance(h,list) else 'N/A'}")

        # 6. _fetch_basic_info
        print("\n[6] _fetch_basic_info:")
        b = await _fetch_basic_info(c, code)
        print(f"  type={type(b).__name__}, keys={list(b.keys()) if isinstance(b, dict) else 'N/A'}")

    print("\n=== 完成 ===")

asyncio.run(main())
