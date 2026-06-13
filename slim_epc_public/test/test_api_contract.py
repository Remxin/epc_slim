"""Layer 4: API contract - TestClient HTTP integration.

Scope:
- HTTP method/path wiring for all endpoints
- Request/response shape and status codes (200/400/422)
- Route-level behavior and end-to-end state transitions through API calls
"""

from __future__ import annotations

import time

import pytest


@pytest.fixture(autouse=True)
def _reset_traffic_manager_singleton():
    """Ensure traffic manager uses the same repo as test_client for this layer."""
    import epc.traffic as traffic_module

    if traffic_module.traffic_manager is not None:
        traffic_module.traffic_manager.stop_all()
    traffic_module.traffic_manager = None
    yield
    if traffic_module.traffic_manager is not None:
        traffic_module.traffic_manager.stop_all()
    traffic_module.traffic_manager = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def attach_ue(client, ue_id: int = 1):
    return client.post("/ues", json={"ue_id": ue_id})


def add_bearer(client, ue_id: int, bearer_id: int):
    return client.post(f"/ues/{ue_id}/bearers", json={"bearer_id": bearer_id})


def start_traffic(client, ue_id: int, bearer_id: int, protocol: str = "tcp", **throughput):
    body = {"protocol": protocol, **throughput}
    return client.post(f"/ues/{ue_id}/bearers/{bearer_id}/traffic", json=body)


def assert_400(response, detail: str):
    assert response.status_code == 400
    assert response.json() == {"detail": detail}


def assert_422(response):
    assert response.status_code == 422
    assert "detail" in response.json()


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------

class TestRootEndpoint:
    def test_health_check_returns_200_with_message(self, test_client):
        response = test_client.get("/")

        assert response.status_code == 200
        assert response.json() == {"message": "EPC Simulator running"}


# ---------------------------------------------------------------------------
# UE lifecycle
# ---------------------------------------------------------------------------

class TestAttachUE:
    def test_attach_ue_success_returns_200_and_creates_default_bearer(self, test_client):
        response = attach_ue(test_client, ue_id=1)

        assert response.status_code == 200
        assert response.json() == {"status": "attached", "ue_id": 1}

        ue = test_client.get("/ues/1").json()
        assert ue["ue_id"] == 1
        assert "9" in ue["bearers"]
        assert ue["bearers"]["9"] == {
            "bearer_id": 9,
            "protocol": None,
            "target_bps": None,
            "active": False,
        }

    def test_attach_duplicate_ue_returns_400(self, test_client):
        attach_ue(test_client, ue_id=1)
        response = attach_ue(test_client, ue_id=1)

        assert_400(response, "UE already attached")

    @pytest.mark.parametrize("ue_id", [0, 101, -1])
    def test_attach_ue_out_of_range_returns_422(self, test_client, ue_id):
        response = attach_ue(test_client, ue_id=ue_id)

        assert_422(response)

    def test_attach_ue_missing_body_field_returns_422(self, test_client):
        response = test_client.post("/ues", json={})

        assert_422(response)

    def test_attach_ue_invalid_type_returns_422(self, test_client):
        response = test_client.post("/ues", json={"ue_id": "not-an-int"})

        assert_422(response)


class TestListUEs:
    def test_list_ues_empty_returns_200(self, test_client):
        response = test_client.get("/ues")

        assert response.status_code == 200
        assert response.json() == {"ues": []}

    def test_list_ues_single_entry(self, test_client):
        attach_ue(test_client, ue_id=5)

        response = test_client.get("/ues")

        assert response.status_code == 200
        assert response.json() == {"ues": [5]}

    def test_list_ues_multiple_sorted_ascending(self, test_client):
        for ue_id in [30, 10, 20]:
            attach_ue(test_client, ue_id=ue_id)

        response = test_client.get("/ues")

        assert response.status_code == 200
        assert response.json() == {"ues": [10, 20, 30]}


class TestGetUE:
    def test_get_ue_success_returns_full_state(self, test_client):
        attach_ue(test_client, ue_id=2)

        response = test_client.get("/ues/2")

        assert response.status_code == 200
        body = response.json()
        assert body["ue_id"] == 2
        assert body["bearers"] == {
            "9": {
                "bearer_id": 9,
                "protocol": None,
                "target_bps": None,
                "active": False,
            }
        }
        assert body["stats"] == {}

    def test_get_ue_not_found_returns_400(self, test_client):
        response = test_client.get("/ues/99")

        assert_400(response, "UE not found")

    def test_get_ue_invalid_path_param_returns_422(self, test_client):
        response = test_client.get("/ues/not-an-int")

        assert_422(response)


class TestDetachUE:
    def test_detach_ue_success_removes_from_list(self, test_client):
        attach_ue(test_client, ue_id=7)

        response = test_client.delete("/ues/7")

        assert response.status_code == 200
        assert response.json() == {"status": "detached", "ue_id": 7}
        assert test_client.get("/ues").json() == {"ues": []}

    def test_detach_ue_not_found_returns_400(self, test_client):
        response = test_client.delete("/ues/99")

        assert_400(response, "UE not found")


# ---------------------------------------------------------------------------
# Bearer management
# ---------------------------------------------------------------------------

class TestAddBearer:
    def test_add_bearer_success_appears_in_ue_state(self, test_client):
        attach_ue(test_client, ue_id=1)

        response = add_bearer(test_client, ue_id=1, bearer_id=3)

        assert response.status_code == 200
        assert response.json() == {
            "status": "bearer_added",
            "ue_id": 1,
            "bearer_id": 3,
        }

        ue = test_client.get("/ues/1").json()
        assert "3" in ue["bearers"]
        assert ue["bearers"]["3"]["active"] is False

    def test_add_bearer_to_missing_ue_returns_400(self, test_client):
        response = add_bearer(test_client, ue_id=99, bearer_id=1)

        assert_400(response, "UE not found")

    def test_add_duplicate_bearer_returns_400(self, test_client):
        attach_ue(test_client, ue_id=1)
        add_bearer(test_client, ue_id=1, bearer_id=1)

        response = add_bearer(test_client, ue_id=1, bearer_id=1)

        assert_400(response, "Bearer already exists")

    @pytest.mark.parametrize("bearer_id", [0, 10, -1])
    def test_add_bearer_out_of_range_returns_422(self, test_client, bearer_id):
        attach_ue(test_client, ue_id=1)

        response = add_bearer(test_client, ue_id=1, bearer_id=bearer_id)

        assert_422(response)

    def test_add_bearer_missing_body_field_returns_422(self, test_client):
        attach_ue(test_client, ue_id=1)

        response = test_client.post("/ues/1/bearers", json={})

        assert_422(response)


class TestDeleteBearer:
    def test_delete_bearer_success_removes_from_state(self, test_client):
        attach_ue(test_client, ue_id=1)
        add_bearer(test_client, ue_id=1, bearer_id=2)

        response = test_client.delete("/ues/1/bearers/2")

        assert response.status_code == 200
        assert response.json() == {
            "status": "bearer_deleted",
            "ue_id": 1,
            "bearer_id": 2,
        }
        assert "2" not in test_client.get("/ues/1").json()["bearers"]

    def test_delete_bearer_missing_ue_returns_400(self, test_client):
        response = test_client.delete("/ues/99/bearers/1")

        assert_400(response, "UE not found")

    def test_delete_bearer_not_found_returns_400(self, test_client):
        attach_ue(test_client, ue_id=1)

        response = test_client.delete("/ues/1/bearers/5")

        assert_400(response, "Bearer not found")

    def test_delete_default_bearer_9_returns_400(self, test_client):
        attach_ue(test_client, ue_id=1)

        response = test_client.delete("/ues/1/bearers/9")

        assert_400(response, "Cannot remove default bearer")
        assert "9" in test_client.get("/ues/1").json()["bearers"]

    def test_delete_bearer_with_active_traffic_stops_traffic(self, test_client):
        attach_ue(test_client, ue_id=1)
        add_bearer(test_client, ue_id=1, bearer_id=1)
        start_traffic(test_client, ue_id=1, bearer_id=1, Mbps=1.0)

        response = test_client.delete("/ues/1/bearers/1")

        assert response.status_code == 200
        stats = test_client.get("/ues/1/bearers/1/traffic").json()
        assert stats["tx_bps"] == 0
        assert stats["rx_bps"] == 0


# ---------------------------------------------------------------------------
# Traffic management
# ---------------------------------------------------------------------------

class TestStartTraffic:
    @pytest.mark.parametrize(
        ("throughput_field", "throughput_value", "expected_bps"),
        [
            ("Mbps", 1.0, 1_000_000),
            ("kbps", 500.0, 500_000),
            ("bps", 8000, 8000),
        ],
    )
    def test_start_traffic_throughput_variants(
        self, test_client, throughput_field, throughput_value, expected_bps
    ):
        attach_ue(test_client, ue_id=1)
        add_bearer(test_client, ue_id=1, bearer_id=1)

        response = start_traffic(
            test_client,
            ue_id=1,
            bearer_id=1,
            protocol="tcp",
            **{throughput_field: throughput_value},
        )

        assert response.status_code == 200
        assert response.json() == {
            "status": "traffic_started",
            "ue_id": 1,
            "bearer_id": 1,
            "target_bps": expected_bps,
        }

        bearer = test_client.get("/ues/1").json()["bearers"]["1"]
        assert bearer["active"] is True
        assert bearer["protocol"] == "tcp"
        assert bearer["target_bps"] == expected_bps

    @pytest.mark.parametrize("protocol", ["tcp", "udp"])
    def test_start_traffic_accepts_valid_protocols(self, test_client, protocol):
        attach_ue(test_client, ue_id=1)

        response = start_traffic(
            test_client, ue_id=1, bearer_id=9, protocol=protocol, Mbps=0.5
        )

        assert response.status_code == 200
        assert test_client.get("/ues/1").json()["bearers"]["9"]["protocol"] == protocol

    def test_start_traffic_on_default_bearer_9(self, test_client):
        attach_ue(test_client, ue_id=1)

        response = start_traffic(test_client, ue_id=1, bearer_id=9, Mbps=2.0)

        assert response.status_code == 200
        assert response.json()["bearer_id"] == 9

    def test_start_traffic_missing_ue_returns_400(self, test_client):
        response = start_traffic(test_client, ue_id=99, bearer_id=1, Mbps=1.0)

        assert_400(response, "UE not found")

    def test_start_traffic_missing_bearer_returns_400(self, test_client):
        attach_ue(test_client, ue_id=1)

        response = start_traffic(test_client, ue_id=1, bearer_id=5, Mbps=1.0)

        assert_400(response, "Bearer not found")

    def test_start_traffic_already_running_returns_400(self, test_client):
        attach_ue(test_client, ue_id=1)
        start_traffic(test_client, ue_id=1, bearer_id=9, Mbps=1.0)

        response = start_traffic(test_client, ue_id=1, bearer_id=9, Mbps=2.0)

        assert_400(response, "Traffic already running")

    def test_start_traffic_no_throughput_field_returns_422(self, test_client):
        attach_ue(test_client, ue_id=1)

        response = test_client.post(
            "/ues/1/bearers/9/traffic",
            json={"protocol": "tcp"},
        )

        assert_422(response)

    def test_start_traffic_multiple_throughput_fields_returns_422(self, test_client):
        attach_ue(test_client, ue_id=1)

        response = test_client.post(
            "/ues/1/bearers/9/traffic",
            json={"protocol": "tcp", "Mbps": 1.0, "kbps": 500.0},
        )

        assert_422(response)

    @pytest.mark.parametrize("protocol", ["http", "TCP", ""])
    def test_start_traffic_invalid_protocol_returns_422(self, test_client, protocol):
        attach_ue(test_client, ue_id=1)

        response = start_traffic(test_client, ue_id=1, bearer_id=9, protocol=protocol, Mbps=1.0)

        assert_422(response)

    def test_start_traffic_zero_throughput_returns_400(self, test_client):
        attach_ue(test_client, ue_id=1)

        response = start_traffic(test_client, ue_id=1, bearer_id=9, Mbps=0.0)

        assert_400(response, "Bearer not configured for traffic")


class TestStopTraffic:
    def test_stop_traffic_success_deactivates_bearer(self, test_client):
        attach_ue(test_client, ue_id=1)
        start_traffic(test_client, ue_id=1, bearer_id=9, Mbps=1.0)

        response = test_client.delete("/ues/1/bearers/9/traffic")

        assert response.status_code == 200
        assert response.json() == {
            "status": "traffic_stopped",
            "ue_id": 1,
            "bearer_id": 9,
        }
        assert test_client.get("/ues/1").json()["bearers"]["9"]["active"] is False

    def test_stop_traffic_never_started_returns_200(self, test_client):
        attach_ue(test_client, ue_id=1)
        add_bearer(test_client, ue_id=1, bearer_id=1)

        response = test_client.delete("/ues/1/bearers/1/traffic")

        assert response.status_code == 200
        assert response.json()["status"] == "traffic_stopped"

    def test_stop_traffic_missing_ue_returns_400(self, test_client):
        response = test_client.delete("/ues/99/bearers/1/traffic")

        assert_400(response, "UE not found")

    def test_stop_traffic_missing_bearer_returns_400(self, test_client):
        attach_ue(test_client, ue_id=1)

        response = test_client.delete("/ues/1/bearers/5/traffic")

        assert_400(response, "Bearer not found")


class TestGetTrafficStats:
    def test_get_traffic_stats_before_start_returns_zeros(self, test_client):
        attach_ue(test_client, ue_id=1)

        response = test_client.get("/ues/1/bearers/9/traffic")

        assert response.status_code == 200
        assert response.json() == {
            "ue_id": 1,
            "bearer_id": 9,
            "protocol": None,
            "target_bps": None,
            "tx_bps": 0,
            "rx_bps": 0,
            "duration": 0,
        }

    def test_get_traffic_stats_unknown_bearer_returns_200_with_zeros(self, test_client):
        attach_ue(test_client, ue_id=1)

        response = test_client.get("/ues/1/bearers/99/traffic")

        assert response.status_code == 200
        body = response.json()
        assert body["ue_id"] == 1
        assert body["bearer_id"] == 99
        assert body["tx_bps"] == 0
        assert body["rx_bps"] == 0
        assert body["duration"] == 0

    def test_get_traffic_stats_missing_ue_returns_400(self, test_client):
        response = test_client.get("/ues/99/bearers/1/traffic")

        assert_400(response, "UE not found")

    def test_get_traffic_stats_after_running_shows_nonzero_counters(self, test_client):
        attach_ue(test_client, ue_id=1)
        start_traffic(test_client, ue_id=1, bearer_id=9, Mbps=1.0)

        time.sleep(1.2)

        response = test_client.get("/ues/1/bearers/9/traffic")

        assert response.status_code == 200
        body = response.json()
        assert body["protocol"] == "tcp"
        assert body["target_bps"] == 1_000_000
        assert body["tx_bps"] > 0
        assert body["rx_bps"] > 0
        assert body["duration"] > 0


# ---------------------------------------------------------------------------
# Aggregated stats
# ---------------------------------------------------------------------------

class TestAggregatedStats:
    def test_stats_empty_system_returns_zeros(self, test_client):
        response = test_client.get("/ues/stats")

        assert response.status_code == 200
        assert response.json() == {
            "scope": "all",
            "ue_count": 0,
            "bearer_count": 0,
            "total_tx_bps": 0,
            "total_rx_bps": 0,
            "details": None,
        }

    def test_stats_with_ue_no_traffic_counts_bearers_with_zero_bps(self, test_client):
        attach_ue(test_client, ue_id=1)
        add_bearer(test_client, ue_id=1, bearer_id=1)

        response = test_client.get("/ues/stats")

        assert response.status_code == 200
        body = response.json()
        assert body["scope"] == "all"
        assert body["ue_count"] == 1
        assert body["bearer_count"] == 0
        assert body["total_tx_bps"] == 0
        assert body["total_rx_bps"] == 0
        assert body["details"] is None

    def test_stats_include_details_false_omits_details(self, test_client):
        attach_ue(test_client, ue_id=1)

        response = test_client.get("/ues/stats", params={"include_details": False})

        assert response.status_code == 200
        assert response.json()["details"] is None

    def test_stats_include_details_true_returns_nested_map(self, test_client):
        attach_ue(test_client, ue_id=1)
        start_traffic(test_client, ue_id=1, bearer_id=9, Mbps=1.0)
        time.sleep(1.2)

        response = test_client.get("/ues/stats", params={"include_details": True})

        assert response.status_code == 200
        body = response.json()
        assert body["details"] is not None
        assert "1" in body["details"]
        assert "9" in body["details"]["1"]
        assert body["details"]["1"]["9"] > 0

    def test_stats_filtered_by_ue_id(self, test_client):
        attach_ue(test_client, ue_id=1)
        attach_ue(test_client, ue_id=2)

        response = test_client.get("/ues/stats", params={"ue_id": 1})

        assert response.status_code == 200
        body = response.json()
        assert body["scope"] == "ue:1"
        assert body["ue_count"] == 1

    def test_stats_filtered_by_missing_ue_returns_400(self, test_client):
        response = test_client.get("/ues/stats", params={"ue_id": 999})

        assert_400(response, "UE not found")

    def test_stats_invalid_ue_id_query_returns_422(self, test_client):
        response = test_client.get("/ues/stats", params={"ue_id": "invalid"})

        assert_422(response)

    def test_stats_invalid_include_details_query_returns_422(self, test_client):
        response = test_client.get("/ues/stats", params={"include_details": "not-a-bool"})

        assert_422(response)


# ---------------------------------------------------------------------------
# System reset
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_clears_all_ues(self, test_client):
        attach_ue(test_client, ue_id=1)
        attach_ue(test_client, ue_id=2)
        start_traffic(test_client, ue_id=1, bearer_id=9, Mbps=1.0)

        response = test_client.post("/reset")

        assert response.status_code == 200
        assert response.json() == {"status": "reset"}
        assert test_client.get("/ues").json() == {"ues": []}

    def test_reset_empty_system_returns_200(self, test_client):
        response = test_client.post("/reset")

        assert response.status_code == 200
        assert response.json() == {"status": "reset"}


# ---------------------------------------------------------------------------
# End-to-end lifecycle
# ---------------------------------------------------------------------------

class TestEndToEndLifecycle:
    def test_full_ue_bearer_traffic_lifecycle(self, test_client):
        attach_resp = attach_ue(test_client, ue_id=1)
        assert attach_resp.status_code == 200

        assert test_client.get("/ues").json() == {"ues": [1]}

        add_resp = add_bearer(test_client, ue_id=1, bearer_id=1)
        assert add_resp.status_code == 200

        start_resp = start_traffic(test_client, ue_id=1, bearer_id=1, protocol="udp", kbps=100.0)
        assert start_resp.status_code == 200
        assert start_resp.json()["target_bps"] == 100_000

        time.sleep(1.2)
        stats_resp = test_client.get("/ues/1/bearers/1/traffic")
        assert stats_resp.status_code == 200
        assert stats_resp.json()["protocol"] == "udp"
        assert stats_resp.json()["tx_bps"] > 0

        stop_resp = test_client.delete("/ues/1/bearers/1/traffic")
        assert stop_resp.status_code == 200

        del_bearer_resp = test_client.delete("/ues/1/bearers/1")
        assert del_bearer_resp.status_code == 200

        detach_resp = test_client.delete("/ues/1")
        assert detach_resp.status_code == 200
        assert test_client.get("/ues").json() == {"ues": []}
