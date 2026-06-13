"""Shared pytest fixtures for slim_epc_v2 test layers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from epc.api import get_repo
from epc.db import EPCRepository
from main import app


@pytest.fixture
def temp_db(tmp_path):
    """Temporary SQLite database file for isolated repository tests."""
    return tmp_path / "test_epc.db"


@pytest.fixture
def repo(temp_db):
    """EPCRepository backed by a temporary database file."""
    return EPCRepository(db_path=str(temp_db))


@pytest.fixture
def repo_with_ue(repo):
    """Repository with a single attached UE (default bearer 9)."""
    repo.attach_ue(1)
    return repo


@pytest.fixture
def mock_repo():
    """Mock EPCRepository for endpoint unit tests."""
    return MagicMock(spec=EPCRepository)


@pytest.fixture
def mock_traffic_manager():
    """Mock TrafficGeneratorManager for endpoint unit tests."""
    manager = MagicMock()
    manager.is_running.return_value = False
    return manager


@pytest.fixture
def test_client(repo):
    """FastAPI TestClient with repository dependency override."""
    import epc.api as api_module
    import epc.traffic as traffic_module

    api_module._repo_singleton = None
    if traffic_module.traffic_manager is not None:
        traffic_module.traffic_manager.stop_all()

    app.dependency_overrides[get_repo] = lambda: repo
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    api_module._repo_singleton = None
