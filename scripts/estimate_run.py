"""Dry-run subset estimate for the complete -21-to-adaptive-future window."""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from lcs_pipeline.config import load_config
from lcs_pipeline.copernicus_io import describe_dataset, estimate_subset, parse_dataset_time_limit, resolve_requested_variables
from lcs_pipeline.timezones import select_preset
from scripts.run_pipeline import add_bbox_args, resolve_aoi


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--config',default='config/defaults.json')
    p.add_argument('--preset',default=None)
    p.add_argument('--aoi-file',default=None)
    args=add_bbox_args(p).parse_args()
    project=load_config(args.config);cfg=project.raw
    aoi,source=resolve_aoi(project,args)
    tz=select_preset(cfg,aoi.centroid_lon,aoi.centroid_lat,override_key=args.preset).preset
    local_today=datetime.now(timezone.utc).astimezone(ZoneInfo(tz.tz)).replace(hour=0,minute=0,second=0,microsecond=0)
    hh=int(cfg['time_reference']['target_local_hour'])
    start=(local_today+timedelta(days=-14,hours=hh)-timedelta(days=cfg['backward_days'],hours=2)).astimezone(timezone.utc)
    dsmeta=describe_dataset(cfg['dataset_id'])
    u,v=resolve_requested_variables(dsmeta,cfg['u_variable_candidates'],cfg['v_variable_candidates'])
    upper=parse_dataset_time_limit(dsmeta.get('time_max'))
    pad=float(cfg.get('spatial_buffer_deg',0))
    bb={'lon_min':max(-180.,aoi.bbox['lon_min']-pad),'lon_max':min(180.,aoi.bbox['lon_max']+pad),
        'lat_min':max(-80.,aoi.bbox['lat_min']-pad),'lat_max':min(90.,aoi.bbox['lat_max']+pad)}
    errors=[]
    estimate=None
    for future in range(int(cfg.get('future_max_days',10)),-1,-1):
        end=(local_today+timedelta(days=future,hours=hh)).astimezone(timezone.utc)
        if upper and end>upper:continue
        try:
            estimate=estimate_subset(cfg['dataset_id'],bb,[u,v],start,end,cfg.get('coordinates_selection_method','nearest'))
            estimate['horizon_days_estimated']=future
            break
        except Exception as e:
            errors.append({'horizon':future,'reason':str(e)[:300]})
    if estimate is None:
        raise RuntimeError(f'Unable to estimate a valid window: {errors[-3:]}')
    estimate.update({'aoi':aoi.bbox,'download_with_buffer':bb,'aoi_source':source,
                     'timezone_preset':tz.__dict__,'estimation_failures':errors,
                     'important':'Dry-run size estimate. Actual forecast horizon varies with current published time samples.'})
    out=project.outputs_dir/'estimate_report.json';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(estimate,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
    print(json.dumps(estimate,indent=2,ensure_ascii=False,default=str))


if __name__=='__main__':main()
