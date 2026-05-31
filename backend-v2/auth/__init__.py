"""
认证模块 — M2 认证层

依赖: config, exceptions
被依赖: routers, hub
对外接口:
  - AuthMiddleware: JWT 验证中间件
  - get_user_id: FastAPI Depends 注入当前用户ID
  - require_admin: FastAPI Depends 管理员权限校验
  - get_optional_user: FastAPI Depends 可选用户（公开端点也用）
"""