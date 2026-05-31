# -*- coding: utf-8 -*-
"""
路由层权限声明（3个Depends函数）
"""
from fastapi import Request, Depends
from typing import Optional

from exceptions import (
    AuthException,
    PermissionException,
    AUTH_NO_TOKEN,
    PERM_NOT_ADMIN,
)


async def get_user_id(request: Request) -> str:
    """
    获取用户ID（必须登录）
    
    从 request.state 取 user_id，为 None → 抛 AuthException(40101)
    
    使用场景：必须登录的路由（基金列表、公式 CRUD）
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise AuthException(
            code=AUTH_NO_TOKEN,
            message="请先登录"
        )
    return user_id


async def require_admin(request: Request) -> str:
    """
    要求管理员权限
    
    从 request.state 取 role，不是 "admin" → 抛 PermissionException(40301)
    
    使用场景：管理员路由（监控、操作、日志）
    """
    role = getattr(request.state, "role", "anonymous")
    if role != "admin":
        raise PermissionException(
            code=PERM_NOT_ADMIN,
            message="需要管理员权限"
        )
    return request.state.user_id


async def get_optional_user(request: Request) -> Optional[str]:
    """
    获取可选用户ID
    
    从 request.state 取 user_id，为 None → 返回 None（不报错）
    
    使用场景：可选登录的路由（基金详情，登录后返回个性化数据）
    """
    return getattr(request.state, "user_id", None)
