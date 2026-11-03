"""Density benchmark dataset: other projects' parcel size and unit count.

The dataset is a plain JSON file so it can be replaced by a Datacenter export
without code changes. The repository ships a synthetic sample flagged
``is_sample: true``; the frontend shows that flag so sample figures are never
mistaken for market data.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from app.config import get_settings


class BenchmarkProjectRecord(BaseModel):
    project_id: str | None = None
    project_name: str
    city: str
    locality: str | None = None
    micromarket: str | None = None
    project_area_acres: float = Field(gt=0)
    total_units: int = Field(gt=0)


class BenchmarkDataset(BaseModel):
    name: str
    version: str | None = None
    as_of: str | None = None
    is_sample: bool = False
    projects: list[BenchmarkProjectRecord] = Field(default_factory=list)


def load_density_benchmarks(path: str | Path | None = None) -> BenchmarkDataset | None:
    """Load the dataset from ``path`` or the configured default; None if missing."""
    settings = get_settings()
    candidate = Path(path) if path else Path(settings.density_benchmarks_path)
    if not candidate.is_absolute():
        candidate = settings.project_root / candidate
    return _load_cached(str(candidate))


@lru_cache(maxsize=4)
def _load_cached(path: str) -> BenchmarkDataset | None:
    file_path = Path(path)
    if not file_path.is_file():
        return None
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    return BenchmarkDataset.model_validate(payload)
