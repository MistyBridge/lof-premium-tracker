"""
异常类层级 + 错误码 + 全局处理器

错误码规范:
  400xx — 参数/校验错误
  401xx — 认证错误
  403xx — 权限错误
  404xx — 资源不存在
  409xx — 冲突
  429xx — 限流
  500xx — 服务器内部错误
  503xx — 服务不可用
"""
import logging
import traceback
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import psutil
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

logger = logging.getLogger("app")

# ── 异常类层级 ─────────────────────────────────────────────


class AppException(Exception):
    """应用基础异常 — 所有业务异常的父类"""

    def __init__(
        self,
        code: int = 50000,
        message: str = "服务器内部错误",
        detail: Any = None,
        status_code: int = 500,
    ):
        self.code = code
        self.message = message
        self.detail = detail
        self.status_code = status_code


# -- 400 参数错误 --

class BadRequestException(AppException):
    """40001 参数不合法"""
    def __init__(self, message: str = "参数不合法", detail: Any = None):
        super().__init__(code=40001, message=message, detail=detail, status_code=400)


class FormulaParseException(AppException):
    """40002 公式解析失败"""
    def __init__(self, message: str = "公式解析失败", detail: Any = None):
        super().__init__(code=40002, message=message, detail=detail, status_code=400)


# -- 401 认证 --

class UnauthorizedException(AppException):
    """40100 未授权（通用）"""
    def __init__(self, message: str = "未授权", detail: Any = None, code: int = 40100):
        super().__init__(code=code, message=message, detail=detail, status_code=401)


class TokenInvalidException(AppException):
    """40101 Token 无效"""
    def __init__(self, message: str = "Token 无效"):
        super().__init__(code=40101, message=message, status_code=401)


class TokenExpiredException(AppException):
    """40102 Token 过期"""
    def __init__(self, message: str = "Token 已过期"):
        super().__init__(code=40102, message=message, status_code=401)


# -- 403 权限 --

class ForbiddenException(AppException):
    """40300 禁止访问（通用）"""
    def __init__(self, message: str = "禁止访问", detail: Any = None):
        super().__init__(code=40300, message=message, detail=detail, status_code=403)


class AdminRequiredException(AppException):
    """40301 需要管理员权限"""
    def __init__(self, message: str = "需要管理员权限", code: int = 40301):
        super().__init__(code=code, message=message, status_code=403)


# -- 404 资源不存在 --

class NotFoundException(AppException):
    """40400 资源不存在"""
    def __init__(self, message: str = "资源不存在", detail: Any = None):
        super().__init__(code=40400, message=message, detail=detail, status_code=404)


# -- 409 冲突 --

class ConflictException(AppException):
    """40900 冲突（乐观锁等）"""
    def __init__(self, message: str = "资源冲突", detail: Any = None):
        super().__init__(code=40900, message=message, detail=detail, status_code=409)


# -- 429 限流 --

class RateLimitException(AppException):
    """42900 请求过于频繁"""
    def __init__(self, message: str = "请求过于频繁"):
        super().__init__(code=42900, message=message, status_code=429)


# -- 503 服务不可用 --

class ServiceUnavailableException(AppException):
    """50300 服务暂不可用"""
    def __init__(self, message: str = "服务暂不可用", detail: Any = None):
        super().__init__(code=50300, message=message, detail=detail, status_code=503)


# ── auth 模块兼容别名 ──────────────────────────────────────
# auth/middleware.py 和 auth/dependencies.py 使用以下名称

AUTH_TOKEN_EXPIRED = 40102
AUTH_TOKEN_INVALID = 40101
AUTH_TOKEN_MALFORMED = 40104
AUTH_TOKEN_MISSING_FIELDS = 40103
AUTH_NO_TOKEN = 40101
PERM_NOT_ADMIN = 40301


class AuthException(AppException):
    """认证异常（auth 中间件专用）"""
    def __init__(self, code: int = 40100, message: str = "认证失败", detail: Any = None):
        super().__init__(code=code, message=message, detail=detail, status_code=401)


class PermissionException(AppException):
    """权限异常（auth 依赖专用）"""
    def __init__(self, code: int = 40300, message: str = "权限不足", detail: Any = None):
        super().__init__(code=code, message=message, detail=detail, status_code=403)


class ValidationException(AppException):
    """校验异常（formula_engine 专用）"""
    def __init__(self, code: int = 40001, message: str = "校验失败", detail: Any = None):
        super().__init__(code=code, message=message, detail=detail, status_code=400)


# ── 错误现场快照 ───────────────────────────────────────────

SNAPSHOT_DIR = Path("logs/snapshots")
MAX_SNAPSHOTS = 50


async def save_snapshot(request_id: str, request_params: dict, exc: Exception):
    """50000 异常时保存现场快照（不含敏感信息）"""
    try:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "request_params": request_params,
            "memory_mb": round(psutil.Process().memory_info().rss / 1024 / 1024, 1),
        }
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{request_id}.json"
        filepath = SNAPSHOT_DIR / filename
        filepath.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

        # 清理旧快照
        snapshots = sorted(SNAPSHOT_DIR.glob("*.json"))
        while len(snapshots) > MAX_SNAPSHOTS:
            snapshots.pop(0).unlink()
    except Exception:
        logger.error("快照保存失败", exc_info=True)


# ── 全局异常处理器注册 ─────────────────────────────────────

def register_exception_handlers(app):
    """注册全局异常处理器到 FastAPI app"""

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "detail": exc.detail,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        errors = []
        for e in exc.errors():
            errors.append({
                "field": ".".join(str(loc) for loc in e["loc"]),
                "error": e["msg"],
            })
        return JSONResponse(
            status_code=400,
            content={"code": 40001, "message": "参数不合法", "detail": errors},
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("未处理异常: %s", exc, exc_info=True)
        await save_snapshot(
            getattr(request.state, "request_id", "unknown"),
            dict(request.query_params),
            exc,
        )
        return JSONResponse(
            status_code=500,
            content={"code": 50000, "message": "服务器内部错误", "detail": None},
        )


# ── 公式引擎 + 查询错误码常量 ─────────────────────────────

FORMULA_SYNTAX_ERROR = 40002
FORMULA_INVALID_FIELD = 40003
FORMULA_COMPLEXITY_EXCEEDED = 40004
QUERY_TOO_MANY_CODES = 40005