from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.save_run_preferences import coordinate_bounds, persist


class SavedPreferencesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "config" / "aoi").mkdir(parents=True)
        self.path = self.root / "config" / "defaults.json"
        self.path.write_text(json.dumps({
            "aoi_geojson": "config/aoi/current.geojson",
            "time_reference": {"default_preset_key": "utc_plus_4", "presets": [
                {"key": "utc_plus_4"}, {"key": "jakarta"}
            ]},
        }), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_manual_input_saved_and_blank_reuses_without_rewriting(self):
        values = {"lon_min": "55.5", "lon_max": "60", "lat_min": "12", "lat_max": "16"}
        first = persist(self.path, values)
        self.assertEqual(first["changed_paths"], ["config/aoi/current.geojson"])
        saved_path = self.root / "config/aoi/current.geojson"
        before = saved_path.read_bytes()
        second = persist(self.path, {k: "" for k in values})
        self.assertEqual(second["changed_paths"], [])
        self.assertEqual(before, saved_path.read_bytes())
        third = persist(self.path, values)
        self.assertEqual(third["changed_paths"], [])
        saved = json.loads(saved_path.read_text())
        self.assertEqual(saved["features"][0]["geometry"]["coordinates"][0][0], [55.5, 12.0])

    def test_manual_edit_updates_stored_geometry(self):
        old = {"lon_min": "55", "lon_max": "60", "lat_min": "12", "lat_max": "15"}
        new = dict(old, lon_min="54.5")
        persist(self.path, old)
        result = persist(self.path, new)
        self.assertEqual(result["changed_paths"], ["config/aoi/current.geojson"])
        self.assertEqual(json.loads((self.root / "config/aoi/current.geojson").read_text())["features"][0]["geometry"]["coordinates"][0][0][0], 54.5)

    def test_partial_nonfinite_and_inverted_coordinates_rejected(self):
        for values in [
            {"lon_min": "55", "lon_max": "", "lat_min": "12", "lat_max": "16"},
            {"lon_min": "nan", "lon_max": "60", "lat_min": "12", "lat_max": "16"},
            {"lon_min": "60", "lon_max": "55", "lat_min": "12", "lat_max": "16"},
        ]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                coordinate_bounds(values)

    def test_timezone_persists_and_blank_does_not_revert(self):
        values = {"lon_min": "55", "lon_max": "60", "lat_min": "12", "lat_max": "16"}
        result = persist(self.path, values, "jakarta")
        self.assertEqual(set(result["changed_paths"]), {"config/aoi/current.geojson", "config/defaults.json"})
        before = self.path.read_bytes()
        next_result = persist(self.path, {k: "" for k in values}, "")
        self.assertEqual(next_result["changed_paths"], [])
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(json.loads(self.path.read_text())["time_reference"]["default_preset_key"], "jakarta")

    def test_invalid_timezone_must_not_modify_aoi(self):
        values = {"lon_min": "55", "lon_max": "60", "lat_min": "12", "lat_max": "16"}
        with self.assertRaises(ValueError):
            persist(self.path, values, "invalid")
        self.assertFalse((self.root / "config/aoi/current.geojson").exists())

    def test_blank_requires_saved_file(self):
        with self.assertRaises(FileNotFoundError):
            persist(self.path, {key: "" for key in ("lon_min", "lon_max", "lat_min", "lat_max")})


if __name__ == "__main__":
    unittest.main()
