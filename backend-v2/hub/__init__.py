"""
Hub 编排模块 — M6 服务层

依赖: services, cache, metrics
被依赖: routers
对外接口:
  - ServiceHub: 编排器，跨 Service 协调 + 缓存失效
  - get_hub: FastAPI Depends 注入
"""
from hub.service import ServiceHub


async def get_hub() -> ServiceHub:
    """FastAPI 依赖注入 — 从 database 模块获取 session_factory"""
    from database import async_session_factory
    return ServiceHub(async_session_factory)