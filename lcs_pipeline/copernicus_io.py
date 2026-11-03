from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import xarray as xr

def _coord_limits(parts) -> tuple[Any, Any]:
    time_min = None; time_max = None
    for part in parts:
        try: coords = part.get_coordinates()
        except Exception: coords = []
        for coord in coords:
            sid = getattr(coord, 'coordinate_id', '') or getattr(coord, 'name', '') or getattr(coord, 'standard_name', '')
            if sid in {'time', 'valid_time'}:
                time_min = getattr(coord, 'minimum_value', time_min)
                time_max = getattr(coord, 'maximum_value', time_max)
    return time_min, time_max

def describe_dataset(dataset_id: str) -> dict[str, Any]:
    import copernicusmarine
    cat = copernicusmarine.describe(dataset_id=dataset_id, disable_progress_bar=True)
    found = [(prod, item) for prod in cat.products for item in prod.datasets
             if item.dataset_id == dataset_id]
    if not found:
        raise KeyError(f'Dataset {dataset_id!r} not found in Copernicus catalogue')
    prod, ds = found[0]
    version = ds.versions[0]; part = version.parts[0]
    time_min, time_max = _coord_limits(version.parts)
    variables = []
    try:
        for var in part.services[0].variables:
            variables.append({'short_name': getattr(var, 'short_name', None), 'standard_name': getattr(var, 'standard_name', None), 'units': getattr(var, 'units', None)})
    except Exception:
        pass
    return {'dataset_id': ds.dataset_id, 'dataset_name': ds.dataset_name, 'product_id': prod.product_id, 'part_name': getattr(part, 'name', None), 'time_min': time_min, 'time_max': time_max, 'variables': variables}

def parse_dataset_time_limit(value: Any) -> datetime | None:
    if value in (None, '', 'None'): return None
    if isinstance(value, datetime): return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        x = float(value)
        if x > 1e16: x /= 1e9
        elif x > 1e12: x /= 1e3
        return datetime.fromtimestamp(x, tz=timezone.utc)
    if isinstance(value, str): return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
    return None

def resolve_requested_variables(ds_meta: dict[str, Any], u_candidates: list[str], v_candidates: list[str]) -> list[str]:
    """Select u/v as a *paired* velocity product; never mix uo with vtotal."""
    if len(u_candidates) != len(v_candidates):
        raise ValueError('East and north velocity candidates must form matched pairs')
    short_names = set()
    standard_to_short = {}
    for item in ds_meta.get('variables', []) or []:
        short, std = item.get('short_name'), item.get('standard_name')
        if short:
            short_names.add(short)
        if std and short:
            standard_to_short[std] = short
    def resolved(name):
        if name in short_names:
            return name
        return standard_to_short.get(name)
    for uc, vc in zip(u_candidates, v_candidates):
        u, v = resolved(uc), resolved(vc)
        if u and v:
            return [u, v]
    raise KeyError(f'No consistent velocity vector pair found in catalogue: {sorted(short_names)}')


def estimate_subset(dataset_id: str, bbox: dict[str, float], variables: list[str], start_utc: datetime, end_utc: datetime, coordinates_selection_method: str = 'nearest') -> dict[str, Any]:
    import copernicusmarine
    response = copernicusmarine.subset(dataset_id=dataset_id, variables=variables, minimum_longitude=float(bbox['lon_min']), maximum_longitude=float(bbox['lon_max']), minimum_latitude=float(bbox['lat_min']), maximum_latitude=float(bbox['lat_max']), start_datetime=start_utc, end_datetime=end_utc, coordinates_selection_method=coordinates_selection_method, dry_run=True)
    return {'repr': repr(response), 'start_utc': start_utc.isoformat(), 'end_utc': end_utc.isoformat(), 'bbox': bbox, 'variables': variables}

def download_subset(dataset_id: str, bbox: dict[str, float], variables: list[str], start_utc: datetime, end_utc: datetime, coordinates_selection_method: str, output_path: str | Path) -> Path:
    import copernicusmarine
    output_path = Path(output_path); output_path.parent.mkdir(parents=True, exist_ok=True)
    copernicusmarine.subset(dataset_id=dataset_id, variables=variables, minimum_longitude=float(bbox['lon_min']), maximum_longitude=float(bbox['lon_max']), minimum_latitude=float(bbox['lat_min']), maximum_latitude=float(bbox['lat_max']), start_datetime=start_utc, end_datetime=end_utc, coordinates_selection_method=coordinates_selection_method, output_filename=output_path.name, output_directory=str(output_path.parent))
    if output_path.exists(): return output_path
    matches = sorted(output_path.parent.glob(f'{output_path.stem}*.nc'))
    if not matches: raise FileNotFoundError(f'Subset download finished but file was not found near {output_path}')
    return matches[0]

def normalize_dataset(ds_path: str | Path, u_var: str, v_var: str) -> xr.Dataset:
    ds = xr.open_dataset(ds_path)
    rename_map = {}
    if 'longitude' not in ds.coords and 'lon' in ds.coords: rename_map['lon'] = 'longitude'
    if 'latitude' not in ds.coords and 'lat' in ds.coords: rename_map['lat'] = 'latitude'
    if rename_map: ds = ds.rename(rename_map)
    if 'time' not in ds.coords: raise KeyError("Normalized subset dataset has no 'time' coordinate")
    for var in (u_var, v_var):
        if var not in ds: raise KeyError(f'Required velocity variable {var!r} is missing from subset dataset')
    ds = ds.sortby(['time', 'latitude', 'longitude'])
    for name in ('depth', 'elevation', 'lev'):
        if name in ds.dims:
            if name in ds.coords:
                value = ds[name].values[0]
                try:
                    ds.attrs['selected_depth_level'] = float(value)
                except (TypeError, ValueError):
                    ds.attrs['selected_depth_level'] = str(value)
            ds = ds.isel({name: 0}, drop=True)
    for name in (u_var, v_var):
        if set(ds[name].dims) != {'time', 'latitude', 'longitude'}:
            raise ValueError(f'Unsupported {name} dimensions: {ds[name].dims}')
        ds[name] = ds[name].transpose('time', 'latitude', 'longitude')
    if ds.sizes.get('longitude', 0) < 3 or ds.sizes.get('latitude', 0) < 3:
        raise ValueError('AOI has fewer than 3 Copernicus cells in a dimension')
    return ds
