import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Settings(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    backend: Literal["mock", "local", "jev"] = "mock"
    model: Literal["jev-1.13.0"] = "jev-1.13.0"
    timeout_seconds: float = Field(default=20, gt=0, le=120)
    batch_size: int = Field(default=24, ge=1, le=64)
    concurrency: int = Field(default=4, ge=1, le=16)
    max_candidate_length: int = Field(default=16, ge=2, le=64)
    ambiguity_margin: float = Field(default=0.8, ge=0)
    fast_path: bool = True
    cache_enabled: bool = False
    cache_max_entries: int = Field(default=256, ge=1)
    cache_ttl_seconds: float = Field(default=300, gt=0, allow_inf_nan=False)
    rate_limit_requests: int = Field(default=0, ge=0)
    rate_limit_window_seconds: float = Field(default=60, gt=0, allow_inf_nan=False)
    request_budget: int = Field(default=0, ge=0)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            backend=os.getenv("JEV_BACKEND", "mock"),
            model=os.getenv("JEV_MODEL", "jev-1.13.0"),
            timeout_seconds=float(os.getenv("JEV_TIMEOUT_SECONDS", "20")),
            batch_size=int(os.getenv("JEV_BATCH_SIZE", "24")),
            concurrency=int(os.getenv("JEV_CONCURRENCY", "4")),
            cache_enabled=os.getenv("JEV_CACHE_ENABLED", "0"),
            cache_max_entries=int(os.getenv("JEV_CACHE_MAX_ENTRIES", "256")),
            cache_ttl_seconds=float(os.getenv("JEV_CACHE_TTL_SECONDS", "300")),
            rate_limit_requests=int(os.getenv("JEV_RATE_LIMIT_REQUESTS", "0")),
            rate_limit_window_seconds=float(os.getenv("JEV_RATE_LIMIT_WINDOW_SECONDS", "60")),
            request_budget=int(os.getenv("JEV_REQUEST_BUDGET", "0")),
        )
