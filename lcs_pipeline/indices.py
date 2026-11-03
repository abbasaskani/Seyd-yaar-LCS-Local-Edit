from __future__ import annotations

from datetime import datetime
import numpy as np

from .ftle import FTLEOutputs, robust_normalize


def centered_persistence(normalized_fields: list[np.ndarray], index: int, half_window: int,
                         calendar_days: list | None = None) -> np.ndarray:
    """Calendar-day-aware 3/5-day mean; never borrows a distant day across gaps."""
    if calendar_days is None:
        nearby = range(max(0,index-half_window),min(len(normalized_fields),index+half_window+1))
    else:
        nearby = [k for k,d in enumerate(calendar_days)
                  if abs((d-calendar_days[index]).days) <= half_window]
    if not nearby:
        return np.full_like(normalized_fields[index], np.nan)
    stack=np.stack([normalized_fields[k] for k in nearby],axis=0)
    count=np.isfinite(stack).sum(axis=0)
    return np.divide(np.nansum(stack,axis=0), count,
                     out=np.full_like(stack[0], np.nan), where=count>0)



def trailing_persistence(normalized_fields: list[np.ndarray], index: int, window_days: int,
                         calendar_days: list | None = None) -> np.ndarray:
    """Use the target day and its *past* window, never later target days.

    This avoids a temporal look-ahead in the derived persistence score. It
    does not make historical reanalysis equivalent to an archived forecast.
    """
    if calendar_days is None:
        nearby = range(max(0, index - window_days + 1), index + 1)
    else:
        nearby = [k for k in range(index + 1)
                  if 0 <= (calendar_days[index] - calendar_days[k]).days < window_days]
    if not nearby:
        return np.full_like(normalized_fields[index], np.nan)
    stack = np.stack([normalized_fields[k] for k in nearby], axis=0)
    count = np.isfinite(stack).sum(axis=0)
    return np.divide(np.nansum(stack, axis=0), count,
                     out=np.full_like(stack[0], np.nan), where=count > 0)


def normalize_comparable_days(fields: list[np.ndarray], q_low: float, q_high: float) -> tuple[list[np.ndarray], tuple[float, float]]:
    """One scale across all days in a run, rather than a different scale/day.

    Note that different executions still have different empirical scale limits.
    This creates an ordinal heuristic score, not a probability of fish presence.
    """
    finite = [np.asarray(f, dtype=float)[np.isfinite(f)] for f in fields]
    pooled = np.concatenate([arr for arr in finite if arr.size]) if any(a.size for a in finite) else np.array([])
    if not pooled.size:
        return [np.full_like(f, np.nan, dtype=float) for f in fields], (float('nan'), float('nan'))
    lo, hi = (float(v) for v in np.percentile(pooled, [q_low, q_high]))
    if not np.isfinite(hi) or hi <= lo:
        hi = lo + 1.0
    normalized = []
    for f in fields:
        array = np.asarray(f, dtype=float)
        normalized.append(np.where(np.isfinite(array), np.clip((array - lo) / (hi - lo), 0., 1.), np.nan))
    return normalized, (lo, hi)

def attach_persistence_and_scores(outputs: list[FTLEOutputs], config_raw: dict) -> list[FTLEOutputs]:
    if not outputs:
        return []
    q_low,q_high=config_raw['persistence'].get('robust_quantiles',[5,95])
    if config_raw.get('score_normalization', 'joint_run_robust') == 'joint_run_robust':
        ftle_norms, scale_limits = normalize_comparable_days([out.ftle_smooth for out in outputs], q_low, q_high)
    else:
        ftle_norms = [robust_normalize(out.ftle_smooth,q_low=q_low,q_high=q_high) for out in outputs]
        scale_limits = None
    dates=[]
    for out in outputs:
        meta=out.metadata or {}
        raw=meta.get('requested_target_date_local') or meta.get('actual_selected_local')
        dates.append(datetime.fromisoformat(raw[:10]).date() if raw else None)
    if any(d is None for d in dates):
        dates=None
    balanced_w=config_raw['composites']['balanced']
    physics_w=config_raw['composites']['physics_first']
    for i,out in enumerate(outputs):
        p3=trailing_persistence(ftle_norms,i,window_days=3,calendar_days=dates)
        p5=trailing_persistence(ftle_norms,i,window_days=5,calendar_days=dates)
        out.persistence_3d=p3;out.persistence_5d=p5
        ftle_norm=ftle_norms[i]
        ridge=np.clip(out.ridge_support,0,1)
        out.balanced_composite=np.clip(
            balanced_w['ftle']*ftle_norm+balanced_w['ridge_support']*ridge+balanced_w['persistence']*p5,0,1)
        out.physics_first_composite=np.clip(
            physics_w['ftle']*ftle_norm+physics_w['ridge_support']*ridge+physics_w['persistence']*p5,0,1)
        out.accumulation_potential_balanced=out.balanced_composite*100
        out.accumulation_potential_physics_first=out.physics_first_composite*100
        meta = dict(out.metadata or {})
        meta['relative_score_definition'] = {
            'status': 'uncalibrated_heuristic_NOT_probability',
            'normalization': config_raw.get('score_normalization', 'joint_run_robust'),
            'shared_within_run_scale': list(scale_limits) if scale_limits else None,
            'persistence_window': 'trailing_3d_and_5d_no_lookahead',
            'not_comparable_between_runs_without_fixed_reference_scale': True,
            'not_a_fish_presence_or_catch_probability': True,
        }
        out.metadata = meta
    return outputs
