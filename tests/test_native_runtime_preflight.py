"""Offline tests of the GitHub Actions native ELF repair orchestration."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_FILE = Path(__file__).resolve().parents[1] / 'scripts' / 'repair_native_runtime.py'
spec = importlib.util.spec_from_file_location('repair_native_runtime', MODULE_FILE)
preflight = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(preflight)


def test_missing_patchelf_fails_before_computation(monkeypatch, tmp_path):
    binary = tmp_path / 'libsolve_ivp.so'
    binary.write_bytes(b'test')
    monkeypatch.setattr(preflight.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(preflight, 'installed_library', lambda: binary)
    monkeypatch.setattr(preflight.shutil, 'which', lambda name: None)
    with pytest.raises(RuntimeError, match='patchelf is missing'):
        preflight.repair_native_library()


def test_only_target_numbalsoda_library_is_patched(monkeypatch, tmp_path):
    binary = tmp_path / 'libsolve_ivp.so'
    binary.write_bytes(b'test')
    commands = []

    def fake_run(args, **kwargs):
        commands.append(list(args))
        return SimpleNamespace(stdout='no\n', returncode=0)

    monkeypatch.setattr(preflight.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(preflight, 'installed_library', lambda: binary)
    monkeypatch.setattr(preflight.shutil, 'which', lambda name: '/usr/bin/patchelf')
    monkeypatch.setattr(preflight.subprocess, 'run', fake_run)

    preflight.repair_native_library()
    assert commands == [
        ['/usr/bin/patchelf', '--print-execstack', str(binary)],
        ['/usr/bin/patchelf', '--clear-execstack', str(binary)],
        ['/usr/bin/patchelf', '--print-execstack', str(binary)],
    ]


def test_non_linux_does_not_patch(monkeypatch):
    monkeypatch.setattr(preflight.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(preflight, 'installed_library', lambda: pytest.fail('should not be called'))
    preflight.repair_native_library()
