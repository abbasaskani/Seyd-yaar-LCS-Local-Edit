from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import xarray as xr

from scripts.build_pages import load_output_from_nc


class TestBuildPagesNetCDFHandle(unittest.TestCase):
    def test_source_closed_and_arrays_eagerly_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            shape = (3, 4)
            field = np.arange(12.0).reshape(shape)
            lon, lat = np.meshgrid(np.array([54.0, 55.0, 56.0]),
                                   np.array([11.0, 12.0, 13.0, 14.0]), indexing="ij")
            xr.Dataset(
                data_vars={
                    "ftle": (("x", "y"), field),
                    "ftle_smooth": (("x", "y"), field + 1),
                    "ridge_support": (("x", "y"), field * 0),
                    "lon": (("x", "y"), lon),
                    "lat": (("x", "y"), lat),
                },
                coords={"x": np.arange(shape[0]), "y": np.arange(shape[1])},
            ).to_netcdf(run_dir / "ftle.nc", engine="scipy")

            original_open = xr.open_dataset
            closed = []

            def tracked_open(*args, **kwargs):
                dataset = original_open(*args, **kwargs)
                original_close = dataset._close

                def record_close():
                    closed.append(True)
                    original_close()

                dataset.set_close(record_close)
                return dataset

            with patch("scripts.build_pages.xr.open_dataset", side_effect=tracked_open):
                out = load_output_from_nc(run_dir)
            self.assertEqual(closed, [True], "Source dataset must close before NetCDF rewrite")
            np.testing.assert_allclose(out.ftle, field)
            np.testing.assert_allclose(out.ftle_smooth, field + 1)
            self.assertEqual(out.lon_grid.shape, shape)


if __name__ == "__main__":
    unittest.main()
