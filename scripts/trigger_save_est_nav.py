"""手动触发 save_est_nav_snapshot 验证写入链路"""
import asyncio
import os
import sys

os.chdir('/opt/jinkuaicha/backend-v2')
sys.path.insert(0, '/opt/jinkuaicha/backend-v2')

import database
import httpx
from config import Settings

async def main():
    s = Settings()
    database.init_engine(s)
    sf = database.async_session_factory

    from services.est_nav_service import save_est_nav_snapshot
    async with httpx.AsyncClient(timeout=30) as client:
        count = await save_est_nav_snapshot(client)
    print(f"save_est_nav_snapshot 返回: {count} 条")

    # 验证表
    from sqlalchemy import text
    async with sf() as session:
        r = await session.execute(text(
            "SELECT trade_date, COUNT(*) FROM fund_est_nav "
            "WHERE trade_date = CURRENT_DATE GROUP BY trade_date"
        ))
        row = r.fetchone()
        print(f"fund_est_nav 今天数据: {row}")

if __name__ == "__main__":
    asyncio.run(main())
