"""Repair and verify the installed numbalsoda DOP853 native library on Linux CI.

Linux/glibc may refuse libsolve_ivp.so if its ELF GNU_STACK flag requests an
executable stack. Do not relax kernel/glibc security restrictions globally:
clear only that flag on the installed third-party library and then check that
its numerical solver actually works. Run after pip install, before downloads.
"""
from __future__ import annotations

import importlib.metadata
import math
from pathlib import Path
import platform
import shutil
import subprocess


def installed_library() -> Path:
    dist = importlib.metadata.distribution("numbalsoda")
    path = Path(dist.locate_file("numbalsoda/libsolve_ivp.so"))
    if not path.is_file():
        raise FileNotFoundError(f"numbalsoda native library missing: {path}")
    return path


def repair_native_library() -> None:
    if platform.system() != "Linux":
        print("Non-Linux system: native GNU_STACK repair is not applicable")
        return

    library = installed_library()
    patcher = shutil.which("patchelf")
    if not patcher:
        raise RuntimeError("patchelf is missing; install it before the native preflight")
    print(f"numbalsoda native library: {library}", flush=True)
    before = subprocess.run([patcher, "--print-execstack", str(library)],
                            capture_output=True, text=True, check=True)
    print("GNU_STACK before:", before.stdout.strip(), flush=True)
    subprocess.run([patcher, "--clear-execstack", str(library)], check=True)
    after = subprocess.run([patcher, "--print-execstack", str(library)],
                           capture_output=True, text=True, check=True)
    print("GNU_STACK after:", after.stdout.strip(), flush=True)


def smoke_test_solver() -> None:
    """Checks actual DOP853 numerical integration, not just a package import."""
    import numpy as np
    from numba import cfunc
    from numbalsoda import dop853, lsoda_sig
    from numbacs.integration import flowmap_grid_2D  # noqa: F401

    @cfunc(lsoda_sig)
    def exponential_decay(t, y, dy, p):
        dy[0] = -y[0]

    times = np.array([0.0, 0.5, 1.0], dtype=np.float64)
    y0 = np.array([1.0], dtype=np.float64)
    result, success = dop853(exponential_decay.address, y0, times)
    if not success or result.shape != (3, 1):
        raise RuntimeError("numbalsoda DOP853 smoke test failed to integrate")
    error = abs(float(result[-1, 0]) - math.exp(-1.0))
    if error > 1e-3:
        raise RuntimeError(f"numbalsoda DOP853 smoke test inaccurate: error={error}")
    print(f"Native preflight OK: DOP853 exp(-1) error={error:.3g}", flush=True)


def main() -> None:
    repair_native_library()
    smoke_test_solver()


if __name__ == "__main__":
    main()
