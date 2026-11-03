import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from lcs_pipeline.land import coast_safe_flowmap
from lcs_pipeline.web_export import save_web_day, LAYERS
from scripts.validate_pages import validate

class NumericalAndWebTests(unittest.TestCase):
    def test_uniform_velocity_24_hours(self):
        t=np.arange(-24,1,1,dtype=float)
        axis=np.linspace(-100,100,41)
        u=np.ones((len(t),41,41),dtype=float)
        v=np.zeros_like(u)
        x=np.array([0,10,20],float);y=np.array([-20,0,20],float)
        f, valid, wet, q=coast_safe_flowmap(t,axis,axis,u,v,x,y,24,1,1,True)
        self.assertTrue(valid.all())
        self.assertTrue(np.allclose(f[...,0],x[:,None]-24,atol=1e-6))
        self.assertTrue(np.allclose(f[...,1],y[None,:],atol=1e-6))
        self.assertEqual(q['invalid_domain_exit'],0)

    def test_grid_boundary_stop(self):
        t=np.arange(-24,1,dtype=float)
        axis=np.linspace(-10,10,21)
        u=np.ones((len(t),21,21),dtype=float)*2
        v=np.zeros_like(u)
        with self.assertRaisesRegex(ValueError,'All particle trajectories are invalid'):
            coast_safe_flowmap(t,axis,axis,u,v,np.array([-8.,0.,8.]),np.array([0.,1.,2.]),24)

    def test_irregular_two_hour_sample_allowed(self):
        t=np.array([-24,-23,-22,-20,-19,-18,-17,-16,-15,-14,-13,-12,-11,-10,-9,-8,-7,-6,-5,-4,-3,-2,-1,0.],dtype=float)
        axis=np.linspace(-50,50,21)
        z=np.zeros((len(t),21,21))
        flow, valid, _ = coast_safe_flowmap(t,axis,axis,z,z,np.array([0,1]),np.array([0,1]),24)
        self.assertTrue(valid.all())

    def test_browser_payload_version_shape(self):
        x,y=np.meshgrid(np.arange(8),np.arange(7),indexing='ij')
        data=(x+y).astype(float)
        out=SimpleNamespace(ftle_smooth=data,lon_grid=x.astype(float),lat_grid=y.astype(float),
            metadata={'bbox':{'lon_min':0,'lon_max':7,'lat_min':0,'lat_max':6}},
            ridge_curves_lonlat=[],hotspots=[],clusters=[], ocean_mask=np.ones((8,7)))
        for name in LAYERS:
            if name!='ocean_mask': setattr(out,name,data)
        with tempfile.TemporaryDirectory() as td:
            path=save_web_day(out,td)
            meta=json.loads(path.read_text())
            self.assertEqual((Path(td)/'web_layers.f32').stat().st_size,8*7*len(LAYERS)*4)
            self.assertEqual(meta['shape'],[8,7])

if __name__=='__main__':unittest.main()
