"""Small, versioned browser visualization payload; full-fidelity results stay in NetCDF."""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np

LAYERS = [
    'ftle_smooth', 'ridge_support', 'current_speed', 'current_u', 'current_v',
    'accumulation_potential_physics_first', 'accumulation_potential_balanced',
    'persistence_3d', 'persistence_5d', 'physics_first_composite',
    'balanced_composite', 'ocean_mask',
]

def save_web_day(out, dest: str | Path) -> Path:
    """Write packed little-endian float32 layers and an explicit geographic metadata file.

    The Float32 web raster is for visualization ONLY, not FTLE recomputation;
    scientific values live in the original NetCDF.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    shape = out.ftle_smooth.shape
    if out.lon_grid.shape != shape or out.lat_grid.shape != shape:
        raise ValueError('Geographic coordinate and raster sizes differ')
    if not np.all(np.diff(out.lon_grid[:, 0]) > 0) or not np.all(np.diff(out.lat_grid[0, :]) > 0):
        raise ValueError('Expected ascending lon/lat axes')
    data = dest / 'web_layers.f32'
    with data.open('wb') as file:
        for name in LAYERS:
            value = getattr(out, name, None)
            if value is None:
                value = np.full(shape, np.nan)
            value = np.asarray(value, dtype='<f4')
            if value.shape != shape:
                raise ValueError(f'Layer {name} has shape {value.shape}, expected {shape}')
            file.write(value.tobytes(order='C'))
    meta = {
        'format': 'seyd-yaar-flat-f32-v1', 'file': data.name,
        'shape': list(shape), 'layers': LAYERS,
        'lon_axis': out.lon_grid[:, 0].astype(float).tolist(),
        'lat_axis': out.lat_grid[0, :].astype(float).tolist(),
        'metadata': out.metadata or {},
        'ridges': [np.asarray(x).round(6).tolist() for x in out.ridge_curves_lonlat],
        'hotspots': out.hotspots, 'clusters': out.clusters,
    }
    path = dest / 'web_day.json'
    path.write_text(json.dumps(meta, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    return path
