import math

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_BEARER_BPS = 100_000_000  # 100 Mbps per bearer


class BearerConfig(BaseModel):
    bearer_id: int = Field(ge=1, le=9)
    protocol: str | None = Field(default=None, pattern="^(tcp|udp)$")
    target_bps: int | None = None  # bits per second
    active: bool = False


class ThroughputStats(BaseModel):
    bearer_id: int
    ue_id: int
    bytes_tx: int = 0  # uplink (MS->SS)
    bytes_rx: int = 0  # downlink (SS->MS)
    start_ts: float | None = None
    last_update_ts: float | None = None
    protocol: str | None = None
    target_bps: int | None = None


class UEState(BaseModel):
    ue_id: int = Field(ge=1, le=100)
    bearers: dict[int, BearerConfig] = {}
    stats: dict[int, ThroughputStats] = {}

    @model_validator(mode="before")
    def init_defaults(cls, values):
        if values.get("bearers") is None:
            values["bearers"] = {}
        if values.get("stats") is None:
            values["stats"] = {}
        return values


# Request body schemas (REST API)
class AttachUERequest(BaseModel):
    ue_id: int = Field(ge=1, le=100)


class AddBearerRequest(BaseModel):
    bearer_id: int = Field(ge=1, le=9)


class StartTrafficRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    protocol: str = Field(default="tcp", pattern="^(tcp|udp)$")
    direction: str = Field(default="DL", pattern="^DL$")
    Mbps: float | None = None
    kbps: float | None = None
    bps: float | None = None

    @model_validator(mode="after")
    def exactly_one_throughput(self):
        provided = [v for v in [self.Mbps, self.kbps, self.bps] if v is not None]
        if len(provided) != 1:
            raise ValueError("Provide exactly one throughput value (Mbps, kbps, or bps)")
        return self

    def target_bps(self) -> int:
        if self.Mbps is not None:
            raw = self.Mbps * 1_000_000
        elif self.kbps is not None:
            raw = self.kbps * 1_000
        else:
            raw = self.bps or 0
        if math.isnan(raw) or math.isinf(raw):
            raise ValueError("Throughput must be a finite number")
        result = int(raw)
        if result <= 0:
            raise ValueError("Throughput must be greater than 0")
        if result > MAX_BEARER_BPS:
            raise ValueError(
                f"Bearer throughput exceeds maximum of {MAX_BEARER_BPS // 1_000_000} Mbps"
            )
        return result


# Response Schemas
class StatusResponse(BaseModel):
    status: str


class AttachResponse(StatusResponse):
    ue_id: int


class DetachResponse(StatusResponse):
    ue_id: int


class BearerAddResponse(StatusResponse):
    ue_id: int
    bearer_id: int


class BearerDeleteResponse(StatusResponse):
    ue_id: int
    bearer_id: int


class TrafficStartResponse(StatusResponse):
    ue_id: int
    bearer_id: int
    target_bps: int


class TrafficStopResponse(StatusResponse):
    ue_id: int
    bearer_id: int


class TrafficStatsResponse(BaseModel):
    ue_id: int
    bearer_id: int
    protocol: str | None = None
    target_bps: int | None = None
    tx_bps: int
    rx_bps: int
    duration: float


class UEDisplayResponse(UEState):
    pass


class UEListResponse(BaseModel):
    ues: list[int]


class AggregatedStatsResponse(BaseModel):
    scope: str  # 'all' or f'ue:{id}'
    ue_count: int
    bearer_count: int
    total_tx_bps: int
    total_rx_bps: int
    details: dict[str, dict[str, int]] | None = None  # per ue optional
