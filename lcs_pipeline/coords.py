from __future__ import annotations
from math import cos, pi
from pathlib import Path
import json
from dataclasses import dataclass
from typing import Iterable
import numpy as np
from matplotlib.path import Path as MplPath
EARTH_RADIUS_KM = 6371.0088

@dataclass
class AOIInfo:
    geometry_type: str
    bbox: dict[str, float]
    centroid_lon: float
    centroid_lat: float
    polygons: list[np.ndarray]
    source_path: str | None = None

def _flatten_polygons(geom: dict) -> list[np.ndarray]:
    gtype = geom.get('type')
    coords = geom.get('coordinates', [])
    if gtype == 'Polygon':
        return [np.asarray(coords[0], dtype=float)] if coords else []
    if gtype == 'MultiPolygon':
        return [np.asarray(poly[0], dtype=float) for poly in coords if poly]
    raise ValueError(f'Unsupported geometry type: {gtype}')

def aoi_from_geojson(path: str | Path) -> AOIInfo:
    path = Path(path)
    obj = json.loads(path.read_text(encoding='utf-8'))
    if obj.get('type') == 'FeatureCollection':
        geoms = [feat['geometry'] for feat in obj.get('features', []) if feat.get('geometry')]
    elif obj.get('type') == 'Feature':
        geoms = [obj['geometry']]
    else:
        geoms = [obj]
    polygons: list[np.ndarray] = []
    for geom in geoms:
        polygons.extend(_flatten_polygons(geom))
    if not polygons:
        raise ValueError('No supported AOI polygons found in GeoJSON')
    xs = np.concatenate([p[:, 0] for p in polygons])
    ys = np.concatenate([p[:, 1] for p in polygons])
    bbox = {'lon_min': float(xs.min()), 'lon_max': float(xs.max()), 'lat_min': float(ys.min()), 'lat_max': float(ys.max())}
    return AOIInfo('MultiPolygon' if len(polygons) > 1 else 'Polygon', bbox, float(xs.mean()), float(ys.mean()), polygons, str(path))

def bbox_info(bbox: dict[str, float]) -> AOIInfo:
    lon_min, lon_max, lat_min, lat_max = map(float, (bbox['lon_min'], bbox['lon_max'], bbox['lat_min'], bbox['lat_max']))
    poly = np.asarray([[lon_min, lat_min],[lon_max, lat_min],[lon_max, lat_max],[lon_min, lat_max],[lon_min, lat_min]], dtype=float)
    return AOIInfo('Polygon', {'lon_min': lon_min, 'lon_max': lon_max, 'lat_min': lat_min, 'lat_max': lat_max}, (lon_min+lon_max)/2, (lat_min+lat_max)/2, [poly], None)

def local_xy_from_lonlat(lon, lat, lon0: float, lat0: float):
    lon = np.asarray(lon, dtype=float); lat = np.asarray(lat, dtype=float)
    x = (lon - lon0) * (pi / 180.0) * EARTH_RADIUS_KM * cos(lat0 * pi / 180.0)
    y = (lat - lat0) * (pi / 180.0) * EARTH_RADIUS_KM
    return x, y

def lonlat_from_local_xy(x, y, lon0: float, lat0: float):
    x = np.asarray(x, dtype=float); y = np.asarray(y, dtype=float)
    lon = lon0 + (x / (EARTH_RADIUS_KM * cos(lat0 * pi / 180.0))) * (180.0 / pi)
    lat = lat0 + (y / EARTH_RADIUS_KM) * (180.0 / pi)
    return lon, lat

def polygon_mask(lon_grid: np.ndarray, lat_grid: np.ndarray, polygons: list[np.ndarray]) -> np.ndarray:
    pts = np.column_stack([lon_grid.ravel(), lat_grid.ravel()])
    masks = [MplPath(poly[:, :2]).contains_points(pts) for poly in polygons]
    merged = np.logical_or.reduce(masks) if masks else np.ones(len(pts), dtype=bool)
    return merged.reshape(lon_grid.shape)
