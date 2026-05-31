# -*- coding: utf-8 -*-
"""
认证层测试（14项）
"""
import pytest
import jwt
import time
from unittest.mock import MagicMock, patch
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from auth.middleware import AuthMiddleware
from auth.dependencies import get_user_id, require_admin, get_optional_user
from exceptions import (
    AUTH_NO_TOKEN,
    AUTH_TOKEN_EXPIRED,
    AUTH_TOKEN_INVALID,
    AUTH_TOKEN_MALFORMED,
    AUTH_TOKEN_MISSING_FIELDS,
    PERM_NOT_ADMIN,
)


# 测试密钥
TEST_JWT_SECRET = "test-secret-key-for-testing-only"
TEST_ADMIN_EMAIL = "admin@example.com"
TEST_USER_EMAIL = "user@example.com"


def create_test_token(payload: dict, secret: str = TEST_JWT_SECRET, expired: bool = False) -> str:
    """创建测试用JWT token"""
    if expired:
        payload["exp"] = int(time.time()) - 3600
    else:
        payload["exp"] = int(time.time()) + 3600
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture
def app():
    """创建测试用FastAPI应用"""
    app = FastAPI()
    
    # 添加中间件
    with patch("backend.config.Config.SUPABASE_JWT_SECRET", TEST_JWT_SECRET), \
         patch("backend.config.Config.ADMIN_EMAILS", TEST_ADMIN_EMAIL):
        app.add_middleware(AuthMiddleware)
    
    # 公开路由
    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok"}
    
    # 需要登录的路由
    @app.get("/api/v1/funds")
    async def get_funds(user_id: str = get_user_id):
        return {"user_id": user_id}
    
    # 可选登录的路由
    @app.get("/api/v1/funds/{code}")
    async def get_fund(code: str, user_id: str = get_optional_user):
        return {"code": code, "user_id": user_id}
    
    # 管理员路由
    @app.get("/api/v1/admin/monitor")
    async def admin_monitor(user_id: str = require_admin):
        return {"admin": user_id}
    
    return app


@pytest.fixture
def client(app):
    """创建测试客户端"""
    return TestClient(app)


class TestAuth:
    """认证测试"""
    
    def test_01_public_route_no_token(self, client):
        """测试1: 无token请求公开路由 - 正常响应"""
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
    
    def test_02_protected_route_no_token(self, client):
        """测试2: 无token请求需登录路由 - 40101"""
        response = client.get("/api/v1/funds")
        assert response.status_code == 401
        data = response.json()
        assert data["code"] == AUTH_NO_TOKEN
        assert data["message"] == "请先登录"
    
    def test_03_valid_token(self, client):
        """测试3: 有效token请求 - 正常响应"""
        token = create_test_token({"sub": "user-123", "email": TEST_USER_EMAIL})
        response = client.get(
            "/api/v1/funds",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert response.json()["user_id"] == "user-123"
    
    def test_04_expired_token(self, client):
        """测试4: 过期token - 40102"""
        token = create_test_token({"sub": "user-123"}, expired=True)
        response = client.get(
            "/api/v1/funds",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 401
        data = response.json()
        assert data["code"] == AUTH_TOKEN_EXPIRED
    
    def test_05_invalid_token(self, client):
        """测试5: 伪造token - 40103"""
        response = client.get(
            "/api/v1/funds",
            headers={"Authorization": "Bearer invalid-token-here"}
        )
        assert response.status_code == 401
        data = response.json()
        assert data["code"] == AUTH_TOKEN_INVALID
    
    def test_06_malformed_header(self, client):
        """测试6: 格式错误header - 40104"""
        response = client.get(
            "/api/v1/funds",
            headers={"Authorization": "InvalidFormat token"}
        )
        assert response.status_code == 401
        data = response.json()
        assert data["code"] == AUTH_TOKEN_MALFORMED
    
    def test_07_missing_sub_field(self, client):
        """测试7: payload缺sub - 40105"""
        token = create_test_token({"email": TEST_USER_EMAIL})
        response = client.get(
            "/api/v1/funds",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 401
        data = response.json()
        assert data["code"] == AUTH_TOKEN_MISSING_FIELDS
    
    def test_08_non_admin_access_admin_route(self, client):
        """测试8: 普通用户访问管理员路由 - 40301"""
        token = create_test_token({"sub": "user-123", "email": TEST_USER_EMAIL})
        response = client.get(
            "/api/v1/admin/monitor",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403
        data = response.json()
        assert data["code"] == PERM_NOT_ADMIN
    
    def test_09_admin_access_admin_route(self, client):
        """测试9: 管理员访问管理员路由 - 正常"""
        token = create_test_token({"sub": "admin-123", "email": TEST_ADMIN_EMAIL})
        response = client.get(
            "/api/v1/admin/monitor",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
    
    def test_10_optional_auth_no_token(self, client):
        """测试10: 可选登录路由无token - 正常"""
        response = client.get("/api/v1/funds/160644")
        assert response.status_code == 200
        assert response.json()["user_id"] is None
    
    def test_11_optional_auth_with_token(self, client):
        """测试11: 可选登录路由有token - 正常"""
        token = create_test_token({"sub": "user-123", "email": TEST_USER_EMAIL})
        response = client.get(
            "/api/v1/funds/160644",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert response.json()["user_id"] == "user-123"
    
    def test_12_cors_preflight(self, client):
        """测试12: CORS预检请求 - 200"""
        response = client.options(
            "/api/v1/funds",
            headers={
                "Origin": "https://jinkuaicha.com",
                "Access-Control-Request-Method": "GET",
            }
        )
        assert response.status_code == 200
    
    def test_13_error_response_with_cors(self, client):
        """测试13: 错误响应带CORS header"""
        response = client.get(
            "/api/v1/funds",
            headers={"Origin": "https://jinkuaicha.com"}
        )
        assert response.status_code == 401
        assert "access-control-allow-origin" in response.headers
    
    def test_14_user_id_truncated_in_log(self, client):
        """测试14: 用户ID在日志中被截断（只记录前8位）"""
        token = create_test_token({"sub": "a1b2c3d4e5f6g7h8i9j0", "email": TEST_USER_EMAIL})
        with patch("backend.auth.middleware.logger") as mock_logger:
            client.get(
                "/api/v1/funds",
                headers={"Authorization": f"Bearer {token}"}
            )
            # 检查日志调用
            mock_logger.info.assert_called()
            log_message = mock_logger.info.call_args[0][0]
            assert "user=a1b2c3d4" in log_message
