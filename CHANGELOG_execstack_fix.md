# Seyd Yar LCS — GitHub Actions native-runtime hotfix

## Root cause confirmed in the 2026-11-02 21:23 UTC log

- Copernicus Marine credentials were present and the shared dataset subset downloaded.
- All historical/current target dates and forecast days +1 through +8 were skipped while loading `numbalsoda/libsolve_ivp.so`:
  `cannot enable executable stack as shared object requires: Invalid argument`.
- Forecast days +9/+10 were skipped independently because no matching target time was returned by the downloaded dataset. The catalog indicated data until 2026-11-11 23:00 UTC; do not interpret the configured maximum of +10 days as guaranteed availability.
- There was **no FTLE map, video or daily result** from this run.

## Changes

1. `.github/workflows/run_lcs.yml`: after pip dependencies install, install `patchelf` and execute a native-library preflight **before Copernicus download**.
2. `scripts/repair_native_runtime.py`: inspect the installed `numbalsoda/libsolve_ivp.so`, clear only its ELF executable-stack requirement using `patchelf --clear-execstack`, then run a **real DOP853 numerical integration** with an expected analytical solution and verify `numbacs` can import.
3. Leave existing geographic bounds, 14 historical days, adaptive future horizon and interactive dashboard unchanged.

## Verification and limits

- Python syntax and workflow structure can be checked offline.
- **Must still run on GitHub Ubuntu runner** to confirm binary compatibility and the end-to-end FTLE computation.
- The patch modifies only an installed third-party ELF file; it does not disable process-wide memory protection. An actual numerical smoke test catches basic incompatibility. If the solver genuinely needs executable stack, the smoke test will fail early rather than proceeding with invalid calculations.

## Use

Replace the updated workflow and add `scripts/repair_native_runtime.py`; the full-project ZIP contains both. Run `mode_choice=single_horizon`, `horizon_offset=0` first for an inexpensive real-data test. Once it succeeds, use `routine` for the complete sequence.
