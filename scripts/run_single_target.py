from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_pipeline import add_bbox_args
from datetime import datetime


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config/defaults.json")
    p.add_argument("--target-local-datetime", required=True)
    p.add_argument("--preset", default=None)
    return add_bbox_args(p).parse_args()


def main() -> None:
    args = parse_args()
    dt = datetime.fromisoformat(args.target_local_datetime)
    label = f"single_{dt.strftime('%Y%m%dT%H%M')}"
    cmd = [
        sys.executable,
        "scripts/run_pipeline.py",
        "--config",
        args.config,
        "--target-local-datetime",
        dt.isoformat(timespec="minutes"),
        "--run-label",
        label,
        "--mode",
        "custom_single",
    ]
    if args.preset:
        cmd.extend(["--preset", args.preset])
    for key in ('lon_min','lon_max','lat_min','lat_max'):
        v=getattr(args,key)
        if v is not None: cmd.extend(['--'+key.replace('_','-'),str(v)])
    subprocess.run(cmd, check=True)
    subprocess.run([sys.executable, "scripts/build_pages.py", "--config", args.config], check=True)


if __name__ == "__main__":
    main()
