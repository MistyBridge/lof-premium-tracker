"""
M8 路由层集成测试 -- 20项
pytest tests/test_routers.py -v
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MOCK_METHODS = [
    "get_health", "get_fund_list", "get_fund_detail", "get_fund_batch",
    "get_fund_chart", "get_fund_holdings", "get_asset_list", "get_asset_detail",
    "get_asset_funds", "get_asset_chart", "get_fund_daily", "get_asset_daily",
    "batch_query", "list_formulas", "get_formula", "create_formula",
    "update_formula", "delete_formula", "validate_expression",
    "list_formula_groups", "create_formula_group", "update_formula_group",
    "delete_formula_group", "list_alerts", "create_alert", "delete_alert",
    "toggle_alert", "get_monitor", "diagnose_redis", "diagnose_db",
    "diagnose_fetcher", "diagnose_queue", "diagnose_fund",
    "ops_mv_refresh", "ops_cache_clear", "get_audit_log",
]

@pytest.fixture
def mock_hub():
    hub = MagicMock()
    for m in MOCK_METHODS:
        setattr(hub, m, AsyncMock(return_value={}))
    hub.get_health.return_value = {"status": "ok", "version": "2.0.0"}
    hub.get_fund_list.return_value = {
        "data": [{"code": "160644", "name": "test", "close": 1.0}],
        "meta": {"page": 1, "size": 50, "total": 1, "realtime_available": False},
    }
    hub.get_fund_detail.return_value = {"code": "160644", "name": "test"}
    hub.get_fund_batch.return_value = [{"code": "160644"}]
    hub.get_fund_chart.return_value = [{"trade_date": "2026-05-29", "close": 1.0}]
    hub.get_fund_holdings.return_value = {"code": "160644", "holdings": []}
    hub.get_asset_list.return_value = {"data": [], "meta": {"total": 0}}
    hub.create_formula.return_value = {"id": 1, "name": "test", "version": 1}
    hub.update_formula.return_value = {"id": 1, "version": 2}
    hub.create_alert.return_value = {"id": 1, "name": "test_alert"}
    hub.get_monitor.return_value = {"cpu_pct": 10, "mem_pct": 50}
    return hub


@pytest.fixture
def client(mock_hub):
    from hub import get_hub
    import app as app_module
    app_module.app.dependency_overrides[get_hub] = lambda: mock_hub
    from fastapi.testclient import TestClient
    c = TestClient(app_module.app, raise_server_exceptions=False)
    yield c
    app_module.app.dependency_overrides.clear()


def _uid():
    from auth.dependencies import get_user_id
    from app import app
    app.dependency_overrides[get_user_id] = lambda: "u-1"

def _adm():
    from auth.dependencies import require_admin
    from app import app
    app.dependency_overrides[require_admin] = lambda: "a-1"

# cleanup handled by conftest.py autouse fixture


# T1: health 200 + fields
class TestT01Health:
    def test_health_200(self, client):
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        assert "status" in r.json()
        assert "version" in r.json()

    def test_health_ok(self, client):
        assert client.get("/api/v1/health").json()["status"] == "ok"


# T2: fund list
class TestT02FundList:
    def test_200(self, client):
        r = client.get("/api/v1/funds")
        assert r.status_code == 200
        d = r.json()
        assert "data" in d and "meta" in d

    def test_pagination(self, client, mock_hub):
        client.get("/api/v1/funds?page=2&size=10&sort=premium_rate&order=desc")
        mock_hub.get_fund_list.assert_called()


# T3: fund detail
class TestT03FundDetail:
    def test_200(self, client):
        r = client.get("/api/v1/funds/160644")
        assert r.status_code == 200
        assert r.json()["code"] == "160644"


# T4: fund batch
class TestT04FundBatch:
    def test_200(self, client):
        r = client.get("/api/v1/funds/batch?codes=160644,160716")
        assert r.status_code == 200


# T5: fund chart
class TestT05FundChart:
    def test_200(self, client):
        r = client.get("/api/v1/funds/160644/chart?days=7")
        assert r.status_code == 200


# T6: fund holdings
class TestT06FundHoldings:
    def test_200(self, client):
        r = client.get("/api/v1/funds/160644/holdings")
        assert r.status_code == 200


# T7: rankings
class TestT07Rankings:
    def test_200(self, client):
        r = client.get("/api/v1/funds/rankings")
        assert r.status_code == 200



# T8: formulas CRUD
class TestT08Formulas:
    def test_list(self, client):
        _uid()
        assert client.get("/api/v1/formulas").status_code == 200

    def test_create(self, client, mock_hub):
        _uid()
        r = client.post("/api/v1/formulas", json={"name": "t", "expression": "close/nav-1"})
        assert r.status_code == 200
        mock_hub.create_formula.assert_called_once()

    def test_delete(self, client, mock_hub):
        _uid()
        r = client.delete("/api/v1/formulas/1")
        assert r.status_code == 200
        assert r.json()["deleted"] is True


# T9: optimistic lock 409
class TestT09OptimisticLock:
    def test_409(self, client, mock_hub):
        from exceptions import ConflictException
        _uid()
        mock_hub.update_formula.side_effect = ConflictException("version conflict")
        r = client.put("/api/v1/formulas/1?version=1", json={"name": "x"})
        assert r.status_code == 409
        assert r.json()["code"] == 40900
        mock_hub.update_formula.side_effect = None


# T10: watchlist add (mock hub._sf as async context manager)
class TestT10Watchlist:
    def test_add(self, client, mock_hub):
        _uid()
        # watchlist router uses hub._sf directly, need to mock it
        mock_session = MagicMock()
        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_hub._sf = MagicMock(return_value=mock_session_ctx)
        r = client.post("/api/v1/watchlist", json={"fund_code": "160644"})
        assert r.status_code == 200


# T11: alert create
class TestT11Alerts:
    def test_create(self, client, mock_hub):
        _uid()
        r = client.post("/api/v1/alerts", json={
            "name": "test", "condition": {"op": "and", "conditions": [{"field": "premium_rate", "op": ">", "value": 5}]}
        })
        assert r.status_code == 200
        mock_hub.create_alert.assert_called_once()


# T12: admin no token -> 401
class TestT12AdminNoToken:
    def test_401(self, client):
        assert client.get("/api/v1/admin/monitor").status_code == 401


# T13: admin normal user -> 403
class TestT13AdminForbidden:
    def test_403(self, client):
        from auth.dependencies import require_admin
        from app import app
        from exceptions import AdminRequiredException
        app.dependency_overrides[require_admin] = AsyncMock(side_effect=AdminRequiredException())
        assert client.get("/api/v1/admin/monitor").status_code == 403


# T14: admin access -> 200
class TestT14AdminAccess:
    def test_200(self, client, mock_hub):
        _adm()
        assert client.get("/api/v1/admin/monitor").status_code == 200


# T15: data daily query
class TestT15DataQuery:
    def test_fund_daily(self, client, mock_hub):
        r = client.get("/api/v1/data/fund/160644?limit=30")
        assert r.status_code == 200


# T16: error format
class TestT16ErrorFormat:
    def test_404_format(self, client, mock_hub):
        from exceptions import NotFoundException
        mock_hub.get_fund_detail.side_effect = NotFoundException("not found")
        r = client.get("/api/v1/funds/999999")
        assert r.status_code == 404
        d = r.json()
        assert "code" in d and "message" in d and isinstance(d["code"], int)
        mock_hub.get_fund_detail.side_effect = None


# T17: formula groups
class TestT17FormulaGroups:
    def test_list(self, client):
        _uid()
        assert client.get("/api/v1/formulas/groups").status_code == 200


# T18: admin diagnose
class TestT18AdminDiagnose:
    def test_redis(self, client, mock_hub):
        _adm()
        assert client.get("/api/v1/admin/diagnose/redis").status_code == 200


# T19: sort validation
class TestT19SortValidation:
    def test_invalid_sort(self, client):
        assert client.get("/api/v1/funds?sort=xxx").status_code == 200


# T20: root
class TestT20Root:
    def test_root(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "v2" in r.json()["message"].lower() or "金快查" in r.json()["message"]
