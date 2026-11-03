from __future__ import annotations

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))

import argparse
import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from lcs_pipeline.availability import coverage_error
from lcs_pipeline.config import load_config
from lcs_pipeline.coords import aoi_from_geojson, bbox_info
from lcs_pipeline.copernicus_io import describe_dataset, download_subset, normalize_dataset, resolve_requested_variables
from lcs_pipeline.ftle import compute_attracting_ftle
from lcs_pipeline.outputs import (
    plot_field_map, save_clusters_geojson, save_field_layers_json, save_ftle_netcdf,
    save_hotspots_csv, save_hotspots_geojson, save_ridges_geojson, save_summary_json,
)
from lcs_pipeline.timezones import build_target_windows, choose_actual_time, select_preset


def add_bbox_args(parser):
    for name in ('lon_min', 'lon_max', 'lat_min', 'lat_max'):
        parser.add_argument('--' + name.replace('_', '-'), type=float, default=None)
    return parser


def parse_args():
    p = argparse.ArgumentParser(description='Seyd Yar FTLE daily run')
    p.add_argument('--config', default='config/defaults.json')
    p.add_argument('--offset-days', type=int, default=0)
    p.add_argument('--run-label')
    p.add_argument('--preset')
    p.add_argument('--aoi-file')
    p.add_argument('--mode', default='routine')
    p.add_argument('--target-local-date')
    p.add_argument('--target-local-datetime')
    p.add_argument('--subset-file', help='Reuse a shared downloaded NetCDF subset')
    return add_bbox_args(p).parse_args()


def resolve_aoi(project, args):
    fields = ('lon_min', 'lon_max', 'lat_min', 'lat_max')
    entered = [getattr(args, k, None) for k in fields]
    if any(v is not None for v in entered):
        if not all(v is not None for v in entered):
            raise ValueError('Provide all four min/max coordinates together')
        bbox = dict(zip(fields, entered))
        if not (-180 <= bbox['lon_min'] < bbox['lon_max'] <= 180 and
                -90 <= bbox['lat_min'] < bbox['lat_max'] <= 90):
            raise ValueError(f'Invalid bbox {bbox}')
        return bbox_info(bbox), 'manual_bbox'
    path = project.resolve_path(args.aoi_file) if getattr(args, 'aoi_file', None) else project.aoi_path
    return aoi_from_geojson(path), str(path)


def parse_local_target(args, tz_name):
    tz = ZoneInfo(tz_name)
    today = datetime.now(timezone.utc).astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    if args.target_local_datetime:
        dt = datetime.fromisoformat(args.target_local_datetime)
        return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)
    if args.target_local_date:
        d = date.fromisoformat(args.target_local_date)
        return datetime(d.year, d.month, d.day, tzinfo=tz)
    return today + timedelta(days=int(args.offset_days))


def run_one(args, shared_ds=None, vars_pair=None, aoi_override=None, project_override=None):
    project = project_override or load_config(args.config)
    cfg = project.raw
    project.outputs_dir.mkdir(parents=True, exist_ok=True)
    aoi_info, aoi_source = aoi_override or resolve_aoi(project, args)
    tz_decision = select_preset(cfg, aoi_info.centroid_lon, aoi_info.centroid_lat, override_key=args.preset)
    tz_name = tz_decision.preset.tz
    target_local = parse_local_target(args, tz_name)
    target_date = target_local.replace(hour=0, minute=0, second=0, microsecond=0)
    nominal_local, windows_utc, _ = build_target_windows(cfg, target_date, tz_name)
    requested_start = windows_utc[0][0] - timedelta(days=float(cfg.get('backward_days', 7))) - timedelta(hours=1)
    requested_end = windows_utc[0][0] + timedelta(hours=1)
    if vars_pair is None:
        meta = describe_dataset(cfg['dataset_id'])
        vars_pair = resolve_requested_variables(meta, cfg['u_variable_candidates'], cfg['v_variable_candidates'])
    u_var, v_var = vars_pair
    label = args.run_label or f"day_{args.offset_days:+d}".replace('+', 'plus').replace('-', 'minus')
    staging = project.outputs_dir / '_staging' / (label + '_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
    staging.mkdir(parents=True, exist_ok=True)
    try:
        if shared_ds is not None:
            ds = shared_ds
        else:
            if args.subset_file:
                path = Path(args.subset_file)
            else:
                pad = float(cfg.get('spatial_buffer_deg', 0))
                fetch_bbox = {'lon_min': max(-180.,aoi_info.bbox['lon_min']-pad),
                              'lon_max': min(180.,aoi_info.bbox['lon_max']+pad),
                              'lat_min': max(-80.,aoi_info.bbox['lat_min']-pad),
                              'lat_max': min(90.,aoi_info.bbox['lat_max']+pad)}
                path = download_subset(cfg['dataset_id'], fetch_bbox, [u_var, v_var], requested_start,
                                       requested_end, cfg.get('coordinates_selection_method', 'nearest'), staging / 'subset_raw.nc')
            ds = normalize_dataset(path, u_var, v_var)
        candidates = [datetime.fromisoformat(np.datetime_as_string(t, unit='s')).replace(tzinfo=timezone.utc)
                      for t in ds['time'].values]
        # Fallback only within the requested local calendar day; never mislabel tomorrow as today.
        selected_windows = windows_utc[:2]
        selection = choose_actual_time(candidates, selected_windows, tz_decision.preset,
                                       tz_decision.auto_selected, nominal_local)
        gap = coverage_error(ds, selection.actual_utc, float(cfg['backward_days']),
                             float(cfg.get('land_handling', {}).get('max_time_gap_hours', 3)))
        if gap:
            raise ValueError(f'Data coverage incomplete for {label}: {gap}')
        chosen = np.datetime64(selection.actual_utc.replace(tzinfo=None))
        start = chosen - np.timedelta64(int(float(cfg['backward_days'])*86400), 's') - np.timedelta64(1, 'h')
        ds_run = ds.sel(time=(ds['time'] >= start) & (ds['time'] <= chosen))
        result = compute_attracting_ftle(ds_run, u_var, v_var, cfg, aoi_info)
        quality_metadata = dict(result.metadata or {})
        result.metadata = {
            **quality_metadata,
            'run_label': label, 'mode': args.mode,
            'aoi_source': aoi_source, 'bbox': aoi_info.bbox,
            'timezone_preset_key': tz_decision.preset.key,
            'timezone_preset_label': tz_decision.preset.label,
            'timezone_name': tz_name, 'timezone_auto_selected': tz_decision.auto_selected,
            'nominal_local_target': nominal_local.isoformat(),
            'actual_selected_utc': selection.actual_utc.isoformat(),
            'actual_selected_local': selection.actual_local.isoformat(),
            'fallback_status': selection.fallback_status,
            'requested_target_date_local': selection.requested_target_date_local,
            'backward_days': cfg['backward_days'],
            'data_coverage_start_utc': str(np.datetime_as_string(ds_run.time.values[0], unit='s'))+'Z',
            'data_coverage_end_utc': str(np.datetime_as_string(ds_run.time.values[-1], unit='s'))+'Z',
            'data_kind': 'historical_or_analysis' if selection.actual_utc <= datetime.now(timezone.utc) else 'forecast',
            'land_handling': cfg.get('land_handling', {}),
        }
        save_ftle_netcdf(result, staging/'ftle.nc')
        save_hotspots_csv(result, staging/'hotspots.csv')
        save_hotspots_geojson(result, staging/'hotspots.geojson')
        save_clusters_geojson(result, staging/'clusters.geojson')
        save_ridges_geojson(result, staging/'ridges.geojson')
        if cfg.get('save_large_field_json', False):
            save_field_layers_json(result, staging/'field_layers.json')
        if cfg.get('save_daily_static_ftle_png', False):
            plot_field_map(result, staging/'map_ftle.png', f"FTLE | {selection.actual_local.isoformat()}", 'ftle_smooth', 'FTLE')
        save_summary_json(result, staging/'summary.json')
        latest = project.outputs_dir/'latest'/label
        if latest.exists():
            shutil.rmtree(latest)
        shutil.copytree(staging, latest)
        # Avoid copying the shared NetCDF cache into every result.
        (latest/'subset_raw.nc').unlink(missing_ok=True)
        if cfg.get('keep_archive_in_repo', 0):
            archive = project.archive_dir / (selection.actual_utc.strftime('%Y%m%dT%H%M%SZ')+'__'+label)
            if archive.exists():
                shutil.rmtree(archive)
            archive.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(latest, archive)
        print(json.dumps({'status': 'success', 'name': label, 'target': selection.actual_utc.isoformat(), 'quality': result.metadata.get('numerical_quality')}, allow_nan=False), flush=True)
        return {'status': 'success', 'label': label, 'actual_utc': selection.actual_utc.isoformat(), 'quality': result.metadata.get('numerical_quality')}
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main():
    result = run_one(parse_args())
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
