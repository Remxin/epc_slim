import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from .models import (
    AddBearerRequest,
    AggregatedStatsResponse,
    AttachResponse,
    AttachUERequest,
    BearerAddResponse,
    BearerDeleteResponse,
    DetachResponse,
    StartTrafficRequest,
    StatusResponse,
    TrafficStartResponse,
    TrafficStatsResponse,
    TrafficStopResponse,
    UEDisplayResponse,
    UEListResponse,
)
from .db import EPCRepository
from .traffic import get_traffic_manager

router = APIRouter()

_repo_singleton: EPCRepository | None = None
TrafficUnit = Literal["bps", "kbps", "Mbps", "mbps"]


def _unit_divisor(unit: TrafficUnit) -> int:
    return 1_000_000 if unit in {"Mbps", "mbps"} else {"bps": 1, "kbps": 1_000}[unit]


def _convert_rate(value: int | None, unit: TrafficUnit) -> int | None:
    if value is None:
        return None
    return int(value / _unit_divisor(unit))


def _throughput_bps(stats: "ThroughputStats", is_running: bool) -> tuple[int, int, float]:
    end_ts = time.time() if (stats.start_ts and is_running) else stats.last_update_ts
    duration = (end_ts - stats.start_ts) if (stats.start_ts and end_ts is not None) else 0
    tx_bps = int(stats.bytes_tx * 8 / duration) if duration > 0 else 0
    rx_bps = int(stats.bytes_rx * 8 / duration) if duration > 0 else 0
    return tx_bps, rx_bps, duration


def _require_existing_bearer(state: "UEState", bearer_id: int) -> None:
    if bearer_id < 1 or bearer_id > 9 or bearer_id not in state.bearers:
        raise HTTPException(status_code=400, detail="Bearer not found")


def get_repo() -> EPCRepository:
    global _repo_singleton
    if _repo_singleton is None:
        _repo_singleton = EPCRepository()
    return _repo_singleton


@router.get("/ues/stats", response_model=AggregatedStatsResponse)
def get_ues_stats(
    repo: Annotated[EPCRepository, Depends(get_repo)],
    ue_id: int | None = None,
    include_details: bool = False,
    unit: TrafficUnit = Query(default="bps"),
):
    if ue_id is not None and not repo.ue_exists(ue_id):
        raise HTTPException(status_code=400, detail="UE not found")
    ues = [ue_id] if ue_id is not None else list(repo.list_ues())
    total_tx = 0
    total_rx = 0
    bearer_count = 0
    details: dict[str, dict[str, int]] = {}
    tm = get_traffic_manager(repo)
    for uid in ues:
        try:
            state = repo.get_ue(uid)
        except ValueError:
            if ue_id is not None:
                raise HTTPException(status_code=400, detail="UE not found")
            continue
        for b_id, stats in state.stats.items():
            tx_bps, rx_bps, _duration = _throughput_bps(stats, tm.is_running(uid, b_id))
            tx = _convert_rate(tx_bps, unit)
            rx = _convert_rate(rx_bps, unit)
            total_tx += tx
            total_rx += rx
            bearer_count += 1
            if include_details:
                details.setdefault(str(uid), {})[str(b_id)] = tx
    scope = f"ue:{ue_id}" if ue_id is not None else "all"
    return AggregatedStatsResponse(
        scope=scope,
        ue_count=len(ues),
        bearer_count=bearer_count,
        total_tx_bps=total_tx,
        total_rx_bps=total_rx,
        details=details if include_details else None,
    )


@router.get("/ues", response_model=UEListResponse)
def list_ues(repo: Annotated[EPCRepository, Depends(get_repo)]):
    return UEListResponse(ues=list(repo.list_ues()))


@router.post("/ues", response_model=AttachResponse)
def attach_ue(body: AttachUERequest, repo: Annotated[EPCRepository, Depends(get_repo)]):
    try:
        repo.attach_ue(body.ue_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return AttachResponse(status="attached", ue_id=body.ue_id)


@router.get("/ues/{ue_id}", response_model=UEDisplayResponse)
def get_ue(ue_id: int, repo: Annotated[EPCRepository, Depends(get_repo)]):
    try:
        state = repo.get_ue(ue_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return UEDisplayResponse(**state.model_dump())


@router.delete("/ues/{ue_id}/traffic", response_model=StatusResponse)
def stop_all_traffic_for_ue(
    ue_id: int,
    repo: Annotated[EPCRepository, Depends(get_repo)],
):
    try:
        state = repo.get_ue(ue_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    tm = get_traffic_manager(repo)
    stopped = 0
    for bearer_id, bearer in state.bearers.items():
        if tm.is_running(ue_id, bearer_id):
            tm.stop(ue_id, bearer_id)
            bearer.active = False
            repo.update_bearer(ue_id, bearer)
            stopped += 1
    return StatusResponse(status=f"stopped {stopped} bearer(s)")


@router.delete("/ues/{ue_id}", response_model=DetachResponse)
def detach_ue(ue_id: int, repo: Annotated[EPCRepository, Depends(get_repo)]):
    try:
        repo.detach_ue(ue_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return DetachResponse(status="detached", ue_id=ue_id)


# --- Bearers ---

@router.post("/ues/{ue_id}/bearers", response_model=BearerAddResponse)
def add_bearer(
    ue_id: int,
    body: AddBearerRequest,
    repo: Annotated[EPCRepository, Depends(get_repo)],
):
    try:
        repo.add_bearer(ue_id, body.bearer_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return BearerAddResponse(status="bearer_added", ue_id=ue_id, bearer_id=body.bearer_id)


@router.delete("/ues/{ue_id}/bearers/{bearer_id}", response_model=BearerDeleteResponse)
def delete_bearer(
    ue_id: int,
    bearer_id: int,
    repo: Annotated[EPCRepository, Depends(get_repo)],
):
    try:
        state = repo.get_ue(ue_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if bearer_id not in state.bearers:
        raise HTTPException(status_code=400, detail="Bearer not found")
    tm = get_traffic_manager(repo)
    if tm.is_running(ue_id, bearer_id):
        tm.stop(ue_id, bearer_id)
    try:
        repo.delete_bearer(ue_id, bearer_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return BearerDeleteResponse(status="bearer_deleted", ue_id=ue_id, bearer_id=bearer_id)


# --- Traffic (start/stop/stats) ---

@router.post("/ues/{ue_id}/bearers/{bearer_id}/traffic", response_model=TrafficStartResponse)
def start_traffic(
    ue_id: int,
    bearer_id: int,
    body: StartTrafficRequest,
    repo: Annotated[EPCRepository, Depends(get_repo)],
):
    try:
        target_bps = body.target_bps()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        state = repo.get_ue(ue_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    bearer = state.bearers.get(bearer_id)
    if not bearer:
        raise HTTPException(status_code=400, detail="Bearer not found")
    active_sum = sum(
        b.target_bps
        for b_id, b in state.bearers.items()
        if b.active and b.target_bps and b_id != bearer_id
    )
    if active_sum + target_bps > 100_000_000:
        raise HTTPException(
            status_code=400,
            detail=(
                f"UE aggregate throughput would exceed 100 Mbps "
                f"(active: {active_sum // 1000} kbps + requested: {target_bps // 1000} kbps)"
            ),
        )
    bearer.protocol = body.protocol.lower()
    bearer.target_bps = target_bps
    bearer.active = True
    repo.update_bearer(ue_id, bearer)
    from .models import ThroughputStats

    if bearer_id not in state.stats:
        initial_stats = ThroughputStats(
            bearer_id=bearer_id,
            ue_id=ue_id,
            start_ts=time.time(),
            last_update_ts=time.time(),
            protocol=bearer.protocol,
            target_bps=target_bps,
        )
        repo.update_stats(ue_id, initial_stats)
    tm = get_traffic_manager(repo)
    try:
        tm.start(ue_id, bearer)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return TrafficStartResponse(
        status="traffic_started",
        ue_id=ue_id,
        bearer_id=bearer_id,
        target_bps=target_bps,
    )


@router.delete("/ues/{ue_id}/bearers/{bearer_id}/traffic", response_model=TrafficStopResponse)
def stop_traffic(
    ue_id: int,
    bearer_id: int,
    repo: Annotated[EPCRepository, Depends(get_repo)],
):
    try:
        state = repo.get_ue(ue_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    bearer = state.bearers.get(bearer_id)
    if not bearer:
        raise HTTPException(status_code=400, detail="Bearer not found")
    tm = get_traffic_manager(repo)
    tm.stop(ue_id, bearer_id)
    bearer.active = False
    bearer.protocol = None
    bearer.target_bps = None
    state.stats.pop(bearer_id, None)
    repo.save_ue(state)
    return TrafficStopResponse(status="traffic_stopped", ue_id=ue_id, bearer_id=bearer_id)


@router.get("/ues/{ue_id}/bearers/{bearer_id}/traffic", response_model=TrafficStatsResponse)
def get_traffic_stats(
    ue_id: int,
    bearer_id: int,
    repo: Annotated[EPCRepository, Depends(get_repo)],
    unit: TrafficUnit = Query(default="bps"),
):
    try:
        state = repo.get_ue(ue_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _require_existing_bearer(state, bearer_id)
    stats = state.stats.get(bearer_id)
    if not stats:
        return TrafficStatsResponse(
            ue_id=ue_id,
            bearer_id=bearer_id,
            protocol=None,
            target_bps=None,
            tx_bps=0,
            rx_bps=0,
            duration=0,
        )
    tm = get_traffic_manager(repo)
    tx_bps, rx_bps, duration = _throughput_bps(stats, tm.is_running(ue_id, bearer_id))
    return TrafficStatsResponse(
        ue_id=ue_id,
        bearer_id=bearer_id,
        protocol=stats.protocol,
        target_bps=_convert_rate(stats.target_bps, unit),
        tx_bps=_convert_rate(tx_bps, unit),
        rx_bps=_convert_rate(rx_bps, unit),
        duration=duration,
    )


# --- Reset ---

@router.post("/reset", response_model=StatusResponse)
def reset_all(repo: Annotated[EPCRepository, Depends(get_repo)]):
    get_traffic_manager(repo).stop_all()
    repo.reset_all()
    return StatusResponse(status="reset")
