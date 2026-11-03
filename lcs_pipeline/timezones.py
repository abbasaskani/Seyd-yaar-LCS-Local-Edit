from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


@dataclass
class TimePreset:
    key: str
    label: str
    tz: str
    utc_offset_hint: str
    lon: float
    lat: float


@dataclass
class TimezoneDecision:
    preset: TimePreset
    auto_selected: bool


@dataclass
class TimeSelection:
    preset: TimePreset
    auto_selected: bool
    local_nominal: datetime
    actual_utc: datetime
    actual_local: datetime
    fallback_status: str
    candidate_windows_utc: list[tuple[datetime, datetime, str]]
    requested_target_date_local: str


def load_presets(config_raw: dict[str, Any]) -> list[TimePreset]:
    return [TimePreset(**item) for item in config_raw["time_reference"]["presets"]]


def select_preset(config_raw: dict[str, Any], centroid_lon: float | None = None, centroid_lat: float | None = None, override_key: str | None = None) -> TimezoneDecision:
    presets = load_presets(config_raw)
    by_key = {p.key: p for p in presets}
    if override_key:
        if override_key not in by_key:
            raise KeyError(f"Unknown timezone preset override: {override_key}")
        return TimezoneDecision(by_key[override_key], False)

    default_key = config_raw.get("time_reference", {}).get("default_preset_key")
    if default_key:
        if default_key not in by_key:
            raise KeyError(f"Unknown default timezone preset: {default_key}")
        return TimezoneDecision(by_key[default_key], False)

    if centroid_lon is None or centroid_lat is None:
        raise ValueError("centroid coordinates required when no default preset is configured")

    def dist2(p: TimePreset) -> float:
        return (p.lon - centroid_lon) ** 2 + (p.lat - centroid_lat) ** 2

    return TimezoneDecision(min(presets, key=dist2), True)


def build_target_windows(config_raw: dict[str, Any], base_local_date: datetime, tz_name: str):
    tz = ZoneInfo(tz_name)
    cfg = config_raw["time_reference"]
    hour = int(cfg.get("target_local_hour", 18))
    same_day_end = int(cfg.get("fallback_same_day_end_hour", 23))
    next_day_end = int(cfg.get("fallback_next_day_end_hour", 6))

    nominal_local = base_local_date.replace(hour=hour, minute=0, second=0, microsecond=0, tzinfo=tz)
    same_day_end_local = base_local_date.replace(hour=same_day_end, minute=59, second=59, microsecond=0, tzinfo=tz)
    next_morning_start_local = (base_local_date + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=tz)
    next_morning_end_local = (base_local_date + timedelta(days=1)).replace(hour=next_day_end, minute=0, second=0, microsecond=0, tzinfo=tz)
    windows = [
        (nominal_local.astimezone(timezone.utc), nominal_local.astimezone(timezone.utc), "exact_18_local"),
        (nominal_local.astimezone(timezone.utc), same_day_end_local.astimezone(timezone.utc), "same_day_evening_fallback"),
        (next_morning_start_local.astimezone(timezone.utc), next_morning_end_local.astimezone(timezone.utc), "next_day_morning_fallback"),
    ]
    return nominal_local, windows, next_morning_end_local.astimezone(timezone.utc)


def choose_actual_time(candidates_utc, windows_utc, preset: TimePreset, auto_selected: bool, requested_nominal_local: datetime) -> TimeSelection:
    cands = sorted(candidates_utc)
    chosen, status = None, "not_found"
    for start_utc, end_utc, tag in windows_utc:
        hits = [t for t in cands if start_utc <= t <= end_utc]
        if not hits:
            continue
        chosen = min(hits, key=lambda t: abs((t - start_utc).total_seconds())) if tag == "exact_18_local" else hits[0]
        status = tag
        break
    if chosen is None:
        raise RuntimeError("No available dataset time found in target / fallback windows")
    actual_local = chosen.astimezone(ZoneInfo(preset.tz))
    return TimeSelection(
        preset=preset,
        auto_selected=auto_selected,
        local_nominal=requested_nominal_local,
        actual_utc=chosen,
        actual_local=actual_local,
        fallback_status=status,
        candidate_windows_utc=windows_utc,
        requested_target_date_local=requested_nominal_local.date().isoformat(),
    )
