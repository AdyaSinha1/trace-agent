"""Open-Meteo rainfall tool (water domain) with a local .cache/ and a simulated fallback.

Returns which source was used — "cache" | "open_meteo" | "simulated" — so callers can record
it in the ledger. Simulated results are deterministic (seeded) and are NOT cached (a later
online attempt must still try the network). Read-only filesystems fall back to a temp dir.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import numpy as np
import requests


def _writable_dir(preferred: Path) -> Path:
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        probe = preferred / ".probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return preferred
    except OSError:
        return Path(tempfile.gettempdir()) / "trace_cache"


def _cache_key(lat: float, lon: float, start: str, end: str) -> str:
    return hashlib.sha256(f"{lat}|{lon}|{start}|{end}".encode()).hexdigest()[:16]


def _simulated(lat: float, lon: float, start: str, end: str, key: str) -> Dict[str, Any]:
    """Deterministic pseudo-rainfall from the request parameters (offline fallback)."""
    try:
        days = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days + 1
    except ValueError:
        days = 7
    days = max(1, min(days, 31))
    rng = np.random.default_rng(int(key[:8], 16))
    series = {str(i): round(max(0.0, float(rng.normal(4.0, 3.0))), 1) for i in range(days)}
    return {"source": "simulated", "total_mm": round(sum(series.values()), 2), "series": series, "unit": "mm"}


def open_meteo_rainfall(
    lat: float,
    lon: float,
    start: str,
    end: str,
    cache_dir: str | Path = ".cache",
    timeout: int = 10,
) -> Dict[str, Any]:
    """Daily rain_sum (mm) for [start, end]. Order: cache -> Open-Meteo -> simulated."""
    cache = _writable_dir(Path(cache_dir))
    key = _cache_key(lat, lon, start, end)
    cache_file = cache / f"rain_{key}.json"
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            data = dict(data)
            data["source"] = "cache"
            return data
        except (OSError, ValueError):
            pass  # corrupt cache: fall through to the network
    try:
        resp = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={"latitude": lat, "longitude": lon, "start_date": start, "end_date": end, "daily": "rain_sum"},
            timeout=timeout,
        )
        resp.raise_for_status()
        daily = resp.json()["daily"]
        series = {d: (v or 0.0) for d, v in zip(daily["time"], daily["rain_sum"])}
        data = {"source": "open_meteo", "total_mm": round(sum(series.values()), 2), "series": series, "unit": "mm"}
        cache_file.write_text(json.dumps(data), encoding="utf-8")
        return data
    except Exception:
        return _simulated(lat, lon, start, end, key)


def rainfall_to_evidence(data: Dict[str, Any], timestamp: str, location: str = "catchment") -> Dict[str, Any]:
    """Ledger-ready evidence dict; the data source is recorded in the observation text."""
    source = data.get("source", "unknown")
    evidence_type = "rainfall_gauge" if source in {"open_meteo", "cache"} else "rainfall_inference"
    return dict(
        evidence_type=evidence_type,
        source=f"rainfall:{source}",
        source_group="rainfall",
        timestamp=timestamp,
        location=location,
        observation=f"rainfall total {data.get('total_mm', 0.0)}mm (source: {source})",
        values={"value": data.get("total_mm", 0.0)},
        reliability=1.0 if source in {"open_meteo", "cache"} else 0.5,
    )
