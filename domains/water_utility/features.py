"""Water-domain feature extractors: raw readings -> evidence items (pure Python only).

The engine discovers these via the EXTRACTORS registry; NO domain logic lives in core/.
Contract: each extractor takes a context dict
    {"raw": <scenario raw dict>, "incident_time": <iso str>, "thresholds": <pack thresholds>,
     "scenario_id": <str>}
and returns a list of evidence dicts (fields of core.evidence.EvidenceRecord minus `kind`
and `id`, which ingestion defaults to tool_output / deterministic ids). Extractors emit RAW
observations only — never support/contradict labels (those come from pack relation rules).
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List

import numpy as np

Extractor = Callable[[Dict[str, Any]], List[Dict[str, Any]]]

SENSOR_NOISE_SIGMA = {"ph": 0.1, "do": 0.2, "turbidity": 2.0}


def _raw(ctx: Dict[str, Any]) -> Dict[str, Any]:
    return ctx.get("raw") or {}


def _window(ts: str, incident_time: str) -> str:
    try:
        marker = datetime.fromisoformat(incident_time) if incident_time else None
        return "pre_incident" if marker and datetime.fromisoformat(ts) < marker else "post_incident"
    except ValueError:
        return "post_incident"


def extract_sensor_readings(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One evidence item per timestamped upstream/downstream sensor reading."""
    out: List[Dict[str, Any]] = []
    for r in _raw(ctx).get("sensor_readings", []):
        param, station, value = r["parameter"], r["station"], float(r["value"])
        window = _window(r["timestamp"], ctx.get("incident_time", ""))
        out.append(
            dict(
                evidence_type=f"sensor_{param}",
                source=f"sensor:{station}",
                source_group=f"{station}:{param}:{window}",
                timestamp=r["timestamp"],
                location=station,
                observation=f"{param}={value:g} at {station} ({window})",
                values={"value": value},
                reliability=0.5,
            )
        )
    return out


def extract_stream_deltas(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Downstream-minus-upstream deltas per parameter/window.

    The delta item SHARES the downstream sensor's source_group so the raw reading and its
    derived delta cannot double-count (strongest-per-group rule in docs/scoring.md).
    """
    by_key: Dict[tuple, List[Dict[str, Any]]] = {}
    for r in _raw(ctx).get("sensor_readings", []):
        window = _window(r["timestamp"], ctx.get("incident_time", ""))
        by_key.setdefault((r["parameter"], window, r["station"]), []).append(r)

    out: List[Dict[str, Any]] = []
    for param in sorted({k[0] for k in by_key}):
        for window in sorted({k[1] for k in by_key}):
            ups = sorted(by_key.get((param, window, "upstream"), []), key=lambda r: r["timestamp"])
            downs = sorted(by_key.get((param, window, "downstream"), []), key=lambda r: r["timestamp"])
            if not ups or not downs:
                continue
            delta = float(downs[0]["value"]) - float(ups[0]["value"])
            out.append(
                dict(
                    evidence_type=f"delta_{param}",
                    source="derived:stream_comparison",
                    source_group=f"downstream:{param}:{window}",
                    timestamp=downs[0]["timestamp"],
                    location=f"{ups[0]['station']}->{downs[0]['station']}",
                    observation=f"downstream-minus-upstream {param} = {delta:+.2f} ({window})",
                    values={"value": round(delta, 4)},
                    reliability=0.5,
                )
            )
    return out


def extract_release_log(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Verified direct record: logged release at the discharge meter (tier A)."""
    out: List[Dict[str, Any]] = []
    for e in _raw(ctx).get("discharge_log", []):
        if not e.get("released"):
            continue
        volume = e.get("volume_m3")
        note = f" ({volume:g} m3)" if volume is not None else ""
        out.append(
            dict(
                evidence_type="discharge_log",
                source="discharge_meter_log",
                source_group="discharge_log",
                timestamp=e["timestamp"],
                location="outfall",
                observation=f"release logged at {e['timestamp']}{note}",
                values={"value": True},
                reliability=1.0,
            )
        )
    return out


def extract_spike_timing(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Timing of the upstream turbidity spike relative to a logged release."""
    threshold = float((ctx.get("thresholds") or {}).get("turbidity_spike_value", 50.0))
    spike_ts = None
    for r in sorted(_raw(ctx).get("sensor_readings", []), key=lambda r: r["timestamp"]):
        if r["station"] == "upstream" and r["parameter"] == "turbidity" and float(r["value"]) > threshold:
            spike_ts = r["timestamp"]
            break
    release_ts = None
    for e in sorted(_raw(ctx).get("discharge_log", []), key=lambda e: e["timestamp"]):
        if e.get("released"):
            release_ts = e["timestamp"]
            break
    if spike_ts is None or release_ts is None:
        return []
    precedes = spike_ts < release_ts
    out = [
        dict(
            evidence_type="spike_timing",
            source="derived:timing",
            source_group="upstream_chain",
            timestamp=spike_ts,
            location="upstream",
            observation=(
                f"upstream turbidity spike at {spike_ts} "
                + ("before" if precedes else "after")
                + f" logged release at {release_ts}"
            ),
            values={"value": "spike_precedes_release" if precedes else "release_precedes_spike"},
            reliability=0.5,
        )
    ]
    if precedes:
        out.append(
            dict(
                evidence_type="upstream_inference",
                source="derived:upstream_chain",
                source_group="upstream_chain",
                timestamp=spike_ts,
                location="upstream",
                observation="pollution signature present upstream before the logged release",
                values={"value": "upstream_spike_before_release"},
                reliability=0.5,
            )
        )
    return out


def extract_rainfall_total(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Modelled rainfall total around the incident (tier C; a gauge record would be tier B)."""
    entries = _raw(ctx).get("rainfall", [])
    if not entries:
        return []
    total = sum(float(e["mm"]) for e in entries)
    if total <= 0:
        return []
    return [
        dict(
            evidence_type="rainfall_inference",
            source="rainfall_model",
            source_group="rainfall",
            timestamp=max(e["timestamp"] for e in entries),
            location="catchment",
            observation=f"rainfall total {total:g}mm around the incident",
            values={"value": round(total, 2)},
            reliability=0.5,
        )
    ]


EXTRACTORS: Dict[str, Extractor] = {
    "rainfall_total": extract_rainfall_total,
    "release_log": extract_release_log,
    "sensor_readings": extract_sensor_readings,
    "spike_timing": extract_spike_timing,
    "stream_deltas": extract_stream_deltas,
}


def make_noisy_variant(scenario: Dict[str, Any], seed: int = 0) -> Dict[str, Any]:
    """Seeded noisy variant: gaussian sensor noise + small timestamp shifts (<=5 min)."""
    variant = deepcopy(scenario)
    rng = np.random.default_rng(seed)
    for r in variant.get("raw", {}).get("sensor_readings", []):
        sigma = SENSOR_NOISE_SIGMA.get(r["parameter"], 1.0)
        r["value"] = round(float(r["value"]) + float(rng.normal(0.0, sigma)), 3)
        shift = int(rng.integers(-5, 6))
        try:
            r["timestamp"] = (datetime.fromisoformat(r["timestamp"]) + timedelta(minutes=shift)).isoformat()
        except ValueError:
            pass
    return variant
