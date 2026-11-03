# Seyd Yar LCS — Repair and validation report (2026-11-03)

## Diagnostic evidence from uploaded GitHub Actions archive

- Workflow Run ID: `41535286716`; execution on 2026-11-02.
- `Analyze ocean / create outputs` finished and listed 23 successful target-day entries; `+9` and `+10` were skipped because target times were missing.
- `Upload runs and diagnostics`: **success**; artifact ID `13185020227` (`seyd-yaar-lcs-outputs`), 241,513,373 bytes.
- `Upload Pages`: **success**; artifact ID `13185055286`, 121,181,351 bytes.
- `Deploy Pages`: **Reported success!** on `2026-11-02T22:17:07Z`.
- An Actions artifact is *not* a Git commit. Thus an empty `outputs/latest/` in the repository Code browser is expected after a run.
- Site failure cannot be attributed to a failed Pages deployment based on this archive. Previous Pages build included large per-day JSON and raw NetCDF. Browser/network errors were NOT captured in the uploaded Actions log, so an exact client-side failure mechanism cannot be proved from the log alone.

## Repairs delivered in this version

1. **Separated data domain and particle seed domain.** Computation now seeds the requested geographic rectangle plus eight fine cells for finite-difference/stencil operations, while retaining the buffered Copernicus velocity grid for particle motion. Previously particles were launched across the entire downloaded buffer. This reduces unnecessary trajectories and memory without lowering the chosen FTLE seed-grid spacing. It is not a promise of bit-for-bit equality at cropped boundaries.
2. **Unified bounded coastal advection.** Both open ocean and island/coastal regions now use a common vectorized RK4 flow-map integration. Every RK4 stage, plus its endpoint, is checked for land masks, finite currents, and velocity-grid bounds. Failed trajectories are not passed off as successes. The former open-ocean DOP853 branch was removed from the default pipeline because it had no reliable per-trajectory success reporting and produced thousands of numerical step failure messages. **RK4 is not mathematically identical to DOP853.**
3. **Diagnostic accounting.** Each run stores counts of valid trajectories, invalid land/guard, invalid domain exit, invalid velocity; coverage of valid FTLE cells in the chosen AOI; and a sample-grid RK4 1h vs 0.5h comparison. A `quality_flag` signals numerical review. A sample comparison is NOT a comprehensive validation of all FTLE ridges.
4. **FTLE/Ridge boundary safeguards.** A finite-difference validity stencil is required; Gaussian smoothing normalizes by valid water cells. Ridge endpoints are clipped on a multi-cell mask and split at invalid gaps. Percentile calculation compensates for invalid cells temporarily filled for the NumbaCS extraction API. Nearshore ridges are conservatively masked: a deliberate loss of spatial coverage, not an assertion of coastal physical fidelity.
5. **Coastline limitations remain explicit.** The mask is based on the *ocean product's native cells*; islands much smaller than the product grid may remain unresolved. No high-resolution bathymetry integration was claimed.
6. **Memory and runtime.** 25 daily windows still use one shared Copernicus subset. Postprocessing generates one daily PNG for the sequence MP4 rather than seven raster PNGs each day. MP4 frames are streamed through the encoder rather than loaded all at once. Scientific per-day NetCDF is losslessly compressed if netCDF4 is installed. A run-wide budget of 290 minutes from job initialization reserves time within the 350-minute workflow timeout for publication; later dates are skipped and documented when budget is reached. This cannot guarantee completion if an individual download/day or network request exceeds the budget.
7. **Browser site fixed for data weight and external JS reliability.** Browser receives `web_day.json` plus compact per-day, little-endian Float32 visualization arrays, keeping full numeric NetCDF exclusively in Actions artifacts. Leaflet 1.9.4 JS/CSS is downloaded on the GitHub runner and its official SHA-256 is verified, then published locally with the site. UI shows selected days, current arrows, LCS vector ridges, hotspots, popup information and sequence MP4. No latitude/longitude offset from the separate unrelated project has been applied.
8. **Rerun-safe Pages artifacts.** GitHub Pages upload/deploy use a unique artifact name containing `github.run_attempt`, preventing the earlier duplicate `github-pages` artifact problem when re-running a failed job.
9. **Prepublication validation.** `scripts/validate_pages.py` checks for the HTML, JS, Leaflet assets, manifest, per-day raster binary lengths, ridge GeoJSON and referenced video. Invalid site packaging fails before Pages publication.
10. **Artifact visibility.** Scientific outputs remain under `outputs/latest/` in the Actions artifact, not in a repository commit. A downloadable `quality_report.csv` / `run_report.json` accompanies outputs. Browser site has only lightweight visualization data and selected GeoJSON and summary files.

## Validation performed locally

- Eight Python unit tests passed (geographic manual bounds, time coverage, calendar-day persistence, coastal/land barrier, uniform-velocity analytic displacement, exits across grid bounds, irregular time samples, binary web format).
- Python `compileall` and Node.js `--check` for JS passed.
- Synthetic two-day pipeline test built dashboard data, JSON/GeoJSON, and an MP4 successfully. This is NOT a live Copernicus run.
- A synthetic seven-day advection/FTLE smoke test with a **stub** for unavailable NumbaCS eigenvalue/ridge functions returned near-zero FTLE for uniform translation; this does not validate the actual NumbaCS native implementation.

## Important work NOT done / requires live validation

- No new run with real Copernicus ocean currents on the user's GitHub Actions runner has been performed after these changes.
- Actual NumbaCS ridge extraction, numerical FTLE convergence against an independent reference, and stability of ridge locations for real eddies have NOT been experimentally established.
- Full browser-map integration with the newly downloaded Leaflet files (and OpenStreetMap tiles) cannot be verified here because this runtime has no access to CDN downloads. The CI downloads and validates pinned files; the live Pages website must still be checked.
- No guarantee of bitwise/identical FTLE outputs is possible when switching from DOP853/cubic interpolation to RK4/linear interpolation. The numeric solution, especially near coastlines, can change; this change is deliberate to prevent false confident outputs.
- The 2-degree velocity buffer is configurable, **not mathematically guaranteed** to contain every seven-day trajectory. `invalid_domain_exit` counts should guide a larger data buffer or smaller domain if needed.
- No high-resolution shoreline/bathymetry product was integrated; no scientific validation with satellite/current drifters, fish catch or effort data was completed.
- An 8-day future availability in the previous log was specific to that data download. The +9/+10 days can be available in different future model releases. The code still requests up to 10 and skips missing targets.

## Deployment instructions

1. Replace files with the `changed_files` archive, keeping their relative paths; OR upload the `full_project` archive contents into the repository root. Don't create an extra `seyd-yaar-LCS/` nested folder if the existing GitHub root already contains `requirements.txt`.
2. Keep the existing Copernicus GitHub repository secrets configured. GitHub Pages Source must be set to **GitHub Actions**.
3. Run `Actions > Run Seyd Yar LCS`, `single_horizon`, `0`, with four latitude/longitude coordinates. A green workflow and site load are necessary first smoke tests; then run `routine`.
4. Download scientific results from the `seyd-yaar-lcs-outputs` **Actions Artifact** for that run. Check its `quality_report.csv` and each day's `summary.json` > `metadata.numerical_quality`. Successful job status does not certify scientific accuracy.
5. To find why a page does not load, inspect browser Developer Tools -> Network/Console for `leaflet.js`, `web_day.json`, and `web_layers.f32` errors; attach those and the fresh Actions log.

## Scientific interpretation

FTLE is a finite-time material deformation diagnostic, not a calibrated probability of tuna presence. Ridge lines represent candidate attracting structures and are sensitive to the velocity model, trajectory integration, interpolation, and finite-difference resolution. Fishing recommendations require independent biological / catch-effort validation.
