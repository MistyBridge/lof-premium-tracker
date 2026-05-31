"""
pytest 全局配置
"""
import os

# 测试环境变量（在任何模块导入前设置）
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_EMAILS", "admin@test.com")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest


@pytest.fixture(autouse=True)
def _reset_overrides():
    """每个测试结束后清理 dependency_overrides"""
    yield
    from app import app
    app.dependency_overrides.clear()
