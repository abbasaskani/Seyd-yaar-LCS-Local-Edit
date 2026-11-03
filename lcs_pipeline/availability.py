"""Dataset temporal coverage, conservative validation, and adaptive future retries."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np

from .copernicus_io import download_subset, parse_dataset_time_limit, normalize_dataset


def coverage_error(ds, target: datetime, backward_days: float, max_gap_hours: float = 3.0) -> str | None:
    times = ds['time'].values.astype('datetime64[ns]')
    if len(times) < 2:
        return 'fewer than two time samples'
    end = np.datetime64(target.replace(tzinfo=None), 'ns')
    start = end - np.timedelta64(int(backward_days * 24 * 3600), 's')
    selected = times[(times >= start) & (times <= end)]
    if not len(selected) or (selected[0] - start) > np.timedelta64(61, 'm'):
        return f'incomplete backward start: need {backward_days} full days'
    if (end - selected[-1]) > np.timedelta64(61, 'm'):
        return 'target time missing or more than one hour from last data sample'
    if len(selected) < 2 or max(np.diff(selected)) > np.timedelta64(int(max_gap_hours * 3600), 's'):
        return f'gaps exceeding {max_gap_hours:g} hours'
    return None


def download_adaptive(cfg: dict, bbox: dict, variables: list[str], earliest_utc: datetime,
                      today_local, tz, cache_dir: Path, u_var: str, v_var: str):
    """One shared subset with max feasible forecast, tolerating unavailable future dates.

    Retry with smaller future horizon if Copernicus rejects the time request.
    Fail explicitly if even historical data cannot be fetched.
    """
    from datetime import time
    from zoneinfo import ZoneInfo
    tzinfo = ZoneInfo(tz)
    target_hour = int(cfg['time_reference'].get('target_local_hour', 18))
    now_limit = datetime.now(timezone.utc) + timedelta(days=int(cfg.get('future_max_days', 10)) + 1)
    horizons = list(range(int(cfg.get('future_max_days', 10)), -1, -1))
    failures = []
    output = cache_dir / 'shared_subset.nc'
    cache_dir.mkdir(parents=True, exist_ok=True)
    for horizon in horizons:
        day = today_local.date() + timedelta(days=horizon)
        requested = datetime.combine(day, time(hour=target_hour), tzinfo=tzinfo).astimezone(timezone.utc)
        end = min(requested, now_limit)
        try:
            for stale in cache_dir.glob('shared_subset*.nc'):
                stale.unlink(missing_ok=True)
            path = download_subset(
                dataset_id=cfg['dataset_id'], bbox=bbox, variables=variables,
                start_utc=earliest_utc, end_utc=end,
                coordinates_selection_method=cfg.get('coordinates_selection_method', 'nearest'),
                output_path=output,
            )
            ds = normalize_dataset(path, u_var, v_var)
            if len(ds.time) < 2:
                raise ValueError('Less than two time values in returned subset')
            return ds, path, failures
        except Exception as exc:
            failures.append({'requested_future_days': horizon, 'error': str(exc)[:450]})
            print(f'Forecast horizon +{horizon} rejected: {exc}', flush=True)
    raise RuntimeError('No Copernicus time window could be downloaded. ' + str(failures[-3:]))
