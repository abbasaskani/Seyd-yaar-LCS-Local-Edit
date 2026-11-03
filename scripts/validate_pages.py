"""Fail the workflow if public dashboard references missing / corrupted files."""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def validate(root: Path) -> int:
    for asset, min_size in [('leaflet.js', 100_000), ('leaflet.css', 10_000)]:
        if not (root / asset).exists() or (root / asset).stat().st_size < min_size:
            raise FileNotFoundError(f'Pinned Leaflet asset {asset} missing or too small')
    manifest_path = root / 'manifest.json'
    if not (root / 'index.html').exists() or not (root / 'lcs_app.js').exists() or not manifest_path.exists():
        raise FileNotFoundError('Dashboard HTML, JS or manifest missing from GitHub Pages folder')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if not manifest.get('runs'):
        raise ValueError('Dashboard has zero runs')
    count = 0
    for run in manifest['runs']:
        rd = root / 'runs' / run['name']
        meta = json.loads((rd / 'web_day.json').read_text(encoding='utf-8'))
        if meta['format'] != 'seyd-yaar-flat-f32-v1':
            raise ValueError(f'Unexpected browser data version for {rd}')
        expected = int(meta['shape'][0]) * int(meta['shape'][1]) * len(meta['layers']) * 4
        actual = (rd / meta['file']).stat().st_size
        if actual != expected:
            raise ValueError(f'Corrupted browser raster for {rd}: {actual} != {expected}')
        if not (rd / 'ridges.geojson').exists():
            raise FileNotFoundError(f'Ridge GeoJSON missing for {rd}')
        count += 1
    if manifest.get('sequence_video') and not (root / manifest['sequence_video']).exists():
        raise FileNotFoundError('Video advertised but missing')
    print(f'PASS GitHub Pages: HTML + JS + {count} daily compact rasters + GeoJSON verified')
    return count

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', nargs='?', default='docs/latest')
    validate(Path(parser.parse_args().root))
