"""Layer 3: Endpoint unit logic - direct handler calls with mocks.

Scope:
- Success and failure branches per handler
- ValueError -> HTTPException(400) mapping
- Behavior depending on mocked repo/traffic-manager state
- Aggregation decisions in GET /ues/stats
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from epc import api
from epc.models import (
    AddBearerRequest,
    AttachUERequest,
    BearerConfig,
    StartTrafficRequest,
    ThroughputStats,
    UEState,
)


def _state(
    ue_id: int = 1,
    bearers: dict[int, BearerConfig] | None = None,
    stats: dict[int, ThroughputStats] | None = None,
) -> UEState:
    return UEState(
        ue_id=ue_id,
        bearers=bearers if bearers is not None else {9: BearerConfig(bearer_id=9)},
        stats=stats if stats is not None else {},
    )


def _patch_traffic_manager(monkeypatch: pytest.MonkeyPatch, manager: MagicMock) -> MagicMock:
    monkeypatch.setattr(api, "get_traffic_manager", MagicMock(return_value=manager))
    return manager


def _assert_http_400(exc_info: pytest.ExceptionInfo[HTTPException], detail: str) -> None:
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == detail


def test_list_ues_returns_repo_ids(mock_repo):
    mock_repo.list_ues.return_value = iter([1, 3, 7])

    response = api.list_ues(repo=mock_repo)

    assert response.ues == [1, 3, 7]
    mock_repo.list_ues.assert_called_once_with()


def test_attach_ue_success(mock_repo):
    response = api.attach_ue(AttachUERequest(ue_id=12), repo=mock_repo)

    assert response.status == "attached"
    assert response.ue_id == 12
    mock_repo.attach_ue.assert_called_once_with(12)


def test_attach_ue_maps_value_error_to_http_400(mock_repo):
    mock_repo.attach_ue.side_effect = ValueError("UE already attached")

    with pytest.raises(HTTPException) as exc_info:
        api.attach_ue(AttachUERequest(ue_id=12), repo=mock_repo)

    _assert_http_400(exc_info, "UE already attached")


def test_get_ue_success(mock_repo):
    mock_repo.get_ue.return_value = _state(ue_id=4)

    response = api.get_ue(4, repo=mock_repo)

    assert response.ue_id == 4
    assert response.bearers[9].bearer_id == 9
    mock_repo.get_ue.assert_called_once_with(4)


def test_get_ue_maps_value_error_to_http_400(mock_repo):
    mock_repo.get_ue.side_effect = ValueError("UE not found")

    with pytest.raises(HTTPException) as exc_info:
        api.get_ue(404, repo=mock_repo)

    _assert_http_400(exc_info, "UE not found")


def test_detach_ue_success(mock_repo):
    response = api.detach_ue(5, repo=mock_repo)

    assert response.status == "detached"
    assert response.ue_id == 5
    mock_repo.detach_ue.assert_called_once_with(5)


def test_detach_ue_maps_value_error_to_http_400(mock_repo):
    mock_repo.detach_ue.side_effect = ValueError("UE not found")

    with pytest.raises(HTTPException) as exc_info:
        api.detach_ue(5, repo=mock_repo)

    _assert_http_400(exc_info, "UE not found")


def test_add_bearer_success(mock_repo):
    response = api.add_bearer(1, AddBearerRequest(bearer_id=2), repo=mock_repo)

    assert response.status == "bearer_added"
    assert response.ue_id == 1
    assert response.bearer_id == 2
    mock_repo.add_bearer.assert_called_once_with(1, 2)


def test_add_bearer_maps_value_error_to_http_400(mock_repo):
    mock_repo.add_bearer.side_effect = ValueError("Bearer already exists")

    with pytest.raises(HTTPException) as exc_info:
        api.add_bearer(1, AddBearerRequest(bearer_id=2), repo=mock_repo)

    _assert_http_400(exc_info, "Bearer already exists")


def test_delete_bearer_stops_running_traffic_before_delete(mock_repo, monkeypatch):
    manager = _patch_traffic_manager(monkeypatch, MagicMock())
    manager.is_running.return_value = True
    mock_repo.get_ue.return_value = _state(
        bearers={9: BearerConfig(bearer_id=9), 2: BearerConfig(bearer_id=2)}
    )

    response = api.delete_bearer(1, 2, repo=mock_repo)

    assert response.status == "bearer_deleted"
    assert response.ue_id == 1
    assert response.bearer_id == 2
    manager.is_running.assert_called_once_with(1, 2)
    manager.stop.assert_called_once_with(1, 2)
    mock_repo.delete_bearer.assert_called_once_with(1, 2)


def test_delete_bearer_missing_bearer_returns_http_400(mock_repo, monkeypatch):
    manager = _patch_traffic_manager(monkeypatch, MagicMock())
    mock_repo.get_ue.return_value = _state()

    with pytest.raises(HTTPException) as exc_info:
        api.delete_bearer(1, 2, repo=mock_repo)

    _assert_http_400(exc_info, "Bearer not found")
    manager.is_running.assert_not_called()
    mock_repo.delete_bearer.assert_not_called()


def test_delete_bearer_maps_repo_delete_error_to_http_400(mock_repo, monkeypatch):
    manager = _patch_traffic_manager(monkeypatch, MagicMock())
    manager.is_running.return_value = False
    mock_repo.get_ue.return_value = _state(
        bearers={9: BearerConfig(bearer_id=9), 2: BearerConfig(bearer_id=2)}
    )
    mock_repo.delete_bearer.side_effect = ValueError("Cannot remove default bearer")

    with pytest.raises(HTTPException) as exc_info:
        api.delete_bearer(1, 2, repo=mock_repo)

    _assert_http_400(exc_info, "Cannot remove default bearer")


def test_start_traffic_configures_bearer_creates_stats_and_starts_manager(mock_repo, monkeypatch):
    manager = _patch_traffic_manager(monkeypatch, MagicMock())
    monkeypatch.setattr(api.time, "time", MagicMock(side_effect=[10.0, 10.5]))
    bearer = BearerConfig(bearer_id=2)
    mock_repo.get_ue.return_value = _state(bearers={2: bearer})
    body = StartTrafficRequest(protocol="tcp", kbps=512)

    response = api.start_traffic(1, 2, body, repo=mock_repo)

    assert response.status == "traffic_started"
    assert response.ue_id == 1
    assert response.bearer_id == 2
    assert response.target_bps == 512_000
    assert bearer.protocol == "tcp"
    assert bearer.target_bps == 512_000
    assert bearer.active is True
    mock_repo.update_bearer.assert_called_once_with(1, bearer)
    stats = mock_repo.update_stats.call_args.args[1]
    assert stats.bearer_id == 2
    assert stats.ue_id == 1
    assert stats.start_ts == 10.0
    assert stats.last_update_ts == 10.5
    assert stats.protocol == "tcp"
    assert stats.target_bps == 512_000
    manager.start.assert_called_once_with(1, bearer)


def test_start_traffic_does_not_create_initial_stats_when_stats_exist(mock_repo, monkeypatch):
    manager = _patch_traffic_manager(monkeypatch, MagicMock())
    bearer = BearerConfig(bearer_id=2)
    mock_repo.get_ue.return_value = _state(
        bearers={2: bearer},
        stats={2: ThroughputStats(bearer_id=2, ue_id=1, start_ts=1.0)},
    )

    api.start_traffic(1, 2, StartTrafficRequest(protocol="udp", bps=100), repo=mock_repo)

    mock_repo.update_stats.assert_not_called()
    manager.start.assert_called_once_with(1, bearer)


def test_start_traffic_missing_bearer_returns_http_400(mock_repo, monkeypatch):
    manager = _patch_traffic_manager(monkeypatch, MagicMock())
    mock_repo.get_ue.return_value = _state()

    with pytest.raises(HTTPException) as exc_info:
        api.start_traffic(1, 2, StartTrafficRequest(protocol="tcp", bps=100), repo=mock_repo)

    _assert_http_400(exc_info, "Bearer not found")
    mock_repo.update_bearer.assert_not_called()
    manager.start.assert_not_called()


def test_start_traffic_maps_manager_value_error_to_http_400(mock_repo, monkeypatch):
    manager = _patch_traffic_manager(monkeypatch, MagicMock())
    manager.start.side_effect = ValueError("Traffic already running")
    bearer = BearerConfig(bearer_id=2)
    mock_repo.get_ue.return_value = _state(bearers={2: bearer})

    with pytest.raises(HTTPException) as exc_info:
        api.start_traffic(1, 2, StartTrafficRequest(protocol="udp", bps=100), repo=mock_repo)

    _assert_http_400(exc_info, "Traffic already running")


def test_stop_traffic_success_marks_bearer_inactive(mock_repo, monkeypatch):
    manager = _patch_traffic_manager(monkeypatch, MagicMock())
    bearer = BearerConfig(bearer_id=2, active=True)
    mock_repo.get_ue.return_value = _state(bearers={2: bearer})

    response = api.stop_traffic(1, 2, repo=mock_repo)

    assert response.status == "traffic_stopped"
    assert response.ue_id == 1
    assert response.bearer_id == 2
    assert bearer.active is False
    manager.stop.assert_called_once_with(1, 2)
    mock_repo.update_bearer.assert_called_once_with(1, bearer)


def test_stop_traffic_missing_bearer_returns_http_400(mock_repo, monkeypatch):
    manager = _patch_traffic_manager(monkeypatch, MagicMock())
    mock_repo.get_ue.return_value = _state()

    with pytest.raises(HTTPException) as exc_info:
        api.stop_traffic(1, 2, repo=mock_repo)

    _assert_http_400(exc_info, "Bearer not found")
    manager.stop.assert_not_called()
    mock_repo.update_bearer.assert_not_called()


def test_get_traffic_stats_returns_zeroes_without_stats(mock_repo):
    mock_repo.get_ue.return_value = _state()

    response = api.get_traffic_stats(1, 2, repo=mock_repo)

    assert response.ue_id == 1
    assert response.bearer_id == 2
    assert response.protocol is None
    assert response.target_bps is None
    assert response.tx_bps == 0
    assert response.rx_bps == 0
    assert response.duration == 0


def test_get_traffic_stats_uses_last_update_for_stopped_traffic(mock_repo, monkeypatch):
    manager = _patch_traffic_manager(monkeypatch, MagicMock())
    manager.is_running.return_value = False
    mock_repo.get_ue.return_value = _state(
        stats={
            2: ThroughputStats(
                bearer_id=2,
                ue_id=1,
                bytes_tx=1_000,
                bytes_rx=500,
                start_ts=10.0,
                last_update_ts=20.0,
                protocol="tcp",
                target_bps=800,
            )
        }
    )

    response = api.get_traffic_stats(1, 2, repo=mock_repo)

    assert response.duration == 10.0
    assert response.tx_bps == 800
    assert response.rx_bps == 400
    assert response.protocol == "tcp"
    assert response.target_bps == 800


def test_get_traffic_stats_uses_current_time_for_running_traffic(mock_repo, monkeypatch):
    manager = _patch_traffic_manager(monkeypatch, MagicMock())
    manager.is_running.return_value = True
    monkeypatch.setattr(api.time, "time", MagicMock(return_value=30.0))
    mock_repo.get_ue.return_value = _state(
        stats={
            2: ThroughputStats(
                bearer_id=2,
                ue_id=1,
                bytes_tx=2_000,
                bytes_rx=1_000,
                start_ts=10.0,
                last_update_ts=12.0,
                protocol="udp",
                target_bps=1000,
            )
        }
    )

    response = api.get_traffic_stats(1, 2, repo=mock_repo)

    assert response.duration == 20.0
    assert response.tx_bps == 800
    assert response.rx_bps == 400


def test_get_ues_stats_aggregates_all_ues_with_details(mock_repo, monkeypatch):
    manager = _patch_traffic_manager(monkeypatch, MagicMock())
    manager.is_running.return_value = False
    mock_repo.list_ues.return_value = iter([1, 2])
    mock_repo.get_ue.side_effect = [
        _state(
            ue_id=1,
            stats={
                2: ThroughputStats(
                    bearer_id=2,
                    ue_id=1,
                    bytes_tx=1_000,
                    bytes_rx=500,
                    start_ts=10.0,
                    last_update_ts=20.0,
                )
            },
        ),
        _state(
            ue_id=2,
            stats={
                3: ThroughputStats(
                    bearer_id=3,
                    ue_id=2,
                    bytes_tx=3_000,
                    bytes_rx=1_500,
                    start_ts=10.0,
                    last_update_ts=30.0,
                )
            },
        ),
    ]

    response = api.get_ues_stats(repo=mock_repo, include_details=True)

    assert response.scope == "all"
    assert response.ue_count == 2
    assert response.bearer_count == 2
    assert response.total_tx_bps == 2_000
    assert response.total_rx_bps == 1_000
    assert response.details == {"1": {"2": 800}, "2": {"3": 1200}}


def test_get_ues_stats_for_missing_requested_ue_returns_http_400(mock_repo):
    mock_repo.ue_exists.return_value = False

    with pytest.raises(HTTPException) as exc_info:
        api.get_ues_stats(repo=mock_repo, ue_id=99)

    _assert_http_400(exc_info, "UE not found")
    mock_repo.get_ue.assert_not_called()


def test_get_ues_stats_skips_missing_ue_during_all_aggregation(mock_repo, monkeypatch):
    _patch_traffic_manager(monkeypatch, MagicMock())
    mock_repo.list_ues.return_value = iter([1])
    mock_repo.get_ue.side_effect = ValueError("UE not found")

    response = api.get_ues_stats(repo=mock_repo)

    assert response.scope == "all"
    assert response.ue_count == 1
    assert response.bearer_count == 0
    assert response.total_tx_bps == 0
    assert response.total_rx_bps == 0
    assert response.details is None


def test_get_ues_stats_requested_ue_get_error_returns_http_400(mock_repo, monkeypatch):
    _patch_traffic_manager(monkeypatch, MagicMock())
    mock_repo.ue_exists.return_value = True
    mock_repo.get_ue.side_effect = ValueError("UE not found")

    with pytest.raises(HTTPException) as exc_info:
        api.get_ues_stats(repo=mock_repo, ue_id=1)

    _assert_http_400(exc_info, "UE not found")


def test_reset_all_stops_traffic_and_resets_repo(mock_repo, monkeypatch):
    manager = _patch_traffic_manager(monkeypatch, MagicMock())

    response = api.reset_all(repo=mock_repo)

    assert response.status == "reset"
    manager.stop_all.assert_called_once_with()
    mock_repo.reset_all.assert_called_once_with()
