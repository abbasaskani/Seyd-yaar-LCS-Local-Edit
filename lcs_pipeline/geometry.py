"""Regional spherical metric for 2-D FTLE from longitude/latitude grids.

The seeding grid uses equirectangular reference coordinates (x,y) in km:
  x = R*cos(lat0)*(lon-lon0), y = R*(lat-lat0)  [radians].
The local EN physical metric is diag(cos(lat)/cos(lat0), 1) in this
reference system. C is built in the physical tangent-plane metric, not
from raw longitude/latitude degree separation.

This is a *regional surface* approximation, not a 3-D geodesic or ocean
forecast validation. It assumes the supplied u/v are physical east/north
velocity components on a locally spherical Earth.
"""
from __future__ import annotations

import numpy as np
from .coords import EARTH_RADIUS_KM


def lat_from_reference_y(y_km, reference_lat_deg: float):
    return reference_lat_deg + np.rad2deg(np.asarray(y_km, dtype=float) / EARTH_RADIUS_KM)


def zonal_projection_factor(y_km, reference_lat_deg: float):
    """dx_reference/dt = u_east * cos(lat0)/cos(lat), in km/h."""
    local_lat = lat_from_reference_y(y_km, reference_lat_deg)
    cos_current = np.cos(np.deg2rad(local_lat))
    if np.any(np.abs(cos_current) < 1e-5):
        raise ValueError('Spherical zonal correction is singular near the poles')
    return np.cos(np.deg2rad(reference_lat_deg)) / cos_current


def metric_ftle_from_flowmap(flowmap: np.ndarray, x_axis, y_axis,
                             reference_lat_deg: float, backward_hours: float):
    """FTLE and principal direction using initial/final orthonormal EN metrics.

    dF_physical = A(final_lat) @ dF_reference @ inv(A(seed_lat)) where
    A(lat) = diag(cos(lat)/cos(lat0), 1). Eigenvectors are transformed
    back to reference x/y components for the ridge extraction tool.
    """
    x_axis = np.asarray(x_axis, dtype=float)
    y_axis = np.asarray(y_axis, dtype=float)
    f = np.asarray(flowmap, dtype=float)
    if f.shape != (len(x_axis), len(y_axis), 2):
        raise ValueError('Flowmap / seed axes shape mismatch')
    if backward_hours <= 0:
        raise ValueError('The integration horizon must be positive')
    if np.any(np.diff(x_axis) <= 0) or np.any(np.diff(y_axis) <= 0):
        raise ValueError('Seed grid must have ascending axes')
    dxfx, dyfx = np.gradient(f[..., 0], x_axis, y_axis, edge_order=2)
    dxfy, dyfy = np.gradient(f[..., 1], x_axis, y_axis, edge_order=2)
    g_initial = np.cos(np.deg2rad(lat_from_reference_y(y_axis[None, :], reference_lat_deg))) / np.cos(np.deg2rad(reference_lat_deg))
    g_final = np.cos(np.deg2rad(lat_from_reference_y(f[..., 1], reference_lat_deg))) / np.cos(np.deg2rad(reference_lat_deg))
    if np.any(g_initial <= 0) or np.any(g_final <= 0):
        raise ValueError('Regional metric not valid across the poles')
    a = (g_final / g_initial) * dxfx
    b = g_final * dyfx
    c = (1. / g_initial) * dxfy
    d = dyfy
    c11, c12, c22 = a*a+c*c, a*b+c*d, b*b+d*d
    cauchy = np.empty(f.shape[:2]+(2,2), dtype=float)
    cauchy[...,0,0] = c11
    cauchy[...,0,1] = cauchy[...,1,0] = c12
    cauchy[...,1,1] = c22
    eigvals, eigvecs = np.linalg.eigh(cauchy)
    largest = eigvals[...,1]
    ftle = np.where(largest>0, 0.5*np.log(np.maximum(largest,1e-300))/backward_hours, np.nan)
    # Ridge extractor works on x_reference/y_reference axes. Return the
    # principal (most stretched) direction expressed in those coordinates.
    v = eigvecs[..., :, 1].copy()
    v[...,0] /= g_initial
    norm = np.linalg.norm(v, axis=-1, keepdims=True)
    v = np.divide(v, norm, out=np.zeros_like(v), where=norm>0)
    return ftle, v
