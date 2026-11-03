from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter, label, binary_erosion, map_coordinates
from scipy.spatial import ConvexHull, QhullError, cKDTree

from .coords import AOIInfo, local_xy_from_lonlat, lonlat_from_local_xy, polygon_mask
from .land import coast_safe_flowmap, native_water_mask, fill_ocean_velocity


@dataclass
class FTLEOutputs:
    ftle: np.ndarray
    ftle_smooth: np.ndarray
    ridge_curves_xy: list[np.ndarray]
    ridge_curves_lonlat: list[np.ndarray]
    ridge_support: np.ndarray
    hotspots: list[dict[str, Any]]
    clusters: list[dict[str, Any]]
    lon_grid: np.ndarray
    lat_grid: np.ndarray
    x_grid: np.ndarray
    y_grid: np.ndarray
    target_time: str
    u_variable: str
    v_variable: str
    aoi_mask: np.ndarray | None = None
    ocean_mask: np.ndarray | None = None
    current_u: np.ndarray | None = None
    current_v: np.ndarray | None = None
    current_speed: np.ndarray | None = None
    metadata: dict[str, Any] | None = None
    persistence_3d: np.ndarray | None = None
    persistence_5d: np.ndarray | None = None
    balanced_composite: np.ndarray | None = None
    physics_first_composite: np.ndarray | None = None
    accumulation_potential_balanced: np.ndarray | None = None
    accumulation_potential_physics_first: np.ndarray | None = None


def _upsampled_axis(arr: np.ndarray, factor: float) -> np.ndarray:
    n_native = len(arr)
    n_out = max(n_native, int(round((n_native - 1) * factor)) + 1)
    return np.linspace(float(arr[0]), float(arr[-1]), n_out)


def _pick_well_separated_points(candidates: list[dict[str, Any]], min_sep_px: int, top_n: int) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    for cand in candidates:
        i, j = cand["i"], cand["j"]
        ok = True
        for prev in chosen:
            if (i - prev["i"]) ** 2 + (j - prev["j"]) ** 2 < min_sep_px**2:
                ok = False
                break
        if ok:
            chosen.append(cand)
            if len(chosen) >= top_n:
                break
    return chosen


def _component_polygon(lons: np.ndarray, lats: np.ndarray) -> list[list[float]]:
    pts = np.column_stack([lons, lats])
    if len(pts) == 1:
        lon, lat = pts[0]
        eps = 1e-3
        return [[lon - eps, lat - eps], [lon + eps, lat - eps], [lon + eps, lat + eps], [lon - eps, lat + eps], [lon - eps, lat - eps]]
    if len(pts) == 2:
        p0, p1 = pts
        return [p0.tolist(), p1.tolist(), p1.tolist(), p0.tolist(), p0.tolist()]
    try:
        hull = ConvexHull(pts)
        poly = pts[hull.vertices].tolist()
        poly.append(poly[0])
        return poly
    except QhullError:
        xmin, ymin = np.min(pts, axis=0); xmax, ymax = np.max(pts, axis=0)
        e = 1e-4
        return [[xmin-e,ymin-e],[xmax+e,ymin-e],[xmax+e,ymax+e],[xmin-e,ymax+e],[xmin-e,ymin-e]]


def robust_normalize(field: np.ndarray, q_low: float = 5.0, q_high: float = 95.0) -> np.ndarray:
    arr = np.array(field, dtype=float, copy=True)
    arr[~np.isfinite(arr)] = np.nan
    if not np.any(np.isfinite(arr)):
        return np.full_like(arr, np.nan)
    lo = np.nanpercentile(arr, q_low)
    hi = np.nanpercentile(arr, q_high)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        out = np.zeros_like(arr)
        out[np.isfinite(arr)] = 0.0
        return out
    out = (arr - lo) / (hi - lo)
    out = np.clip(out, 0.0, 1.0)
    out[~np.isfinite(arr)] = np.nan
    return out


def compute_ridge_support(lon_grid: np.ndarray, lat_grid: np.ndarray, ridge_curves_lonlat: list[np.ndarray], ftle_smooth: np.ndarray, d0_deg: float = 0.15) -> np.ndarray:
    if not ridge_curves_lonlat:
        return np.zeros_like(ftle_smooth, dtype=float)
    support_terms = []
    ftle_norm = robust_normalize(ftle_smooth)
    lon_axis = lon_grid[:, 0]
    lat_axis = lat_grid[0, :]
    for ridge in ridge_curves_lonlat:
        if len(ridge) == 0:
            continue
        # KD-tree avoids O(N_grid * N_ridge_points) intermediate allocation.
        nearest = cKDTree(ridge[:, :2])
        d = nearest.query(np.column_stack([lon_grid.ravel(), lat_grid.ravel()]), workers=1)[0].reshape(lon_grid.shape)
        ix = np.abs(lon_axis[:, None] - ridge[:, 0][None, :]).argmin(axis=0)
        iy = np.abs(lat_axis[None, :] - ridge[:, 1][:, None]).argmin(axis=1)
        strengths = [float(ftle_norm[a, b]) for a, b in zip(ix, iy)]
        finite_strengths = [v for v in strengths if np.isfinite(v)]
        ridge_strength = float(np.mean(finite_strengths)) if finite_strengths else 0.0
        term = np.clip(ridge_strength, 0.0, 1.0) * np.exp(-d / max(d0_deg, 1e-6))
        support_terms.append(np.clip(term, 0.0, 1.0))
    if not support_terms:
        return np.where(np.isfinite(ftle_smooth), 0.0, np.nan)
    prod = np.ones_like(ftle_smooth, dtype=float)
    for term in support_terms:
        prod *= 1.0 - term
    return np.where(np.isfinite(ftle_smooth), np.clip(1.0 - prod, 0.0, 1.0), np.nan)


def compute_attracting_ftle(ds, u_var: str, v_var: str, config_raw: dict[str, Any], aoi_info: AOIInfo | None = None) -> FTLEOutputs:
    from numbacs.extraction import ftle_ordered_ridges
    from .geometry import metric_ftle_from_flowmap

    lon = ds["longitude"].values.astype(float)
    lat = ds["latitude"].values.astype(float)
    time = ds["time"].values
    target_time = np.datetime64(ds["time"].values[-1])
    lon0 = float(lon.mean())
    lat0 = float(lat.mean())

    x_native, _ = local_xy_from_lonlat(lon, np.full_like(lon, lat0), lon0=lon0, lat0=lat0)
    _, y_native = local_xy_from_lonlat(np.full_like(lat, lon0), lat, lon0=lon0, lat0=lat0)
    t_hours = ((time - target_time) / np.timedelta64(1, "h")).astype(float)

    T = -24.0 * float(config_raw["backward_days"])

    u = ds[u_var].values.astype(np.float64)
    v = ds[v_var].values.astype(np.float64)
    # The ocean product is expected to provide eastward/northward velocity in
    # m/s; silently assuming other units would corrupt the entire flowmap.
    velocity_units_missing = []
    for name in (u_var, v_var):
        units = str(ds[name].attrs.get('units', '')).strip().lower().replace(' ', '')
        accepted = {'m/s', 'ms-1', 'ms^-1', 'ms**-1', 'metrespersecond', 'meterspersecond'}
        if not units:
            velocity_units_missing.append(name)
        if units and units not in accepted:
            raise ValueError(f'Unexpected physical units for {name}: {ds[name].attrs.get("units")!r}; expected m/s')
    scale = 3.6
    u = np.transpose(u, (0, 2, 1)) * scale
    v = np.transpose(v, (0, 2, 1)) * scale

    factor = float(config_raw.get("compute_grid_factor", 3.0))
    x_full = _upsampled_axis(x_native, factor)
    y_full = _upsampled_axis(y_native, factor)
    # Track only the requested AOI, with enough extra seeds for finite-difference
    # derivatives / smoothing near its border. The velocity grid remains buffered.
    if aoi_info is not None:
        margin = int(config_raw.get('seed_margin_cells', 8))
        lon_full, _ = lonlat_from_local_xy(x_full, np.zeros_like(x_full), lon0, lat0)
        _, lat_full = lonlat_from_local_xy(np.zeros_like(y_full), y_full, lon0, lat0)
        def crop_axis(axis, bounds, pad):
            ids = np.flatnonzero((axis >= bounds[0]) & (axis <= bounds[1]))
            if ids.size < 2:
                raise ValueError('The AOI is too small for the requested FTLE seed grid')
            return slice(max(0, int(ids[0])-pad), min(len(axis), int(ids[-1])+pad+1))
        xs = crop_axis(lon_full, (aoi_info.bbox['lon_min'], aoi_info.bbox['lon_max']), margin)
        ys = crop_axis(lat_full, (aoi_info.bbox['lat_min'], aoi_info.bbox['lat_max']), margin)
        x, y = x_full[xs], y_full[ys]
    else:
        x, y = x_full, y_full
    dx, dy = float(x[1] - x[0]), float(y[1] - y[0])
    land_cfg = config_raw.get('land_handling', {})
    # A single bounded, coastline-aware trajectory algorithm for all regions.
    # Previous NumbaCS DOP853 path silently classified failed paths as valid.
    # Fixed-step RK4 is a different numerical method: convergence must be checked.
    flowmap, trajectory_valid, ocean_native, trajectory_qc = coast_safe_flowmap(
        t_hours, x_native, y_native, u, v, x, y, backward_hours=abs(T),
        max_step_hours=float(land_cfg.get('max_step_hours', 1)),
        coast_guard_native_cells=int(land_cfg.get('coast_guard_native_cells', 1)),
        return_diagnostics=True,
        max_displacement_native_cells=float(land_cfg.get('max_displacement_native_cells', 0.75)),
        reference_lat_deg=lat0 if config_raw.get('spherical_metric', True) else None,
        max_input_time_gap_hours=float(land_cfg.get('max_time_gap_hours', 1.51)),
    )
    # Lightweight convergence diagnostic, not a substitute for full validation.
    # Same seed points, same velocity data, half the RK4 temporal step.
    ix_test = np.unique(np.linspace(0, len(x)-1, min(11, len(x)), dtype=int))
    iy_test = np.unique(np.linspace(0, len(y)-1, min(11, len(y)), dtype=int))
    try:
        half_flow, half_valid, _ = coast_safe_flowmap(
            t_hours, x_native, y_native, u, v, x[ix_test], y[iy_test],
            backward_hours=abs(T),
            max_step_hours=float(land_cfg.get('max_step_hours', 1)) / 2,
            coast_guard_native_cells=int(land_cfg.get('coast_guard_native_cells', 1)),
            max_displacement_native_cells=float(land_cfg.get('max_displacement_native_cells', 0.75)),
            reference_lat_deg=lat0 if config_raw.get('spherical_metric', True) else None,
            max_input_time_gap_hours=float(land_cfg.get('max_time_gap_hours', 1.51)),
        )
        base_flow = flowmap[np.ix_(ix_test, iy_test)]
        base_valid = trajectory_valid[np.ix_(ix_test, iy_test)]
        both = base_valid & half_valid
        distance = np.linalg.norm(base_flow - half_flow, axis=-1)
        limit = 0.02 * min(abs(x_native[1]-x_native[0]), abs(y_native[1]-y_native[0]))
        trajectory_qc['refinement_valid_pairs'] = int(both.sum())
        trajectory_qc['refinement_max_displacement_km'] = float(np.max(distance[both])) if both.any() else None
        trajectory_qc['refinement_p95_displacement_km'] = float(np.percentile(distance[both], 95)) if both.any() else None
        trajectory_qc['refinement_fraction_of_samples_valid'] = float(both.mean())
        trajectory_qc['refinement_tolerance_km'] = float(limit)
        trajectory_qc['refinement_warning'] = bool(not both.any() or np.percentile(distance[both], 95) > limit)
    except Exception as exc:
        trajectory_qc['refinement_warning'] = True
        trajectory_qc['refinement_error'] = str(exc)[:300]

    if flowmap.shape != (len(x), len(y), 2):
        raise ValueError(f'Unexpected flowmap shape: {flowmap.shape}')
    # Eigen-derivatives at trajectory failures or land edges can form false ridges.
    # Derivatives at invalid trajectories are masked with a whole-stencil guard.
    # Replace invalid flowmap endpoints only for the numerical derivative kernel;
    # none can subsequently pass the erosion/validity mask.
    numerical_flowmap = np.where(trajectory_valid[..., None], flowmap, 0.0)
    if config_raw.get('spherical_metric', True):
        ftle, eigvec_max = metric_ftle_from_flowmap(numerical_flowmap, x, y, lat0, abs(T))
    else:
        from numbacs.diagnostics import C_eig_2D, ftle_from_eig
        eigvals, eigvecs = C_eig_2D(numerical_flowmap, dx, dy)
        eigvec_max = eigvecs[:, :, :, 1]
        ftle = ftle_from_eig(eigvals[:, :, 1], T)
    valid_stencil = binary_erosion(trajectory_valid, iterations=max(1, int(land_cfg.get('coast_guard_output_cells', 1))), border_value=0)
    ftle = np.where(valid_stencil & np.isfinite(ftle), ftle, np.nan)
    if not np.isfinite(ftle).any():
        raise ValueError('No valid offshore FTLE cells; AOI may be too small')
    # Normalized Gaussian smoothing prevents NaNs bleeding into valid water.
    sigma = float(config_raw['ridge_extraction'].get('smooth_sigma', 1))
    finite = np.isfinite(ftle)
    filled = np.where(finite, ftle, 0)
    denominator = gaussian_filter(finite.astype(float), sigma=sigma, mode='nearest')
    ftle_smooth = np.divide(gaussian_filter(filled, sigma=sigma, mode='nearest'), denominator,
                            out=np.full_like(ftle, np.nan), where=denominator > 1e-6)
    ftle_smooth[~valid_stencil] = np.nan

    ridge_cfg = config_raw["ridge_extraction"]
    sigma = float(ridge_cfg.get("smooth_sigma", 1.0))
    # ftle_smooth was calculated with normalized, water-only convolution above.
    dist_tol = float(ridge_cfg.get("dist_tol_grid_cells", 3.0)) * max(dx, dy)

    # Ridge extraction needs a rectangular finite field. Suppress results near
    # invalid-cell boundaries to avoid ridges introduced by numerical filling.
    ridge_guard = binary_erosion(valid_stencil, iterations=max(3, int(np.ceil(3*sigma))), border_value=0)
    ridge_finite = np.isfinite(ftle_smooth)
    ridge_ready = np.where(ridge_finite, ftle_smooth, float(np.nanmin(ftle_smooth)))
    # The extraction API computes its percentile over the full rectangle.
    # Compensate for invalid cells inserted at the minimum so the numeric
    # threshold corresponds to the configured percentile of valid ocean cells.
    ridge_percentile = float(ridge_cfg.get('percentile', 70))
    nfinite, nall = int(ridge_finite.sum()), int(ridge_finite.size)
    if 0 < nfinite < nall:
        ridge_percentile = 100.0 * ((nall-nfinite) + (ridge_percentile/100.0)*(nfinite-1)) / max(nall-1,1)
    ridge_curves_xy = ftle_ordered_ridges(
        ridge_ready,
        eigvec_max,
        x,
        y,
        dist_tol,
        percentile=float(ridge_percentile),
        sdd_thresh=float(ridge_cfg.get("sdd_thresh", 0.0)),
    )
    ridge_curves_xy = list(ridge_curves_xy) if ridge_curves_xy is not None else []
    # Break ridge lines where they meet land / invalid FTLE stencils.
    clean_ridges = []
    for ridge in ridge_curves_xy:
        coords = np.asarray(ridge, dtype=float)
        if len(coords) < 2:
            continue
        ix = np.rint((coords[:, 0]-x[0])/dx).astype(int)
        iy = np.rint((coords[:, 1]-y[0])/dy).astype(int)
        ok = (ix >= 0) & (ix < len(x)) & (iy >= 0) & (iy < len(y))
        keep = np.zeros(len(coords), dtype=bool)
        keep[ok] = ridge_guard[ix[ok], iy[ok]]
        # Split broken ridges instead of connecting opposite island shores.
        starts = np.flatnonzero(keep & ~np.r_[False, keep[:-1]])
        ends = np.flatnonzero(keep & ~np.r_[keep[1:], False])
        for a, b in zip(starts, ends):
            if b-a >= 1:
                clean_ridges.append(coords[a:b+1])
    ridge_curves_xy = clean_ridges

    lon_grid_1d, _ = lonlat_from_local_xy(x, np.zeros_like(x), lon0=lon0, lat0=lat0)
    _, lat_grid_1d = lonlat_from_local_xy(np.zeros_like(y), y, lon0=lon0, lat0=lat0)
    lon_grid, lat_grid = np.meshgrid(lon_grid_1d, lat_grid_1d, indexing="ij")
    x_grid, y_grid = np.meshgrid(x, y, indexing="ij")

    ridge_curves_lonlat: list[np.ndarray] = []
    for rc in ridge_curves_xy:
        rlon, rlat = lonlat_from_local_xy(rc[:, 0], rc[:, 1], lon0=lon0, lat0=lat0)
        ridge_curves_lonlat.append(np.column_stack([rlon, rlat]))

    mask = valid_stencil.copy()
    if aoi_info is not None:
        mask &= polygon_mask(lon_grid, lat_grid, aoi_info.polygons)
        ftle = np.where(mask, ftle, np.nan)
        ftle_smooth = np.where(mask, ftle_smooth, np.nan)
        # Exclude offshore ridge points outside the user-selected AOI.
        in_aoi_ridges = []
        for ridge in ridge_curves_lonlat:
            inside = polygon_mask(ridge[:, 0], ridge[:, 1], aoi_info.polygons).ravel()
            begins = np.flatnonzero(inside & ~np.r_[False, inside[:-1]])
            ends = np.flatnonzero(inside & ~np.r_[inside[1:], False])
            for k, m in zip(begins, ends):
                if m > k:
                    in_aoi_ridges.append(ridge[k:m+1])
        ridge_curves_lonlat = in_aoi_ridges

    ridge_support = compute_ridge_support(lon_grid, lat_grid, ridge_curves_lonlat, ftle_smooth)
    if mask is not None:
        ridge_support = np.where(mask, ridge_support, np.nan)

    hot_cfg = config_raw["hotspots"]
    field = np.array(ftle_smooth, copy=True)
    field[~np.isfinite(field)] = np.nan
    valid = np.isfinite(field)
    if not valid.any():
        raise ValueError("No valid FTLE cells inside AOI")
    threshold = np.nanpercentile(field, float(hot_cfg.get("percentile", 98.5)))
    peak_mask = valid & (field >= threshold)
    localmax = field == maximum_filter(field, size=int(hot_cfg.get("localmax_window", 7)), mode="nearest")
    inds = np.argwhere(peak_mask & localmax)
    candidates = []
    for i, j in inds:
        candidates.append(
            {
                "i": int(i),
                "j": int(j),
                "ftle": float(field[i, j]),
                "x_km": float(x_grid[i, j]),
                "y_km": float(y_grid[i, j]),
                "lon": float(lon_grid[i, j]),
                "lat": float(lat_grid[i, j]),
            }
        )
    candidates.sort(key=lambda d: d["ftle"], reverse=True)
    hotspots = _pick_well_separated_points(
        candidates,
        min_sep_px=int(hot_cfg.get("min_separation_px", 8)),
        top_n=int(hot_cfg.get("top_n", 5)),
    )
    for rank, hs in enumerate(hotspots, start=1):
        hs["rank"] = rank

    cl_cfg = config_raw["clusters"]
    cluster_thr = np.nanpercentile(field, float(cl_cfg.get("percentile", 94.0)))
    labels, n_labels = label(valid & (field >= cluster_thr))
    clusters = []
    cell_area_km2 = abs(dx * dy)
    for lab in range(1, n_labels + 1):
        mask_lab = labels == lab
        if not np.any(mask_lab):
            continue
        coords = np.argwhere(mask_lab)
        vals = field[mask_lab]
        peak_idx_local = int(np.nanargmax(vals))
        peak_ij = coords[peak_idx_local]
        pts_lon = lon_grid[mask_lab]
        pts_lat = lat_grid[mask_lab]
        polygon = _component_polygon(pts_lon, pts_lat)
        cluster = {
            "cluster_id": lab,
            "n_cells": int(mask_lab.sum()),
            "area_km2": float(mask_lab.sum() * cell_area_km2),
            "peak_ftle": float(vals[peak_idx_local]),
            "peak_lon": float(lon_grid[tuple(peak_ij)]),
            "peak_lat": float(lat_grid[tuple(peak_ij)]),
            "centroid_lon": float(np.nanmean(pts_lon)),
            "centroid_lat": float(np.nanmean(pts_lat)),
            "polygon_lonlat": polygon,
        }
        clusters.append(cluster)
    clusters.sort(key=lambda d: d["peak_ftle"], reverse=True)
    for rank, cl in enumerate(clusters, start=1):
        cl["rank"] = rank

    within_aoi = polygon_mask(lon_grid, lat_grid, aoi_info.polygons) if aoi_info else np.ones_like(mask, dtype=bool)
    valid_fraction = float(np.count_nonzero(np.isfinite(ftle) & within_aoi) / max(1, np.count_nonzero(within_aoi)))
    trajectory_qc['valid_trajectory_fraction_in_aoi'] = float(np.count_nonzero(trajectory_valid & within_aoi)/max(1,np.count_nonzero(within_aoi)))
    trajectory_qc['valid_trajectory_fraction_seed_rectangle'] = float(trajectory_valid.mean())
    trajectory_qc['ftle_unit'] = 'per_hour'
    trajectory_qc['numerical_assurance'] = 'sampled_step_refinement_not_full_validation'
    trajectory_qc['velocity_units_missing'] = velocity_units_missing
    trajectory_qc['quality_flag'] = 'review_required' if (bool(velocity_units_missing) or valid_fraction < float(config_raw.get('quality', {}).get('minimum_valid_ftle_fraction', 0.90)) or trajectory_qc.get('refinement_warning')) else 'numerical_screen_passed_unvalidated'
    target_iso = str(np.datetime_as_string(target_time, unit="s")) + "Z"
    # Current snapshot, resampled to the *actual* longitude/latitude FTLE grid.
    uu = fill_ocean_velocity(u[-1:, :, :], ocean_native)[0]
    vv = fill_ocean_velocity(v[-1:, :, :], ocean_native)[0]
    x_index = (x - x_native[0]) / (x_native[1] - x_native[0])
    y_index = (y - y_native[0]) / (y_native[1] - y_native[0])
    ix, iy = np.meshgrid(x_index, y_index, indexing='ij')
    curr_u = map_coordinates(uu, [ix, iy], order=1, mode='nearest') / scale
    curr_v = map_coordinates(vv, [ix, iy], order=1, mode='nearest') / scale
    curr_u = np.where(mask, curr_u, np.nan)
    curr_v = np.where(mask, curr_v, np.nan)
    curr_speed = np.hypot(curr_u, curr_v)
    return FTLEOutputs(
        ftle=ftle,
        ftle_smooth=ftle_smooth,
        ridge_curves_xy=ridge_curves_xy,
        ridge_curves_lonlat=ridge_curves_lonlat,
        ridge_support=ridge_support,
        hotspots=hotspots,
        clusters=clusters,
        lon_grid=lon_grid,
        lat_grid=lat_grid,
        x_grid=x_grid,
        y_grid=y_grid,
        target_time=target_iso,
        u_variable=u_var,
        v_variable=v_var,
        aoi_mask=mask,
        ocean_mask=mask,
        current_u=curr_u,
        current_v=curr_v,
        current_speed=curr_speed,
        metadata={
            'numerical_quality': {
                **trajectory_qc,
                'method': 'bounded_rk4_linear_space_time',
                'seed_grid_shape': [int(len(x)), int(len(y))],
                'velocity_grid_shape': [int(len(x_native)), int(len(y_native))],
                'valid_ftle_cells_total': int(np.isfinite(ftle).sum()),
                'requested_aoi_cells': int(within_aoi.sum()),
                'valid_ftle_fraction_in_aoi': valid_fraction,
                'seed_grid_policy': 'Seeds in AOI plus finite-difference margin; full buffered velocity domain retained.',
                'velocity_domain_lonlat': {'lon_min':float(lon.min()), 'lon_max':float(lon.max()), 'lat_min':float(lat.min()), 'lat_max':float(lat.max())},
                'model_data_is_observation': False,
                'ocean_model_depth_level': ds.attrs.get('selected_depth_level', 'not_provided'),
                'earth_geometry': 'regional_spherical_surface_metric' if config_raw.get('spherical_metric', True) else 'local_constant_scale',
                'caveat': 'Numerical screening is not scientific validation. Model resolution, interpolation and forecast uncertainty still limit results.'
            }
        },
    )
