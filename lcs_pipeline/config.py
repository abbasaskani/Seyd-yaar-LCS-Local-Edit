from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ProjectConfig:
    raw: dict[str, Any]
    base_dir: Path

    @property
    def outputs_dir(self) -> Path:
        return self.base_dir / self.raw.get("outputs_dir", "outputs")

    @property
    def pages_dir(self) -> Path:
        return self.base_dir / self.raw.get("pages_dir", "docs/latest")

    @property
    def archive_dir(self) -> Path:
        return self.base_dir / self.raw.get("archive_dir", "outputs/archive")

    @property
    def aoi_path(self) -> Path:
        return self.resolve_path(self.raw.get("aoi_geojson", "config/aoi/current.geojson"))

    def resolve_path(self, value: str | Path) -> Path:
        p = Path(value)
        return p if p.is_absolute() else self.base_dir / p


def load_config(path: str | Path) -> ProjectConfig:
    path = Path(path).resolve()
    raw = json.loads(path.read_text(encoding="utf-8"))
    base_dir = path.parent.parent if path.parent.name == "config" else path.parent
    return ProjectConfig(raw=raw, base_dir=base_dir)
