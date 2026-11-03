# Seyd Yar LCS — coast-aware rolling FTLE and interactive map

**Seyd Yar LCS** analyzes attracting FTLE and Lagrangian coherent structures in Copernicus global-ocean surface currents. Its derived accumulation-potential index is **not** a calibrated prediction of tuna catches.

This release adds rolling `-14` historical to up to `+10` forecast output dates (as data permits), per-target **7-day backward** integrations, shared Copernicus subsets, adaptive forecast fallback, conservative land/island crossing rejection, manual bounding box inputs in GitHub Actions, Leaflet map/interactive per-cell popups, and a daily LCS-map-change MP4.

Run via **GitHub Actions → Run Seyd Yar LCS → Run workflow**. Enter all four `lon_min, lon_max, lat_min, lat_max` fields for a custom rectangle, or leave all blank to use the saved `config/aoi/current.geojson`. Configure Copernicus username/password as repository secrets. The output report lists successful and skipped dates and reasons; GitHub Pages serves the map dashboard.

See [README_fa.md](README_fa.md) for full Persian operating instructions, validation caveats and architecture. See [CHANGELOG_vNext.md](CHANGELOG_vNext.md) for completed work and tests. Offline smoke tests: `python -m unittest discover -s tests -v`.

**Release caveat:** Remote Copernicus downloads, actual NumbaCS production execution and live Pages deployment could not be exercised in the isolated preparation environment; do a first GitHub Actions test run before using outputs operationally.


## vNext Reliability / GitHub Pages and reproducible quality

See **`REPAIR_REPORT_2026-11-03.md`** for exact changes, log diagnostics, validation and limitations.

- Actions outputs are stored in **Artifacts**, not committed into the repository's `outputs` folder. Extract `seyd-yaar-lcs-outputs` for scientific NetCDF, per-day CSV/GeoJSON and run reports.
- The generated GitHub Pages dashboard is under `docs/latest/` after a successful Actions job. It includes compact browser data and a daily-sequence video. The source HTML template alone does not contain simulation results.
- GitHub Pages Source must be **GitHub Actions**. The workflow vendors verified Leaflet JS/CSS into `docs/latest` and validates the files before deployment.
- Daily ranges are -14 to the farthest Copernicus forecast target available (up to +10). Each backward FTLE still integrates seven complete days.
- Scientific time/space limitations: 2-degree configurable surrounding velocity grid, bounded RK4 with ocean-mask checking, and a sampled half-step diagnostic. An FTLE day can be geographically incomplete. Check `quality_report.csv` and `summary.json` before using it.
- Numeric solver method changed; **do not assume it matches previous DOP853 output point for point**. Real-data numerical/biological validation is still required.

## Scientific audit (2026-11-03)

Read `SCIENTIFIC_AUDIT_2026-11-03.md` before relying on the output. This revision includes regional spherical kinematics/metric-aware FTLE, strict coastal interpolation stencils, spatial RK4 step control, consistent paired vector components, operational hourly-gap rejection, and within-run comparable (but **uncalibrated**) 0–100 heuristic scores. Full Copernicus/NumbaCS production validation, adaptive buffer enlargement, six-hour batch guarantees, and independent drifter/fisheries skill evaluation remain **outstanding**.
