"""
路由模块 — M8 路由层
已实现路由统一导出，app.py 通过 include_router 注册。
"""
from fastapi import APIRouter

from .system import router as system_router
from .funds import router as funds_router
from .assets import router as assets_router
from .data import router as data_router
from .formulas import router as formulas_router
from .watchlist import router as watchlist_router
from .alerts import router as alerts_router
from .admin import router as admin_router
from .stream import router as stream_router

main_router = APIRouter()
main_router.include_router(system_router)
main_router.include_router(funds_router)
main_router.include_router(assets_router)
main_router.include_router(data_router)
main_router.include_router(formulas_router)
main_router.include_router(watchlist_router)
main_router.include_router(alerts_router)
main_router.include_router(admin_router)
main_router.include_router(stream_router)

__all__ = ["main_router"]
