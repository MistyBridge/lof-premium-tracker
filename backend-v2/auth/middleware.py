# -*- coding: utf-8 -*-
"""
JWT验证中间件 + 身份注入 + 请求日志
"""
import jwt
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from typing import Optional

from exceptions import (
    AuthException,
    AUTH_TOKEN_EXPIRED,
    AUTH_TOKEN_INVALID,
    AUTH_TOKEN_MALFORMED,
    AUTH_TOKEN_MISSING_FIELDS,
)

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    JWT认证中间件
    
    执行顺序：CORSMiddleware（最外层） → AuthMiddleware（内层） → 路由
    
    处理流程：
    1. 提取 Authorization header
    2. header 不存在 → 设置 request.state = {user_id: None, email: None, role: "anonymous"}，放行
    3. header 存在但格式错误 → 抛 AuthException(40104)
    4. 提取 token 部分，调用 jwt.decode
    5. 从 payload 提取信息并注入 request.state
    6. 记录请求日志
    7. 放行
    """
    
    def __init__(self, app):
        super().__init__(app)
        # 从 config 模块读取配置
        from config import Settings
        _settings = Settings()
        admin_emails_str = _settings.ADMIN_EMAILS or ""
        self.admin_emails = set(
            email.strip() for email in admin_emails_str.split(",") if email.strip()
        )
        self.jwt_secret = _settings.SUPABASE_JWT_SECRET
    
    async def dispatch(self, request: Request, call_next) -> Response:
        # 初始化默认身份信息
        request.state.user_id = None
        request.state.email = None
        request.state.role = "anonymous"
        
        # 提取Authorization header
        auth_header = request.headers.get("Authorization")
        
        if not auth_header:
            # 无token，匿名访问
            logger.info(
                f"[AUTH] anonymous method={request.method} path={request.url.path}"
            )
            return await call_next(request)
        
        # 检查格式：必须是 "Bearer xxx"
        parts = auth_header.split()
        if len(parts) != 2 or parts[0] != "Bearer":
            logger.warning(
                f"[AUTH] REJECTED code={AUTH_TOKEN_MALFORMED} ip={request.client.host if request.client else 'unknown'}"
            )
            raise AuthException(
                code=AUTH_TOKEN_MALFORMED,
                message="请求凭证格式不正确",
                detail=f"Expected 'Bearer <token>', got '{auth_header[:20]}...'"
            )
        
        token = parts[1]
        
        try:
            # 解码JWT
            payload = jwt.decode(
                token,
                self.jwt_secret,
                algorithms=["HS256"],
                options={"verify_aud": False}  # Supabase的aud字段不固定
            )
            
            # 提取用户信息
            user_id = payload.get("sub")
            if not user_id:
                raise AuthException(
                    code=AUTH_TOKEN_MISSING_FIELDS,
                    message="登录信息不完整",
                    detail="Token payload missing 'sub' field"
                )
            
            email = payload.get("email")
            
            # 判断角色
            if email and email in self.admin_emails:
                role = "admin"
            else:
                role = "authenticated"
            
            # 注入到request.state
            request.state.user_id = user_id
            request.state.email = email
            request.state.role = role
            
            # 记录请求日志
            logger.info(
                f"[AUTH] user={user_id[:8]} method={request.method} "
                f"path={request.url.path} ip={request.client.host if request.client else 'unknown'}"
            )
            
        except jwt.ExpiredSignatureError:
            logger.warning(
                f"[AUTH] REJECTED code={AUTH_TOKEN_EXPIRED} ip={request.client.host if request.client else 'unknown'}"
            )
            raise AuthException(
                code=AUTH_TOKEN_EXPIRED,
                message="登录已过期，请重新登录",
                detail="Token has expired"
            )
        except jwt.InvalidTokenError as e:
            logger.warning(
                f"[AUTH] REJECTED code={AUTH_TOKEN_INVALID} ip={request.client.host if request.client else 'unknown'}"
            )
            raise AuthException(
                code=AUTH_TOKEN_INVALID,
                message="无效的登录凭证",
                detail=str(e)
            )
        except AuthException:
            raise
        except Exception as e:
            logger.error(f"[AUTH] Unexpected error: {e}")
            raise AuthException(
                code=AUTH_TOKEN_INVALID,
                message="无效的登录凭证",
                detail=str(e)
            )
        
        return await call_next(request)
