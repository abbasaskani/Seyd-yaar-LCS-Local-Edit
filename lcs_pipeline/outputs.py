from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr

from .ftle import FTLEOutputs


def save_ftle_netcdf(out: FTLEOutputs, path: str | Path) -> Path:
    path = Path(path)
    data_vars = {
        "ftle": (("x", "y"), out.ftle),
        "ftle_smooth": (("x", "y"), out.ftle_smooth),
        "ridge_support": (("x", "y"), out.ridge_support),
        "lon": (("x", "y"), out.lon_grid),
        "lat": (("x", "y"), out.lat_grid),
        "current_u": (("x", "y"), out.current_u) if out.current_u is not None else (("x", "y"), np.full_like(out.ftle, np.nan)),
        "current_v": (("x", "y"), out.current_v) if out.current_v is not None else (("x", "y"), np.full_like(out.ftle, np.nan)),
        "current_speed": (("x", "y"), out.current_speed) if out.current_speed is not None else (("x", "y"), np.full_like(out.ftle, np.nan)),
    }
    for name in [
        "persistence_3d",
        "persistence_5d",
        "balanced_composite",
        "physics_first_composite",
        "accumulation_potential_balanced",
        "accumulation_potential_physics_first",
    ]:
        value = getattr(out, name, None)
        if value is not None:
            data_vars[name] = (("x", "y"), value)
    attrs = {"target_time": out.target_time, "u_variable": out.u_variable, "v_variable": out.v_variable, **(out.metadata or {})}
    attrs = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict,list)) else
                 int(v) if isinstance(v, bool) else
                 '' if v is None else v)
             for k,v in attrs.items()}
    ds = xr.Dataset(
        data_vars=data_vars,
        coords={"x": out.x_grid[:, 0], "y": out.y_grid[0, :]},
        attrs=attrs,
    )
    try:
        import netCDF4  # noqa: F401
        encoding = {name: {'zlib': True, 'complevel': 1, 'shuffle': True} for name in ds.data_vars}
        ds.to_netcdf(path, engine='netcdf4', encoding=encoding)
    except ImportError:
        ds.to_netcdf(path)
    return path


def save_hotspots_csv(out: FTLEOutputs, path: str | Path) -> Path:
    path = Path(path)
    pd.DataFrame(out.hotspots).to_csv(path, index=False)
    return path


def save_summary_json(out: FTLEOutputs, path: str | Path, extra: dict | None = None) -> Path:
    path = Path(path)
    payload = {
        "target_time": out.target_time,
        "u_variable": out.u_variable,
        "v_variable": out.v_variable,
        "hotspots": out.hotspots,
        "top_clusters": out.clusters[:10],
        "metadata": out.metadata or {},
    }
    if extra:
        payload.update(extra)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_field_layers_json(out: FTLEOutputs, path: str | Path) -> Path:
    path = Path(path)
    payload = {
        "lon_axis": [float(x) for x in out.lon_grid[:, 0]],
        "lat_axis": [float(y) for y in out.lat_grid[0, :]],
        "bbox": {
            "lon_min": float(np.nanmin(out.lon_grid)),
            "lon_max": float(np.nanmax(out.lon_grid)),
            "lat_min": float(np.nanmin(out.lat_grid)),
            "lat_max": float(np.nanmax(out.lat_grid)),
        },
        "layers": {
            "ftle": np.nan_to_num(out.ftle, nan=-9999.0).round(6).tolist(),
            "ftle_smooth": np.nan_to_num(out.ftle_smooth, nan=-9999.0).round(6).tolist(),
            "ridge_support": np.nan_to_num(out.ridge_support, nan=-9999.0).round(6).tolist(),
            "persistence_3d": np.nan_to_num(out.persistence_3d, nan=-9999.0).round(6).tolist() if out.persistence_3d is not None else None,
            "persistence_5d": np.nan_to_num(out.persistence_5d, nan=-9999.0).round(6).tolist() if out.persistence_5d is not None else None,
            "balanced_composite": np.nan_to_num(out.balanced_composite, nan=-9999.0).round(6).tolist() if out.balanced_composite is not None else None,
            "physics_first_composite": np.nan_to_num(out.physics_first_composite, nan=-9999.0).round(6).tolist() if out.physics_first_composite is not None else None,
            "accumulation_potential_balanced": np.nan_to_num(out.accumulation_potential_balanced, nan=-9999.0).round(6).tolist() if out.accumulation_potential_balanced is not None else None,
            "accumulation_potential_physics_first": np.nan_to_num(out.accumulation_potential_physics_first, nan=-9999.0).round(6).tolist() if out.accumulation_potential_physics_first is not None else None,
            "aoi_mask": out.aoi_mask.astype(int).tolist() if out.aoi_mask is not None else None,
            "ocean_mask": out.ocean_mask.astype(int).tolist() if out.ocean_mask is not None else None,
            "current_u": np.nan_to_num(out.current_u, nan=-9999.0).round(6).tolist() if out.current_u is not None else None,
            "current_v": np.nan_to_num(out.current_v, nan=-9999.0).round(6).tolist() if out.current_v is not None else None,
            "current_speed": np.nan_to_num(out.current_speed, nan=-9999.0).round(6).tolist() if out.current_speed is not None else None,
        },
        "ridges": [ridge.round(6).tolist() for ridge in out.ridge_curves_lonlat],
        "hotspots": out.hotspots,
        "clusters": out.clusters,
        "metadata": out.metadata or {},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def save_hotspots_geojson(out: FTLEOutputs, path: str | Path) -> Path:
    path = Path(path)
    features = []
    for hs in out.hotspots:
        features.append({
            "type": "Feature",
            "properties": {k: v for k, v in hs.items() if k not in {"lon", "lat"}},
            "geometry": {"type": "Point", "coordinates": [hs["lon"], hs["lat"]]},
        })
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_clusters_geojson(out: FTLEOutputs, path: str | Path) -> Path:
    path = Path(path)
    features = []
    for cl in out.clusters:
        features.append({
            "type": "Feature",
            "properties": {k: v for k, v in cl.items() if k != "polygon_lonlat"},
            "geometry": {"type": "Polygon", "coordinates": [[list(map(float, pt)) for pt in cl["polygon_lonlat"]]]},
        })
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_ridges_geojson(out: FTLEOutputs, path: str | Path) -> Path:
    path = Path(path)
    features = []
    for idx, ridge in enumerate(out.ridge_curves_lonlat, start=1):
        features.append({
            "type": "Feature",
            "properties": {"ridge_id": idx, "n_points": int(len(ridge))},
            "geometry": {"type": "LineString", "coordinates": ridge.tolist()},
        })
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _draw_overlay(ax, out: FTLEOutputs):
    for ridge in out.ridge_curves_lonlat:
        ax.plot(ridge[:, 0], ridge[:, 1], color="black", lw=1.1, alpha=0.9)
    for cl in out.clusters[:10]:
        poly = np.array(cl["polygon_lonlat"], dtype=float)
        ax.plot(poly[:, 0], poly[:, 1], linestyle="--", lw=1.0, alpha=0.8, color="#ffffff")
        ax.text(cl["centroid_lon"], cl["centroid_lat"], f"C{cl['rank']}", fontsize=8, color="white")
    for hs in out.hotspots:
        ax.scatter(hs["lon"], hs["lat"], s=36, marker="x", color="#ffde59")
        ax.text(hs["lon"], hs["lat"], f" H{hs['rank']}", fontsize=9, color="white")


def plot_field_map(out: FTLEOutputs, path: str | Path, title: str, layer_name: str, colorbar_label: str) -> Path:
    path = Path(path)
    layer = getattr(out, layer_name)
    fig, ax = plt.subplots(figsize=(9, 7), dpi=220)
    cf = ax.contourf(out.lon_grid, out.lat_grid, layer, levels=80)
    plt.colorbar(cf, ax=ax, label=colorbar_label)
    _draw_overlay(ax, out)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(title)
    ax.set_aspect("equal", adjustable="box")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path
