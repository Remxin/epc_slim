"""Layer 2: Repository - SQLite state and invariants.

Scope:
- UE lifecycle: attach/get/list/detach flows
- Bearer add/remove behavior
- Invariants: default bearer 9, cannot delete bearer 9
- Persisted updates: update_bearer, update_stats, save_ue
- Reset behavior: reset_all
"""

import pytest

from epc.db import EPCRepository
from epc.models import BearerConfig, ThroughputStats, UEState


def test_new_repository_starts_empty(repo):
    assert list(repo.list_ues()) == []
    assert repo.ue_exists(1) is False


def test_attach_ue_creates_state_with_default_bearer(repo):
    repo.attach_ue(1)

    state = repo.get_ue(1)

    assert state.ue_id == 1
    assert state.bearers == {9: BearerConfig(bearer_id=9)}
    assert state.stats == {}
    assert repo.ue_exists(1) is True
    assert list(repo.list_ues()) == [1]


def test_list_ues_returns_ids_in_ascending_order(repo):
    repo.attach_ue(3)
    repo.attach_ue(1)
    repo.attach_ue(2)

    assert list(repo.list_ues()) == [1, 2, 3]


def test_attach_existing_ue_raises_value_error(repo_with_ue):
    with pytest.raises(ValueError, match="UE already attached"):
        repo_with_ue.attach_ue(1)


@pytest.mark.parametrize("operation", ["get", "detach"])
def test_missing_ue_operations_raise_value_error(repo, operation):
    with pytest.raises(ValueError, match="UE not found"):
        if operation == "get":
            repo.get_ue(99)
        else:
            repo.detach_ue(99)


def test_detach_ue_removes_state(repo_with_ue):
    repo_with_ue.detach_ue(1)

    assert repo_with_ue.ue_exists(1) is False
    assert list(repo_with_ue.list_ues()) == []
    with pytest.raises(ValueError, match="UE not found"):
        repo_with_ue.get_ue(1)


def test_detach_one_ue_leaves_other_ues_untouched(repo):
    repo.attach_ue(1)
    repo.attach_ue(2)
    repo.add_bearer(2, 3)

    repo.detach_ue(1)

    assert list(repo.list_ues()) == [2]
    assert set(repo.get_ue(2).bearers) == {3, 9}


def test_add_bearer_persists_new_bearer(repo_with_ue):
    repo_with_ue.add_bearer(1, 5)

    state = repo_with_ue.get_ue(1)

    assert set(state.bearers) == {5, 9}
    assert state.bearers[5] == BearerConfig(bearer_id=5)


def test_add_bearer_does_not_create_stats(repo_with_ue):
    repo_with_ue.add_bearer(1, 5)

    assert repo_with_ue.get_ue(1).stats == {}


def test_add_existing_bearer_raises_value_error(repo_with_ue):
    with pytest.raises(ValueError, match="Bearer already exists"):
        repo_with_ue.add_bearer(1, 9)


def test_add_bearer_to_missing_ue_raises_value_error(repo):
    with pytest.raises(ValueError, match="UE not found"):
        repo.add_bearer(42, 1)


def test_update_bearer_persists_configuration(repo_with_ue):
    bearer = BearerConfig(
        bearer_id=9,
        protocol="tcp",
        target_bps=1_000_000,
        active=True,
    )

    repo_with_ue.update_bearer(1, bearer)

    assert repo_with_ue.get_ue(1).bearers[9] == bearer


def test_update_bearer_preserves_existing_stats(repo_with_ue):
    stats = ThroughputStats(bearer_id=9, ue_id=1, bytes_tx=100, bytes_rx=200)
    bearer = BearerConfig(
        bearer_id=9,
        protocol="udp",
        target_bps=250_000,
        active=True,
    )
    repo_with_ue.update_stats(1, stats)

    repo_with_ue.update_bearer(1, bearer)
    state = repo_with_ue.get_ue(1)

    assert state.bearers[9] == bearer
    assert state.stats[9] == stats


def test_update_bearer_requires_existing_bearer(repo_with_ue):
    with pytest.raises(ValueError, match="Bearer not found"):
        repo_with_ue.update_bearer(1, BearerConfig(bearer_id=3))

    assert set(repo_with_ue.get_ue(1).bearers) == {9}


def test_update_bearer_on_missing_ue_raises_value_error(repo):
    with pytest.raises(ValueError, match="UE not found"):
        repo.update_bearer(1, BearerConfig(bearer_id=9))


def test_update_stats_persists_throughput_stats(repo_with_ue):
    stats = ThroughputStats(
        bearer_id=9,
        ue_id=1,
        bytes_tx=1200,
        bytes_rx=2400,
        start_ts=10.0,
        last_update_ts=16.0,
        protocol="udp",
        target_bps=500_000,
    )

    repo_with_ue.update_stats(1, stats)

    assert repo_with_ue.get_ue(1).stats[9] == stats


def test_update_stats_replaces_existing_stats(repo_with_ue):
    initial_stats = ThroughputStats(bearer_id=9, ue_id=1, bytes_tx=100)
    updated_stats = ThroughputStats(
        bearer_id=9,
        ue_id=1,
        bytes_tx=300,
        bytes_rx=600,
        start_ts=1.0,
        last_update_ts=4.0,
        protocol="tcp",
        target_bps=1_000,
    )
    repo_with_ue.update_stats(1, initial_stats)

    repo_with_ue.update_stats(1, updated_stats)

    assert repo_with_ue.get_ue(1).stats[9] == updated_stats


def test_update_stats_requires_existing_bearer(repo_with_ue):
    with pytest.raises(ValueError, match="Bearer not found"):
        repo_with_ue.update_stats(
            1,
            ThroughputStats(
                bearer_id=3,
                ue_id=1,
                bytes_tx=1200,
            ),
        )

    assert repo_with_ue.get_ue(1).stats == {}


def test_update_stats_rejects_mismatched_ue_id(repo_with_ue):
    with pytest.raises(ValueError, match="Stats UE mismatch"):
        repo_with_ue.update_stats(
            1,
            ThroughputStats(
                bearer_id=9,
                ue_id=2,
                bytes_tx=1200,
            ),
        )

    assert repo_with_ue.get_ue(1).stats == {}


def test_update_stats_on_missing_ue_raises_value_error(repo):
    with pytest.raises(ValueError, match="UE not found"):
        repo.update_stats(1, ThroughputStats(bearer_id=9, ue_id=1))


def test_save_ue_replaces_persisted_state(repo):
    state = UEState(
        ue_id=7,
        bearers={
            9: BearerConfig(bearer_id=9),
            2: BearerConfig(
                bearer_id=2,
                protocol="tcp",
                target_bps=10_000,
                active=True,
            )
        },
        stats={
            2: ThroughputStats(
                bearer_id=2,
                ue_id=7,
                bytes_tx=100,
                bytes_rx=200,
            )
        },
    )

    repo.save_ue(state)

    assert repo.ue_exists(7) is True
    assert repo.get_ue(7) == state


def test_save_ue_replaces_existing_state(repo_with_ue):
    repo_with_ue.add_bearer(1, 2)
    repo_with_ue.update_stats(1, ThroughputStats(bearer_id=2, ue_id=1, bytes_tx=100))
    replacement = UEState(
        ue_id=1,
        bearers={9: BearerConfig(bearer_id=9, protocol="tcp")},
        stats={},
    )

    repo_with_ue.save_ue(replacement)

    assert repo_with_ue.get_ue(1) == replacement


def test_save_ue_rejects_state_without_default_bearer(repo):
    state = UEState(
        ue_id=7,
        bearers={2: BearerConfig(bearer_id=2)},
    )

    with pytest.raises(ValueError, match="Default bearer missing"):
        repo.save_ue(state)

    assert repo.ue_exists(7) is False


def test_save_ue_rejects_mismatched_bearer_key(repo):
    state = UEState(
        ue_id=7,
        bearers={
            9: BearerConfig(bearer_id=9),
            2: BearerConfig(bearer_id=3),
        },
    )

    with pytest.raises(ValueError, match="Bearer ID mismatch"):
        repo.save_ue(state)

    assert repo.ue_exists(7) is False


def test_save_ue_rejects_stats_for_missing_bearer(repo):
    state = UEState(
        ue_id=7,
        bearers={9: BearerConfig(bearer_id=9)},
        stats={2: ThroughputStats(bearer_id=2, ue_id=7)},
    )

    with pytest.raises(ValueError, match="Bearer not found"):
        repo.save_ue(state)

    assert repo.ue_exists(7) is False


def test_save_ue_rejects_stats_with_mismatched_key(repo):
    state = UEState(
        ue_id=7,
        bearers={
            9: BearerConfig(bearer_id=9),
            2: BearerConfig(bearer_id=2),
        },
        stats={2: ThroughputStats(bearer_id=3, ue_id=7)},
    )

    with pytest.raises(ValueError, match="Stats bearer ID mismatch"):
        repo.save_ue(state)

    assert repo.ue_exists(7) is False


def test_save_ue_rejects_stats_for_different_ue(repo):
    state = UEState(
        ue_id=7,
        bearers={
            9: BearerConfig(bearer_id=9),
            2: BearerConfig(bearer_id=2),
        },
        stats={2: ThroughputStats(bearer_id=2, ue_id=8)},
    )

    with pytest.raises(ValueError, match="Stats UE mismatch"):
        repo.save_ue(state)

    assert repo.ue_exists(7) is False


def test_get_ue_returns_detached_state_until_saved(repo_with_ue):
    state = repo_with_ue.get_ue(1)
    state.bearers[3] = BearerConfig(bearer_id=3)

    assert set(repo_with_ue.get_ue(1).bearers) == {9}


def test_repository_state_persists_between_instances(temp_db):
    first_repo = EPCRepository(db_path=str(temp_db))
    first_repo.attach_ue(4)
    first_repo.add_bearer(4, 1)

    second_repo = EPCRepository(db_path=str(temp_db))

    assert list(second_repo.list_ues()) == [4]
    assert set(second_repo.get_ue(4).bearers) == {1, 9}


def test_repository_instances_with_different_paths_are_isolated(tmp_path):
    first_repo = EPCRepository(db_path=str(tmp_path / "first.db"))
    second_repo = EPCRepository(db_path=str(tmp_path / "second.db"))

    first_repo.attach_ue(1)
    second_repo.attach_ue(2)

    assert list(first_repo.list_ues()) == [1]
    assert list(second_repo.list_ues()) == [2]


def test_delete_bearer_removes_bearer_and_related_stats(repo_with_ue):
    repo_with_ue.add_bearer(1, 3)
    repo_with_ue.update_stats(
        1,
        ThroughputStats(
            bearer_id=3,
            ue_id=1,
            bytes_tx=100,
            bytes_rx=200,
        ),
    )

    repo_with_ue.delete_bearer(1, 3)
    state = repo_with_ue.get_ue(1)

    assert 3 not in state.bearers
    assert 3 not in state.stats
    assert 9 in state.bearers


def test_delete_missing_bearer_raises_value_error(repo_with_ue):
    with pytest.raises(ValueError, match="Bearer not found"):
        repo_with_ue.delete_bearer(1, 2)


def test_delete_default_bearer_is_forbidden(repo_with_ue):
    with pytest.raises(ValueError, match="Cannot remove default bearer"):
        repo_with_ue.delete_bearer(1, 9)


def test_delete_default_bearer_from_missing_ue_raises_ue_not_found(repo):
    with pytest.raises(ValueError, match="UE not found"):
        repo.delete_bearer(1, 9)


def test_delete_bearer_from_missing_ue_raises_ue_not_found(repo):
    with pytest.raises(ValueError, match="UE not found"):
        repo.delete_bearer(1, 2)


def test_delete_bearer_preserves_unrelated_bearers_and_stats(repo_with_ue):
    repo_with_ue.add_bearer(1, 2)
    repo_with_ue.add_bearer(1, 3)
    repo_with_ue.update_stats(1, ThroughputStats(bearer_id=2, ue_id=1, bytes_tx=100))
    repo_with_ue.update_stats(1, ThroughputStats(bearer_id=3, ue_id=1, bytes_tx=200))

    repo_with_ue.delete_bearer(1, 2)
    state = repo_with_ue.get_ue(1)

    assert set(state.bearers) == {3, 9}
    assert set(state.stats) == {3}


def test_reset_all_is_idempotent_for_empty_repository(repo):
    repo.reset_all()

    assert list(repo.list_ues()) == []


def test_reset_all_removes_every_ue(repo):
    repo.attach_ue(1)
    repo.attach_ue(2)
    repo.add_bearer(1, 3)
    repo.update_stats(1, ThroughputStats(bearer_id=3, ue_id=1, bytes_tx=50))

    repo.reset_all()

    assert list(repo.list_ues()) == []
    assert repo.ue_exists(1) is False
    assert repo.ue_exists(2) is False
