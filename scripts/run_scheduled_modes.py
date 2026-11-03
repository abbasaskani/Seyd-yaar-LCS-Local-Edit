"""Runs a full rolling retrospective+forecast set from one Copernicus download."""
from __future__ import annotations

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import time
import csv
import os

from lcs_pipeline.availability import download_adaptive
from lcs_pipeline.config import load_config
from lcs_pipeline.copernicus_io import describe_dataset, resolve_requested_variables
from lcs_pipeline.timezones import select_preset
from scripts.run_pipeline import add_bbox_args, resolve_aoi, run_one


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', default='config/defaults.json')
    p.add_argument('--preset', default=None)
    p.add_argument('--aoi-file', default=None)
    p.add_argument('--mode', default='routine')
    add_bbox_args(p)
    args = p.parse_args()
    project = load_config(args.config)
    cfg = project.raw
    aoi = resolve_aoi(project, args)
    decision = select_preset(cfg, aoi[0].centroid_lon, aoi[0].centroid_lat, override_key=args.preset)
    from zoneinfo import ZoneInfo
    local_today = datetime.now(timezone.utc).astimezone(ZoneInfo(decision.preset.tz)).replace(hour=0, minute=0, second=0, microsecond=0)
    offsets = sorted(set(int(x) for x in cfg['run_horizons_days']))
    # Earliest FTLE needs data from (oldest target - backward_days).
    earliest = (local_today + timedelta(days=min(offsets), hours=int(cfg['time_reference']['target_local_hour']))
                - timedelta(days=float(cfg['backward_days']), hours=2)).astimezone(timezone.utc)
    meta = describe_dataset(cfg['dataset_id'])
    vars_pair = resolve_requested_variables(meta, cfg['u_variable_candidates'], cfg['v_variable_candidates'])
    max_available = None
    try:
        from lcs_pipeline.copernicus_io import parse_dataset_time_limit
        max_available = parse_dataset_time_limit(meta.get('time_max'))
    except (ValueError, TypeError, OverflowError):
        pass
    if max_available is not None:
        cfg['future_max_days'] = min(int(cfg['future_max_days']), max(0, (max_available.astimezone(ZoneInfo(decision.preset.tz)).date() - local_today.date()).days))
    pad = float(cfg.get('spatial_buffer_deg', 0))
    bbox_fetch = {
        'lon_min': max(-180., aoi[0].bbox['lon_min'] - pad),
        'lon_max': min(180., aoi[0].bbox['lon_max'] + pad),
        'lat_min': max(-80., aoi[0].bbox['lat_min'] - pad),
        'lat_max': min(90., aoi[0].bbox['lat_max'] + pad),
    }
    ds, cache_path, retries = download_adaptive(cfg, bbox_fetch, vars_pair, earliest, local_today,
                                              decision.preset.tz, project.outputs_dir/'_cache', *vars_pair)
    latest = project.outputs_dir/'latest'
    if latest.exists():
        shutil.rmtree(latest)
    latest.mkdir(parents=True, exist_ok=True)
    outcomes = []
    start_clock = time.monotonic()
    job_start = float(os.environ.get('SEYD_JOB_STARTED_EPOCH', time.time()))
    max_minutes = float(cfg.get('processing_time_budget_minutes', 290))
    run_durations = []
    for offset in offsets:
        # The max nominal request isn't always in the returned subset; evaluate per target.
        if offset > int(cfg.get('future_max_days', 10)):
            outcomes.append({'offset': offset, 'status': 'skipped', 'reason': 'beyond available product horizon'})
            continue
        elapsed = max((time.time()-job_start)/60, (time.monotonic()-start_clock)/60)
        estimated_next = max(run_durations[-5:]) if run_durations else 0
        if elapsed + estimated_next >= max_minutes:
            outcomes.append({'offset':offset, 'status':'skipped', 'reason':'processing time budget reached before next day'})
            continue
        day_clock = time.monotonic()
        args.offset_days = offset
        args.target_local_date = None
        args.target_local_datetime = None
        args.run_label = f"minus_{abs(offset)}" if offset < 0 else ('today' if offset == 0 else f'plus_{offset}')
        try:
            outcome = run_one(args, shared_ds=ds, vars_pair=vars_pair, aoi_override=aoi, project_override=project)
            outcome['offset'] = offset
            outcomes.append(outcome)
            run_durations.append((time.monotonic()-day_clock)/60)
        except Exception as exc:
            outcomes.append({'offset': offset, 'label': args.run_label, 'status': 'skipped', 'reason': str(exc)[:500]})
            print(f'SKIPPED {args.run_label}: {exc}', flush=True)
    report = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'requested_offsets': offsets, 'download_retries': retries,
        'actual_data_first': str(ds.time.values[0]), 'actual_data_last': str(ds.time.values[-1]),
        'outcomes': outcomes,
    }
    (latest/'run_report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    with (latest/'quality_report.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['day','status','quality_flag','valid_trajectory_fraction_in_aoi','valid_ftle_fraction_in_aoi','invalid_domain_exit','invalid_land_or_guard','invalid_nonfinite','refinement_valid_pairs','refinement_p95_displacement_km','refinement_max_displacement_km','refinement_tolerance_km','refinement_warning','spatial_step_limited','spherical_zonal_correction','maximum_input_time_gap_hours','reason'])
        writer.writeheader()
        for outcome in outcomes:
            q = outcome.get('quality') or {}
            writer.writerow({'day':outcome.get('label',outcome.get('offset')), 'status':outcome['status'],
                **{k:q.get(k) for k in ('quality_flag','valid_trajectory_fraction_in_aoi','valid_ftle_fraction_in_aoi','invalid_domain_exit','invalid_land_or_guard','invalid_nonfinite','refinement_valid_pairs','refinement_p95_displacement_km','refinement_max_displacement_km','refinement_tolerance_km','refinement_warning','spatial_step_limited','spherical_zonal_correction','maximum_input_time_gap_hours')},
                'reason':outcome.get('reason','')})
    try:
        ds.close()
    except Exception:
        pass
    if not any(item['status'] == 'success' for item in outcomes):
        raise RuntimeError('No daily outputs produced; see outputs/latest/run_report.json')
    import subprocess
    subprocess.run([__import__('sys').executable, 'scripts/build_pages.py', '--config', args.config], check=True)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
