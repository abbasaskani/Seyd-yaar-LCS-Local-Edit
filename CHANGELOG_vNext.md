# Seyd Yar LCS vNext — Changes and verification

## Implemented
- 14 historical output days plus today; adaptively attempt up to 10 forecast days.
- 7-day backward FTLE; 21-day historical source horizon for day -14.
- Shared Copernicus download + coverage validation, retry for reduced forecast horizon, non-fatal skip with diagnostics.
- Manual rectangle selection in GitHub Actions, full min/max validation.
- Coast-safe RK4 integration for masked surface currents; prevent crossing into land/invalid native grid cells, exclude adjacent output cells, and split ridges over land.
- Speed/direction snapshot from surface U/V, NetCDF and cell JSON.
- Leaflet georeferenced map; daily layers, LCS lines, hotspots, clusters, click popup, date player.
- Historical daily-map video generated as MP4, separate from current/particle advection.
- Fixed calendar-day-aligned persistence, actual-UTC chronological sort of daily outputs, video frame normalization, NetCDF metadata handling, and data preservation.
- Removed inherited manual map offsets (none needed for this data).

## Tests run
- Python syntax compilation; JavaScript syntax validation (Node).
- Synthetic coast barrier: invalid cells and adjacent cells rejected, ocean cells preserved.
- Synthetic 7-day hourly coverage success/failure cases.
- Manual bbox argument selection and default horizons.
- Synthetic NetCDF/JSON write/read.
- Complete two-day dashboard + MP4 generation using synthetic fixture (not real FTLE scientific validation).

## Not verified in this environment
- Live Copernicus authentication, catalogue metadata and subset service; remote internet unavailable.
- Actual NumbaCS API/runtime and high-resolution FTLE ridge fidelity; package could not be installed in sandbox.
- Live GitHub Actions and GitHub Pages deployment.
- Real small-island coastline validation and operational performance at all requested regions.

## Scientific caveat
A maximum nominal +10-day forecast horizon is not a guarantee of 10 future daily outputs; availability depends on Copernicus dataset release times and complete 7-day backward source coverage. Nearshore masking follows *the model resolution*, not coastline truth. Accumulation potential is a relative LCS-derived index and not calibrated catch probability.
