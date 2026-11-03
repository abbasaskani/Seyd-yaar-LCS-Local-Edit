"""Offline native-runtime repair tests, using only Python's standard unittest."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

MODULE_FILE = Path(__file__).resolve().parents[1] / "scripts" / "repair_native_runtime.py"
spec = importlib.util.spec_from_file_location("repair_native_runtime", MODULE_FILE)
preflight = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(preflight)


class NativeRuntimePreflightTests(unittest.TestCase):
    def test_missing_patchelf_fails_before_computation(self):
        with TemporaryDirectory() as tempdir:
            binary = Path(tempdir) / "libsolve_ivp.so"
            binary.write_bytes(b"test")
            with (patch.object(preflight.platform, "system", return_value="Linux"),
                  patch.object(preflight, "installed_library", return_value=binary),
                  patch.object(preflight.shutil, "which", return_value=None)):
                with self.assertRaisesRegex(RuntimeError, "patchelf is missing"):
                    preflight.repair_native_library()

    def test_only_target_numbalsoda_library_is_patched(self):
        with TemporaryDirectory() as tempdir:
            binary = Path(tempdir) / "libsolve_ivp.so"
            binary.write_bytes(b"test")
            commands = []

            def fake_run(args, **kwargs):
                commands.append(list(args))
                return SimpleNamespace(stdout="no\n", returncode=0)

            with (patch.object(preflight.platform, "system", return_value="Linux"),
                  patch.object(preflight, "installed_library", return_value=binary),
                  patch.object(preflight.shutil, "which", return_value="/usr/bin/patchelf"),
                  patch.object(preflight.subprocess, "run", side_effect=fake_run)):
                preflight.repair_native_library()
            self.assertEqual(commands, [
                ["/usr/bin/patchelf", "--print-execstack", str(binary)],
                ["/usr/bin/patchelf", "--clear-execstack", str(binary)],
                ["/usr/bin/patchelf", "--print-execstack", str(binary)],
            ])

    def test_non_linux_does_not_patch(self):
        with (patch.object(preflight.platform, "system", return_value="Windows"),
              patch.object(preflight, "installed_library", side_effect=AssertionError("should not be called"))):
            preflight.repair_native_library()


if __name__ == "__main__":
    unittest.main()
