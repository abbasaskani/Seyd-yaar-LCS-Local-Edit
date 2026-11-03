"""Coast-aware advection: reject trajectories crossing the model's land mask.

This is a conservative *model-grid* boundary, not high-resolution coastline
physics. Nearshore cells are excluded rather than presenting false FTLE ridges.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import binary_erosion, distance_transform_edt, map_coordinates


def native_water_mask(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """(time, lon, lat) -> stable ocean cells. Intermittent NaNs are invalid."""
    if u.shape != v.shape or u.ndim != 3:
        raise ValueError('Expected matching (time, longitude, latitude) velocity arrays')
    return np.isfinite(u).all(axis=0) & np.isfinite(v).all(axis=0)


def fill_ocean_velocity(data: np.ndarray, water: np.ndarray) -> np.ndarray:
    """Nearest-ocean numerical fill; filled land values are NEVER valid output."""
    if not np.any(water):
        raise ValueError('No usable ocean cells in selected area')
    idx = distance_transform_edt(~water, return_distances=False, return_indices=True)
    return np.asarray(data[:, idx[0], idx[1]], dtype=np.float64)


def _grid_coords(xp, yp, x, y):
    return ((xp - x[0]) / (x[1] - x[0]), (yp - y[0]) / (y[1] - y[0]))


def coast_safe_flowmap(t_hours, x_native, y_native, u_kmh, v_kmh,
                        x_out, y_out, backward_hours=168., max_step_hours=1.,
                        coast_guard_native_cells=1, return_diagnostics=False,
                        max_displacement_native_cells=0.75,
                        reference_lat_deg=None, max_input_time_gap_hours=3.01):
    """Advect back from t=0, validating ocean at every RK4 evaluation.

    Returns (flowmap[nx,ny,2], valid[nx,ny], native_water[nx,ny]).
    Velocity is in km/h and native axes in km. No unphysical land crossing.
    """
    t = np.asarray(t_hours, dtype=float)
    if len(t) < 2 or not np.all(np.diff(t) > 0):
        raise ValueError('Time samples must be strictly increasing')
    if t[0] > -backward_hours + 1.01 or t[-1] < -0.01:
        raise ValueError('Insufficient temporal coverage for complete backward FTLE')
    # Time interpolation uses actual timestamps; operational configuration
    # uses a stricter 1.51-hour limit for the hourly Copernicus product.
    diffs = np.diff(t)
    if np.nanmax(diffs) > max_input_time_gap_hours + 1e-6:
        raise ValueError('A gap in ocean currents exceeds the approved sampling interval')
    water = native_water_mask(u_kmh, v_kmh)
    if min(water.shape) < 3 or not water.any():
        raise ValueError('Area too small or entirely land')
    safe_water = binary_erosion(water, iterations=int(coast_guard_native_cells), border_value=0) if coast_guard_native_cells else water
    if not safe_water.any():
        raise ValueError('No safe offshore grid cells after coast margin')
    uf = fill_ocean_velocity(u_kmh, water)
    vf = fill_ocean_velocity(v_kmh, water)
    X, Y = np.meshgrid(x_out, y_out, indexing='ij')
    xp, yp = X.ravel().copy(), Y.ravel().copy()
    initial = np.column_stack((xp.copy(), yp.copy()))
    valid = np.ones(xp.size, dtype=bool)
    failure_reason = np.zeros(xp.size, dtype=np.uint8)  # 0 valid, 1 land/guard, 2 grid edge, 3 nonfinite
    # Keep a step below a fraction of the native velocity cell at the maximum
    # available speed. This does NOT increase the native ocean model resolution.
    # It only avoids stepping over an entire native cell in one RK4 step.
    if not (0 < float(max_displacement_native_cells) <= 1.0):
        raise ValueError('max_displacement_native_cells must be in (0, 1]')
    if float(max_step_hours) <= 0:
        raise ValueError('max_step_hours must be positive')
    native_spacing_km = min(float(np.min(np.diff(x_native))), float(np.min(np.diff(y_native))))
    max_speed_kmh = float(np.nanmax(np.hypot(u_kmh[:, water], v_kmh[:, water])))
    h_limit = float(max_step_hours)
    if max_speed_kmh > 0:
        h_limit = min(h_limit, max_displacement_native_cells * native_spacing_km / max_speed_kmh)
    if not np.isfinite(h_limit) or h_limit <= 0:
        raise ValueError('Cannot select a valid advection step from the velocity field')
    step_count = int(np.ceil(float(backward_hours) / h_limit))
    h = -float(backward_hours) / step_count

    def sample(xp_, yp_, time_):
        ix, iy = _grid_coords(xp_, yp_, x_native, y_native)
        inside = ((ix >= 0) & (ix <= len(x_native)-1) & (iy >= 0) & (iy <= len(y_native)-1))
        cells = np.vstack((ix, iy))
        wet = map_coordinates(safe_water.astype(np.float32), cells, order=0, mode='constant', cval=0.0) >= 0.5
        # Bilinear interpolation needs all four native spatial corners to be
        # water. A wet nearest cell alone can still interpolate THROUGH land.
        ix0 = np.clip(np.floor(ix).astype(np.int64), 0, len(x_native)-1)
        iy0 = np.clip(np.floor(iy).astype(np.int64), 0, len(y_native)-1)
        ix1 = np.minimum(ix0 + 1, len(x_native)-1)
        iy1 = np.minimum(iy0 + 1, len(y_native)-1)
        wet &= (water[ix0, iy0] & water[ix0, iy1] & water[ix1, iy0] & water[ix1, iy1])
        ti = np.interp(time_, t, np.arange(len(t), dtype=float))
        coords = np.vstack((np.full(xp_.shape, ti), ix, iy))
        uu = map_coordinates(uf, coords, order=1, mode='nearest')
        vv = map_coordinates(vf, coords, order=1, mode='nearest')
        finite = np.isfinite(uu) & np.isfinite(vv)
        if reference_lat_deg is not None:
            from .geometry import zonal_projection_factor
            uu = uu * zonal_projection_factor(yp_, float(reference_lat_deg))
        return uu, vv, inside & wet & finite, inside, wet, finite

    # Updating only live particles cuts cost once paths reach land / the grid edge.
    for step in range(step_count):
        live = np.flatnonzero(valid)
        if live.size == 0:
            break
        px, py = xp[live], yp[live]
        now = step * h
        u1, v1, ok1, in1, wet1, fin1 = sample(px, py, now)
        u2, v2, ok2, in2, wet2, fin2 = sample(px + h*u1/2, py + h*v1/2, now+h/2)
        u3, v3, ok3, in3, wet3, fin3 = sample(px + h*u2/2, py + h*v2/2, now+h/2)
        u4, v4, ok4, in4, wet4, fin4 = sample(px + h*u3, py + h*v3, now+h)
        nx = px + (h / 6) * (u1 + 2*u2 + 2*u3 + u4)
        ny = py + (h / 6) * (v1 + 2*v2 + 2*v3 + v4)
        _, _, end_ok, end_inside, end_wet, end_fin = sample(nx, ny, now+h)
        good = ok1 & ok2 & ok3 & ok4 & end_ok
        inside = in1 & in2 & in3 & in4 & end_inside
        wet = wet1 & wet2 & wet3 & wet4 & end_wet
        finite = fin1 & fin2 & fin3 & fin4 & end_fin & np.isfinite(nx) & np.isfinite(ny)
        failure_reason[live[~good]] = np.where(~inside[~good], 2, np.where(~finite[~good], 3, 1))
        xp[live[good]], yp[live[good]] = nx[good], ny[good]
        valid[live[~good]] = False
    if not valid.any():
        raise ValueError('All particle trajectories are invalid: coastline, data boundary or missing flow')
    flowmap = np.stack((xp, yp), axis=-1).reshape(len(x_out), len(y_out), 2)
    result = (flowmap, valid.reshape(len(x_out),len(y_out)), water)
    if not return_diagnostics:
        return result
    qc = {
        'initial_particles': int(valid.size),
        'valid_trajectories': int(valid.sum()),
        'valid_trajectory_fraction': float(valid.mean()),
        'invalid_land_or_guard': int(np.count_nonzero(failure_reason == 1)),
        'invalid_domain_exit': int(np.count_nonzero(failure_reason == 2)),
        'invalid_nonfinite': int(np.count_nonzero(failure_reason == 3)),
        'completed_hours': float(backward_hours),
        'step_hours': float(abs(h)),
        'steps': int(step_count),
        'native_cell_min_spacing_km': native_spacing_km,
        'max_dataset_current_kmh': max_speed_kmh,
        'maximum_input_time_gap_hours': float(np.max(diffs)),
        'max_displacement_native_cells': float(max_displacement_native_cells),
        'spherical_zonal_correction': reference_lat_deg is not None,
        'spatial_step_limited': bool(h_limit < max_step_hours),
    }
    return result + (qc,)
