"""Synthetic numerical checks, not a substitute for real-Copernicus validation."""
import unittest
from datetime import date, timedelta
import numpy as np
from lcs_pipeline.geometry import metric_ftle_from_flowmap, zonal_projection_factor
from lcs_pipeline.land import coast_safe_flowmap
from lcs_pipeline.indices import normalize_comparable_days, trailing_persistence


class PhysicsChecks(unittest.TestCase):
    def test_identity_flow_spherical_metric_zero_ftle(self):
        x = np.linspace(-50., 50., 21)
        y = np.linspace(-80., 80., 21)
        gx, gy = np.meshgrid(x, y, indexing='ij')
        f = np.stack((gx,gy),axis=-1)
        ftle, principal=metric_ftle_from_flowmap(f,x,y,30.,168.)
        self.assertLess(np.nanmax(abs(ftle)),1e-11)
        self.assertTrue(np.isfinite(principal).all())

    def test_shear_flow_known_metric_ftle_at_reference_lat(self):
        x = np.linspace(-40.,40.,41)
        y = np.linspace(-30.,30.,41)
        gx, gy = np.meshgrid(x,y,indexing='ij')
        s = 0.18
        f = np.stack((gx+s*gy,gy),axis=-1)
        ftle,_=metric_ftle_from_flowmap(f,x,y,20.,168.)
        eigmax=(2+s*s + np.sqrt((2+s*s)**2-4))/2
        expected=np.log(eigmax)/(2*168)
        self.assertAlmostEqual(ftle[len(x)//2,len(y)//2], expected, places=10)

    def test_zonal_projection_correction_increases_at_high_latitude(self):
        self.assertAlmostEqual(float(zonal_projection_factor(0., 30.)), 1., places=14)
        one_degree_north=6371.0088*np.pi/180
        self.assertGreater(float(zonal_projection_factor(one_degree_north,30.)),1.)

    def test_advection_spherical_zonal_correction(self):
        t=np.arange(-12.,1.)
        axis=np.linspace(-100.,100.,41)
        u=np.ones((len(t),41,41),float)
        v=np.zeros_like(u)
        x=np.array([0.,5.,10.]); y=np.array([-20.,0.,20.])
        f,valid,_=coast_safe_flowmap(t,axis,axis,u,v,x,y,12,1,1,
                    reference_lat_deg=30.)
        self.assertTrue(valid.all())
        for j,ycoord in enumerate(y):
            expected = x - 12*float(zonal_projection_factor(ycoord,30.))
            self.assertTrue(np.allclose(f[:,j,0],expected,atol=1e-9))

    def test_full_vs_cropped_seeding_same_trajectories(self):
        t=np.arange(-24,1,dtype=float)
        axis=np.linspace(-150.,150.,41)
        u=np.ones((len(t),41,41))*0.9
        v=np.ones_like(u)*0.3
        xfull=np.linspace(-60,60,13); yfull=np.linspace(-50,50,11)
        whole,valid,_=coast_safe_flowmap(t,axis,axis,u,v,xfull,yfull,24,1,1)
        crop,valid_crop,_=coast_safe_flowmap(t,axis,axis,u,v,xfull[3:10],yfull[2:9],24,1,1)
        self.assertTrue(valid_crop.all())
        self.assertTrue(np.allclose(whole[3:10,2:9], crop,atol=1e-12))

    def test_guard_rejects_land_for_interpolation_even_without_erosion(self):
        t=np.arange(-3.,1.)
        axis=np.arange(21.,dtype=float)
        u=np.zeros((len(t),21,21))
        v=np.zeros_like(u)
        u[:,10,10]=np.nan
        v[:,10,10]=np.nan
        flow,valid,_=coast_safe_flowmap(t,axis,axis,u,v,
                     np.array([9.5,11.5,15]),np.array([9.5]),3,1,
                     coast_guard_native_cells=0)
        self.assertFalse(valid[0,0])
        self.assertTrue(valid[-1,0])

    def test_shared_normalization_cross_day_and_no_lookahead(self):
        fields=[np.ones((2,2))*v for v in (1,2,3)]
        norms,limits=normalize_comparable_days(fields,0,100)
        self.assertEqual(limits,(1.,3.))
        self.assertAlmostEqual(norms[0][0,0],0.)
        self.assertAlmostEqual(norms[1][0,0],0.5)
        self.assertAlmostEqual(norms[2][0,0],1.)
        days=[date(2026,11,1)+timedelta(days=i) for i in range(3)]
        self.assertAlmostEqual(trailing_persistence(norms,1,3,days)[0,0],0.25)
        self.assertAlmostEqual(trailing_persistence(norms,0,3,days)[0,0],0.)

if __name__=='__main__': unittest.main()

class CatalogueChecks(unittest.TestCase):
    def test_velocity_components_not_mixed(self):
        from lcs_pipeline.copernicus_io import resolve_requested_variables
        meta={'variables':[{'short_name':'uo'}, {'short_name':'vtotal'}]}
        with self.assertRaises(KeyError):
            resolve_requested_variables(meta,['uo','utotal'],['vo','vtotal'])
        meta['variables'].append({'short_name':'utotal'})
        self.assertEqual(resolve_requested_variables(meta,['uo','utotal'],['vo','vtotal']), ['utotal','vtotal'])

    def test_strict_operational_hourly_gap(self):
        from lcs_pipeline.land import coast_safe_flowmap
        t=np.array([-3.,-1.,0.]);axis=np.linspace(-10,10,9)
        u=np.zeros((3,9,9));v=u.copy()
        with self.assertRaisesRegex(ValueError,'sampling interval'):
            coast_safe_flowmap(t,axis,axis,u,v,np.array([0.,1.]),np.array([0.,1.]),3,
                max_input_time_gap_hours=1.51)
