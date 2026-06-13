"""Layer 1: Models - validation and normalization.

Scope:
- BearerConfig: bearer_id range, protocol pattern, default values
- StartTrafficRequest: exactly one throughput field, target_bps conversion
- UEState: ue_id range, default dict initialization, cross-field validation
"""

import pytest
from pydantic import ValidationError

from epc.models import (
    AddBearerRequest,
    AttachUERequest,
    BearerConfig,
    StartTrafficRequest,
    ThroughputStats,
    UEState,
)


# --- BearerConfig ---


class TestBearerConfigBearerId:
    @pytest.mark.parametrize("bearer_id", [1, 5, 9])
    def test_valid_bearer_id(self, bearer_id):
        cfg = BearerConfig(bearer_id=bearer_id)
        assert cfg.bearer_id == bearer_id

    @pytest.mark.parametrize("bearer_id", [0, -1, 10, 100])
    def test_invalid_bearer_id_raises(self, bearer_id):
        with pytest.raises(ValidationError):
            BearerConfig(bearer_id=bearer_id)


class TestBearerConfigProtocol:
    @pytest.mark.parametrize("protocol", ["tcp", "udp"])
    def test_valid_protocol(self, protocol):
        cfg = BearerConfig(bearer_id=1, protocol=protocol)
        assert cfg.protocol == protocol

    @pytest.mark.parametrize("protocol", ["ftp", "http", "TCP", "UDP", ""])
    def test_invalid_protocol_raises(self, protocol):
        with pytest.raises(ValidationError):
            BearerConfig(bearer_id=1, protocol=protocol)

    def test_protocol_none_is_allowed(self):
        cfg = BearerConfig(bearer_id=1, protocol=None)
        assert cfg.protocol is None


class TestBearerConfigDefaults:
    def test_default_protocol_is_none(self):
        cfg = BearerConfig(bearer_id=1)
        assert cfg.protocol is None

    def test_default_active_is_false(self):
        cfg = BearerConfig(bearer_id=1)
        assert cfg.active is False

    def test_default_target_bps_is_none(self):
        cfg = BearerConfig(bearer_id=1)
        assert cfg.target_bps is None


# --- ThroughputStats ---


class TestThroughputStatsDefaults:
    def test_bytes_tx_default_is_zero(self):
        stats = ThroughputStats(bearer_id=1, ue_id=1)
        assert stats.bytes_tx == 0

    def test_bytes_rx_default_is_zero(self):
        stats = ThroughputStats(bearer_id=1, ue_id=1)
        assert stats.bytes_rx == 0

    def test_start_ts_default_is_none(self):
        stats = ThroughputStats(bearer_id=1, ue_id=1)
        assert stats.start_ts is None

    def test_last_update_ts_default_is_none(self):
        stats = ThroughputStats(bearer_id=1, ue_id=1)
        assert stats.last_update_ts is None

    def test_protocol_default_is_none(self):
        stats = ThroughputStats(bearer_id=1, ue_id=1)
        assert stats.protocol is None

    def test_target_bps_default_is_none(self):
        stats = ThroughputStats(bearer_id=1, ue_id=1)
        assert stats.target_bps is None

    def test_explicit_values_stored(self):
        stats = ThroughputStats(
            bearer_id=3,
            ue_id=7,
            bytes_tx=1000,
            bytes_rx=2000,
            start_ts=1.0,
            last_update_ts=2.5,
            protocol="tcp",
            target_bps=500_000,
        )
        assert stats.bearer_id == 3
        assert stats.ue_id == 7
        assert stats.bytes_tx == 1000
        assert stats.bytes_rx == 2000
        assert stats.start_ts == 1.0
        assert stats.last_update_ts == 2.5
        assert stats.protocol == "tcp"
        assert stats.target_bps == 500_000


# --- StartTrafficRequest ---


class TestStartTrafficRequestValidation:
    @pytest.mark.parametrize("kwargs", [
        {"protocol": "tcp", "Mbps": 1.0},
        {"protocol": "udp", "kbps": 500.0},
        {"protocol": "tcp", "bps": 1234},
    ])
    def test_exactly_one_throughput_valid(self, kwargs):
        req = StartTrafficRequest(**kwargs)
        assert req is not None

    def test_no_throughput_field_raises(self):
        with pytest.raises(ValidationError):
            StartTrafficRequest(protocol="tcp")

    @pytest.mark.parametrize("kwargs", [
        {"protocol": "tcp", "Mbps": 1.0, "kbps": 500.0},
        {"protocol": "tcp", "Mbps": 1.0, "bps": 100},
        {"protocol": "tcp", "kbps": 500.0, "bps": 100},
        {"protocol": "tcp", "Mbps": 1.0, "kbps": 500.0, "bps": 100},
    ])
    def test_multiple_throughput_fields_raises(self, kwargs):
        with pytest.raises(ValidationError):
            StartTrafficRequest(**kwargs)

    @pytest.mark.parametrize("protocol", ["ftp", "http", "TCP", "UDP", ""])
    def test_invalid_protocol_raises(self, protocol):
        with pytest.raises(ValidationError):
            StartTrafficRequest(protocol=protocol, Mbps=1.0)


class TestStartTrafficRequestTargetBps:
    @pytest.mark.parametrize("mbps,expected", [
        (1.0, 1_000_000),
        (0.5, 500_000),
        (10.0, 10_000_000),
        (0.001, 1_000),
    ])
    def test_mbps_conversion(self, mbps, expected):
        req = StartTrafficRequest(protocol="tcp", Mbps=mbps)
        assert req.target_bps() == expected

    @pytest.mark.parametrize("kbps,expected", [
        (1.0, 1_000),
        (500.0, 500_000),
        (0.5, 500),
    ])
    def test_kbps_conversion(self, kbps, expected):
        req = StartTrafficRequest(protocol="tcp", kbps=kbps)
        assert req.target_bps() == expected

    @pytest.mark.parametrize("bps,expected", [
        (1000, 1000),
        (9_999_999, 9_999_999),
    ])
    def test_bps_passthrough(self, bps, expected):
        req = StartTrafficRequest(protocol="tcp", bps=bps)
        assert req.target_bps() == expected

    def test_target_bps_raises_for_zero(self):
        req = StartTrafficRequest(protocol="tcp", bps=0.0)
        with pytest.raises(ValueError, match="greater than 0"):
            req.target_bps()


# --- UEState ---


class TestUEStateBoundaries:
    @pytest.mark.parametrize("ue_id", [1, 50, 100])
    def test_valid_ue_id(self, ue_id):
        ue = UEState(ue_id=ue_id)
        assert ue.ue_id == ue_id

    @pytest.mark.parametrize("ue_id", [0, -1, 101, 200])
    def test_invalid_ue_id_raises(self, ue_id):
        with pytest.raises(ValidationError):
            UEState(ue_id=ue_id)


class TestUEStateDefaults:
    def test_bearers_default_is_empty_dict(self):
        ue = UEState(ue_id=1)
        assert ue.bearers == {}

    def test_stats_default_is_empty_dict(self):
        ue = UEState(ue_id=1)
        assert ue.stats == {}

    def test_bearers_none_initializes_to_empty_dict(self):
        ue = UEState(ue_id=1, bearers=None)
        assert ue.bearers == {}

    def test_stats_none_initializes_to_empty_dict(self):
        ue = UEState(ue_id=1, stats=None)
        assert ue.stats == {}


# --- AttachUERequest ---


class TestAttachUERequest:
    @pytest.mark.parametrize("ue_id", [1, 50, 100])
    def test_valid_ue_id(self, ue_id):
        req = AttachUERequest(ue_id=ue_id)
        assert req.ue_id == ue_id

    @pytest.mark.parametrize("ue_id", [0, 101])
    def test_invalid_ue_id_raises(self, ue_id):
        with pytest.raises(ValidationError):
            AttachUERequest(ue_id=ue_id)


# --- AddBearerRequest ---


class TestAddBearerRequest:
    @pytest.mark.parametrize("bearer_id", [1, 5, 9])
    def test_valid_bearer_id(self, bearer_id):
        req = AddBearerRequest(bearer_id=bearer_id)
        assert req.bearer_id == bearer_id

    @pytest.mark.parametrize("bearer_id", [0, 10])
    def test_invalid_bearer_id_raises(self, bearer_id):
        with pytest.raises(ValidationError):
            AddBearerRequest(bearer_id=bearer_id)
