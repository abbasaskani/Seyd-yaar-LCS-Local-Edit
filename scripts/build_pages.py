from __future__ import annotations

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import xarray as xr

from lcs_pipeline.config import load_config
from lcs_pipeline.ftle import FTLEOutputs
from lcs_pipeline.indices import attach_persistence_and_scores
from lcs_pipeline.outputs import plot_field_map, save_summary_json
from lcs_pipeline.video import build_sequence_video
from lcs_pipeline.web_export import save_web_day


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config/defaults.json")
    return p.parse_args()


def load_output_from_nc(run_dir: Path) -> FTLEOutputs:
    # Eagerly materialize the source arrays before rewriting this same NetCDF.
    # Otherwise the NetCDF4/HDF5 read handle can block reopening the file for
    # writing in save_ftle_netcdf() (PermissionError / HDF5 file locking).
    ds = xr.open_dataset(run_dir / "ftle.nc")
    try:
        ds.load()
    finally:
        ds.close()
    meta = json.loads((run_dir / "summary.json").read_text(encoding="utf-8")).get("metadata", {}) if (run_dir / "summary.json").exists() else {}
    ridge_geo = json.loads((run_dir / "ridges.geojson").read_text(encoding="utf-8")) if (run_dir / "ridges.geojson").exists() else {"features": []}
    ridges = [np.asarray(f["geometry"]["coordinates"], dtype=float) for f in ridge_geo.get("features", [])]
    hotspots = json.loads((run_dir / "hotspots.geojson").read_text(encoding="utf-8")) if (run_dir / "hotspots.geojson").exists() else {"features": []}
    hot_rows = []
    for feat in hotspots.get("features", []):
        row = dict(feat.get("properties", {}))
        row["lon"], row["lat"] = feat["geometry"]["coordinates"]
        hot_rows.append(row)
    clusters_geo = json.loads((run_dir / "clusters.geojson").read_text(encoding="utf-8")) if (run_dir / "clusters.geojson").exists() else {"features": []}
    cl_rows = []
    for feat in clusters_geo.get("features", []):
        row = dict(feat.get("properties", {}))
        row["polygon_lonlat"] = feat["geometry"]["coordinates"][0]
        cl_rows.append(row)
    x_grid, y_grid = np.meshgrid(ds["x"].values, ds["y"].values, indexing="ij")
    out = FTLEOutputs(
        ftle=ds["ftle"].values,
        ftle_smooth=ds["ftle_smooth"].values,
        ridge_support=ds["ridge_support"].values,
        ridge_curves_xy=[],
        ridge_curves_lonlat=ridges,
        hotspots=hot_rows,
        clusters=cl_rows,
        lon_grid=ds["lon"].values,
        lat_grid=ds["lat"].values,
        x_grid=x_grid,
        y_grid=y_grid,
        target_time=str(ds.attrs.get("target_time", "")),
        u_variable=str(ds.attrs.get("u_variable", "uo")),
        v_variable=str(ds.attrs.get("v_variable", "vo")),
        metadata=meta,
        aoi_mask=np.isfinite(ds['ftle'].values),
        ocean_mask=np.isfinite(ds['ftle'].values),
        current_u=ds['current_u'].values if 'current_u' in ds else None,
        current_v=ds['current_v'].values if 'current_v' in ds else None,
        current_speed=ds['current_speed'].values if 'current_speed' in ds else None,
    )
    return out


def render_dashboard(manifest: dict, target: Path) -> None:
    template = Path(__file__).resolve().parents[1] / 'docs' / 'lcs_template.html'
    target.write_text(template.read_text(encoding='utf-8'), encoding='utf-8')


def main() -> None:
    args = parse_args()
    project = load_config(args.config)
    latest_root = project.outputs_dir / 'latest'
    pages_root = project.pages_dir
    pages_root.mkdir(parents=True, exist_ok=True)
    runs_root = pages_root / 'runs'
    if runs_root.exists(): shutil.rmtree(runs_root)
    runs_root.mkdir(parents=True, exist_ok=True)
    run_dirs = [p for p in latest_root.iterdir() if p.is_dir() and (p / 'ftle.nc').exists()]
    def run_time(path):
        try:
            payload = json.loads((path / 'summary.json').read_text(encoding='utf-8'))
            return payload.get('metadata', {}).get('actual_selected_utc', '')
        except (ValueError, OSError):
            return ''
    run_dirs.sort(key=run_time)
    outs = [load_output_from_nc(p) for p in run_dirs]
    if not outs:
        raise RuntimeError('There are no successful daily outputs to publish')
    outs = attach_persistence_and_scores(outs, project.raw)
    video_frames = []
    manifest_runs = []
    # Publish a light interactive dashboard. Never mirror the entire scientific
    # output tree into GitHub Pages; raw NetCDF remains in Actions artifacts.
    for run_dir, out in zip(run_dirs, outs):
        target_run_dir = runs_root / run_dir.name
        target_run_dir.mkdir(parents=True, exist_ok=True)
        save_web_day(out, target_run_dir)
        for filename in ('ridges.geojson', 'hotspots.geojson', 'clusters.geojson', 'hotspots.csv'):
            source = run_dir / filename
            if source.exists():
                shutil.copy2(source, target_run_dir / filename)
        # Save the full postprocessed numeric arrays to the downloadable run
        # NetCDF. Unlike the browser Float32 raster, this stays double precision.
        if project.raw.get('save_postprocessed_netcdf', True):
            from lcs_pipeline.outputs import save_ftle_netcdf
            save_ftle_netcdf(out, run_dir / 'ftle.nc')
        save_summary_json(out, run_dir / 'summary.json')
        shutil.copy2(run_dir / 'summary.json', target_run_dir / 'summary.json')
        # One image per day supplies the sequence video, not seven redundant maps.
        if project.raw.get('media', {}).get('create_mp4', True):
            frame = run_dir / 'map_potential_physics_first.png'
            plot_field_map(out, frame, f'Potential | {run_dir.name}', 'accumulation_potential_physics_first', '0..100')
            video_frames.append(frame)
        summary = json.loads((run_dir / 'summary.json').read_text(encoding='utf-8'))
        manifest_runs.append({'name': run_dir.name, 'summary': summary})
    video_rel = None
    if video_frames and project.raw.get('media', {}).get('create_mp4', True):
        video_path = pages_root / 'sequence.mp4'
        try:
            build_sequence_video(video_frames, video_path, fps=int(project.raw.get('media', {}).get('fps', 2)))
            video_rel = 'sequence.mp4'
        except Exception as exc:
            print(f'MP4 encoding skipped: {exc}', flush=True)
    if (latest_root / 'quality_report.csv').exists():
        shutil.copy2(latest_root / 'quality_report.csv', pages_root / 'quality_report.csv')
    report_path = latest_root / 'run_report.json'
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else None
    manifest = {'runs': manifest_runs, 'sequence_video': video_rel, 'report': report}
    shutil.copy2(Path(__file__).resolve().parents[1] / 'docs' / 'lcs_app.js', pages_root / 'lcs_app.js')
    shutil.copy2(Path(__file__).resolve().parents[1] / 'docs' / 'lcs_ui.css', pages_root / 'lcs_ui.css')
    (pages_root / '.nojekyll').touch()
    (pages_root / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    render_dashboard(manifest, pages_root / 'index.html')


if __name__ == '__main__':
    main()
