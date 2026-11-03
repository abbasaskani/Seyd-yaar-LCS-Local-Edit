"""Persist explicitly entered AOI/timezone selections in version-controlled config.

Blank GitHub Actions fields mean *reuse* the settings already committed to the
repository, not the original/default coordinates. Requires no third-party libs.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path


COORDS = ("lon_min", "lon_max", "lat_min", "lat_max")


def coordinate_bounds(values: dict[str, str]) -> dict[str, float] | None:
    stripped = {key: str(values.get(key, "") or "").strip() for key in COORDS}
    supplied = [bool(value) for value in stripped.values()]
    if not any(supplied):
        return None
    if not all(supplied):
        raise ValueError("All four lon_min/lon_max/lat_min/lat_max must be supplied together, or all left blank.")
    try:
        bounds = {key: float(stripped[key]) for key in COORDS}
    except ValueError as exc:
        raise ValueError("Coordinates must be valid decimal numbers (e.g. 55.5).") from exc
    if not all(math.isfinite(value) for value in bounds.values()):
        raise ValueError("Coordinates must be finite numbers.")
    if not (-180 <= bounds["lon_min"] < bounds["lon_max"] <= 180):
        raise ValueError("Longitude must satisfy -180 <= lon_min < lon_max <= 180.")
    if not (-90 <= bounds["lat_min"] < bounds["lat_max"] <= 90):
        raise ValueError("Latitude must satisfy -90 <= lat_min < lat_max <= 90.")
    return bounds


def rectangle_geojson(bounds: dict[str, float]) -> dict:
    west, east = bounds["lon_min"], bounds["lon_max"]
    south, north = bounds["lat_min"], bounds["lat_max"]
    ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {"name": "Saved manual AOI"},
                      "geometry": {"type": "Polygon", "coordinates": [ring]}}],
    }


def write_if_changed(path: Path, payload: dict) -> bool:
    content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def persist(config_path: Path, values: dict[str, str], preset: str = "") -> dict:
    config_path = Path(config_path).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    bounds = coordinate_bounds(values)
    preset = preset.strip()
    presets = {item["key"] for item in config.get("time_reference", {}).get("presets", [])}
    if preset and preset not in presets:
        raise ValueError(f"Unknown timezone preset {preset!r}; choose one of {sorted(presets)}")

    root = config_path.parent.parent if config_path.parent.name == "config" else config_path.parent
    aoi = (root / config.get("aoi_geojson", "config/aoi/current.geojson")).resolve()
    if not aoi.is_relative_to(root):
        raise ValueError("AOI path must be located within the repository")

    changes = []
    if bounds is not None:
        if write_if_changed(aoi, rectangle_geojson(bounds)):
            changes.append(str(aoi.relative_to(root)))
        print(f"Saved AOI for subsequent runs: {bounds}")
    else:
        if not aoi.is_file():
            raise FileNotFoundError(f"Saved AOI does not exist: {aoi}. Specify all four coordinates once.")
        print(f"Reusing saved AOI without changing coordinates: {aoi.relative_to(root)}")

    if preset:
        old = config["time_reference"].get("default_preset_key")
        if old != preset:
            config["time_reference"]["default_preset_key"] = preset
            if write_if_changed(config_path, config):
                changes.append(str(config_path.relative_to(root)))
        print(f"Using saved timezone preset: {preset}")
    else:
        print(f"Reusing saved timezone preset: {config['time_reference']['default_preset_key']}")

    print("Dates: automatic from clock, using timezone preset. Routine horizons unchanged.")
    return {"changed_paths": changes, "aoi_path": str(aoi), "bounds_input": bounds}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", default="config/defaults.json")
    for coord in COORDS:
        p.add_argument("--" + coord.replace("_", "-"), default=os.getenv(coord.upper(), ""))
    p.add_argument("--preset", default=os.getenv("PRESET", ""))
    args = p.parse_args()
    result = persist(Path(args.config), {key: getattr(args, key) for key in COORDS}, args.preset)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
