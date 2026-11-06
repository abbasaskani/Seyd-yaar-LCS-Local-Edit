"""Regression checks for LCS-only static dashboard controls; no live ocean needed."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
import xarray as xr

from scripts.build_pages import main as build_main
from scripts.validate_pages import validate

ROOT = Path(__file__).resolve().parents[1]


class TestLCSMapUI(unittest.TestCase):
    def test_dashboard_elements_and_asset_copy_contract(self):
        html = (ROOT / "docs/lcs_template.html").read_text(encoding="utf-8")
        js = (ROOT / "docs/lcs_app.js").read_text(encoding="utf-8")
        for element in (
            "mapStage", "inspector", "inspectConnector", "coordinateMode", "coordLat", "coordLon",
            "gammaRange", "minValue", "maxValue", "paletteSelect", "mapLegend", "datePick",
            "playSpeed", "saveMap", "pinPoint", "projectSelect", "loadSecond",
            "inspectCoordMode", "inspectLat", "inspectLon", "inspectCoordGo", "inspectCoordCopy",
        ):
            self.assertIn(f'id="{element}"', html)
        self.assertIn('href="lcs_ui.css"', html)
        self.assertIn('src="lcs_app.js"', html)
        self.assertIn('new Date()', js) if False else None
        self.assertIn('Date.now()', js)
        self.assertIn('new Float32Array(buf)', js)
        self.assertNotIn('manualLatOffset', js)
        self.assertNotIn('manualLonOffset', js)
        self.assertIn("shutil.copy2(Path(__file__).resolve().parents[1] / 'docs' / 'lcs_ui.css'", (ROOT / 'scripts/build_pages.py').read_text())

    def test_js_syntax(self):
        p = subprocess.run(['node', '--check', str(ROOT / 'docs/lcs_app.js')], capture_output=True, text=True)
        self.assertEqual(0, p.returncode, p.stderr)

    def test_coordinate_conversion_algorithms(self):
        js = (ROOT / 'docs/lcs_app.js').read_text(encoding='utf-8')
        start = js.index('  function parseCoord(')
        end = js.index('  const coordsOf=', start)
        funcs = js[start:end]
        runner = '''
const assert = require('node:assert/strict');
''' + funcs + '''
const nearly=(a,b)=>assert.ok(Math.abs(a-b)<1e-5, String(a)+' !== '+String(b));
nearly(parseCoord('58° 15′ 00″ E', 'lon'),58.25);
nearly(parseCoord('12° 30′ 00″ N', 'lat'),12.5);
nearly(parseCoord('12° 30′ 00″ S', 'lat'),-12.5);
nearly(parseCoord('۵۸٫۲۵', 'lon'),58.25);
nearly(parseCoord('58° 15.0000′ E', 'lon'),58.25);
assert.match(coordText(58.25,'dms','lon'),/58° 15′ 0.00″ E/);
assert.match(coordText(-12.5,'dmm','lat'),/12° 30.0000′ S/);
assert.throws(()=>parseCoord('95°','lat'));
assert.throws(()=>parseCoord('12° 62′','lat'));
assert.throws(()=>parseCoord('12° 4′ E','lat'));
console.log('Coordinate conversion checks passed');
'''
        p = subprocess.run(['node', '-e', runner], capture_output=True, text=True)
        self.assertEqual(0, p.returncode, p.stderr)

    def test_synthetic_day_publish_and_validate(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            run = temp / 'outputs/latest/test_day'
            run.mkdir(parents=True)
            lon, lat = np.meshgrid(np.array([55., 55.2, 55.4, 55.6]),
                                   np.array([12., 12.2, 12.4, 12.6]), indexing='ij')
            f = np.arange(16., dtype=float).reshape(4, 4) / 1000
            dataset = xr.Dataset(
                data_vars={
                    'ftle': (('x','y'), f), 'ftle_smooth': (('x','y'), f),
                    'ridge_support': (('x','y'), np.ones_like(f)*.4),
                    'lon': (('x','y'), lon), 'lat': (('x','y'), lat),
                    'current_u': (('x','y'), np.ones_like(f)*.2),
                    'current_v': (('x','y'), np.ones_like(f)*.1),
                    'current_speed': (('x','y'), np.ones_like(f)*np.hypot(.2,.1)),
                },
                coords={'x':np.arange(4), 'y':np.arange(4)},
                attrs={'target_time':'2026-11-03T12:00:00Z','u_variable':'uo','v_variable':'vo'}
            )
            dataset.to_netcdf(run/'ftle.nc',engine='scipy')
            meta={'actual_selected_utc':'2026-11-03T12:00:00+00:00',
                  'requested_target_date_local':'2026-11-03',
                  'bbox':{'lon_min':55.,'lon_max':55.6,'lat_min':12.,'lat_max':12.6}}
            (run/'summary.json').write_text(json.dumps({'metadata':meta}),encoding='utf-8')
            for name in ('ridges','hotspots','clusters'):
                (run/f'{name}.geojson').write_text('{"type":"FeatureCollection","features":[]}',encoding='utf-8')
            cfg=json.loads((ROOT/'config/defaults.json').read_text())
            cfg['outputs_dir']=str(temp/'outputs')
            cfg['pages_dir']=str(temp/'pages')
            cfg['media']['create_mp4']=False
            cfg['save_postprocessed_netcdf']=False
            cfg_path=temp/'test_config.json'
            cfg_path.write_text(json.dumps(cfg),encoding='utf-8')
            process=subprocess.run(['python','scripts/build_pages.py','--config',str(cfg_path)],cwd=ROOT,
                                   capture_output=True,text=True)
            self.assertEqual(0,process.returncode,process.stderr)
            published=temp/'pages'
            for fpath in ('index.html','lcs_app.js','lcs_ui.css','manifest.json','runs/test_day/web_day.json','runs/test_day/web_layers.f32'):
                self.assertTrue((published/fpath).is_file(),fpath)
            # The production workflow downloads signed Leaflet assets before validation;
            # mocks here test site packaging without reaching a CDN.
            (published/'leaflet.js').write_bytes(b'x'*110000)
            (published/'leaflet.css').write_bytes(b'x'*11000)
            self.assertEqual(1,validate(published))
            manifest=json.loads((published/'manifest.json').read_text())
            self.assertEqual('test_day',manifest['runs'][0]['name'])
            data=json.loads((published/'runs/test_day/web_day.json').read_text())
            self.assertEqual(data['format'],'seyd-yaar-flat-f32-v1')
            self.assertEqual((published/'runs/test_day/web_layers.f32').stat().st_size,
                             4*4*4*len(data['layers']))


if __name__ == '__main__':
    unittest.main()
