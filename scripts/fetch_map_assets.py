"""Vendor pinned Leaflet 1.9.4 into the generated static Pages output.

Used only in the connected GitHub runner; no user browser must reach a JS CDN.
"""
from __future__ import annotations
from pathlib import Path
from urllib.request import urlopen, Request
import base64
import hashlib

ASSETS = {
    'leaflet.js': (100_000, '20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=', [
        'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
        'https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js']),
    'leaflet.css': (10_000, 'p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=', [
        'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
        'https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css']),
    'LEAFLET_LICENSE.txt': (500, None, [
        'https://raw.githubusercontent.com/Leaflet/Leaflet/v1.9.4/LICENSE',
        'https://unpkg.com/leaflet@1.9.4/LICENSE']),
}

def fetch(root: str | Path = 'docs/latest') -> None:
    dest = Path(root)
    dest.mkdir(parents=True, exist_ok=True)
    for name, (min_bytes, expected_sha, urls) in ASSETS.items():
        path = dest / name
        if path.exists() and path.stat().st_size >= min_bytes:
            continue
        errors = []
        for url in urls:
            try:
                request = Request(url, headers={'User-Agent':'SeydYar-LCS-builder/1.0'})
                with urlopen(request, timeout=25) as response:
                    body = response.read()
                if len(body) < min_bytes:
                    raise ValueError(f'Unexpected {name} asset size {len(body)}')
                if expected_sha:
                    checksum = base64.b64encode(hashlib.sha256(body).digest()).decode('ascii')
                    if checksum != expected_sha:
                        raise ValueError(f'Unexpected SHA256 for {name}, got {checksum}')
                path.write_bytes(body)
                print(f'Vendored {name} ({len(body)} bytes) from {url}')
                break
            except Exception as exc:
                errors.append(f'{url}: {exc}')
        else:
            raise RuntimeError(f'Unable to vendor {name}: ' + '; '.join(errors))

if __name__ == '__main__':
    fetch()
