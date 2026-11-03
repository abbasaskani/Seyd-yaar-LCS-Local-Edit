from __future__ import annotations

import json

from lcs_pipeline.config import load_config
from lcs_pipeline.copernicus_io import describe_dataset


def main() -> None:
    project = load_config("config/defaults.json")
    cfg = project.raw
    meta = describe_dataset(cfg["dataset_id"])
    print(json.dumps(meta, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
