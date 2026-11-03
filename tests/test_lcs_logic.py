"""Offline smoke tests — do NOT constitute real-Copernicus scientific validation."""
import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import numpy as np
import xarray as xr

from lcs_pipeline.land import coast_safe_flowmap
from lcs_pipeline.availability import coverage_error
from lcs_pipeline.config import load_config
from lcs_pipeline.indices import centered_persistence
from scripts.run_pipeline import resolve_aoi


class LCSSmoke(unittest.TestCase):
    def test_land_barrier(self):
        ts=np.arange(-24,1,dtype=float)
        xy=np.linspace(0,100,24)
        u=np.ones((len(ts),len(xy),len(xy)))*2.0
        v=np.zeros_like(u)
        u[:,:,12]=np.nan
        v[:,:,12]=np.nan
        _,valid,_=coast_safe_flowmap(ts,xy,xy,u,v,xy,xy,backward_hours=24)
        self.assertFalse(valid[:,11:14].any())
        self.assertTrue(valid.any())

    def test_coverage(self):
        now=datetime(2026,11,2,18,tzinfo=timezone.utc)
        time=np.arange(np.datetime64('2026-10-26T18'),np.datetime64('2026-11-02T19'),np.timedelta64(1,'h'))
        ds=xr.Dataset(coords={'time':time})
        self.assertIsNone(coverage_error(ds,now,7))
        self.assertIsNotNone(coverage_error(ds.isel(time=slice(10,None)),now,7))

    def test_manual_bounds(self):
        cfg=load_config('config/defaults.json')
        a=SimpleNamespace(lon_min=59.0,lon_max=60.0,lat_min=18.0,lat_max=19.0,aoi_file=None)
        geo,origin=resolve_aoi(cfg,a)
        self.assertEqual(origin,'manual_bbox')
        self.assertEqual(geo.bbox['lon_min'],59.0)
        self.assertEqual(len(cfg.raw['run_horizons_days']),25)

    def test_calendar_persistence(self):
        arr=[np.ones((2,2))*k for k in (1,2,3)]
        days=[datetime(2026,10,1).date(),datetime(2026,10,2).date(),datetime(2026,10,8).date()]
        near=centered_persistence(arr,1,1,days)
        self.assertTrue(np.allclose(near,1.5))


if __name__=='__main__':
    unittest.main()
