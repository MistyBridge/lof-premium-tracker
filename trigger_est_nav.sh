#!/bin/bash
# 手动触发一次 est_nav 计算 + SQL 切片写入验证
cd /opt/jinkuaicha/backend-v2
python3 -c "
import asyncio, httpx, logging, time
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')

import database
from config import settings
from services.est_nav_service import run_est_nav, save_est_nav_slice

async def main():
    database.init_engine(settings)
    async with httpx.AsyncClient(timeout=30) as client:
        data = await run_est_nav(client)
        print(f'run_est_nav: {len(data)} funds computed')
        if data:
            saved = await save_est_nav_slice(data)
            print(f'save_est_nav_slice: {saved} rows written')
        else:
            print('No data to save')

    # 查询验证
    async with database.async_session_factory() as session:
        from sqlalchemy import text
        r = await session.execute(text(
            \"SELECT count(*), count(DISTINCT code), max(snapshot_time) FROM fund_est_nav WHERE trade_date = CURRENT_DATE\"
        ))
        row = r.fetchone()
        print(f'Today rows: {row[0]}, unique funds: {row[1]}, latest: {row[2]}')

asyncio.run(main())
" 2>&1 | tail -10
