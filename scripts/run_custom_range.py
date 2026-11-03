from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_pipeline import add_bbox_args
from datetime import datetime, timedelta


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config/defaults.json")
    p.add_argument("--start-local-date", required=True)
    p.add_argument("--end-local-date", required=True)
    p.add_argument("--step-hours", type=int, default=24)
    p.add_argument("--preset", default=None)
    return add_bbox_args(p).parse_args()


def main() -> None:
    args = parse_args()
    start = datetime.fromisoformat(args.start_local_date + "T00:00:00")
    end = datetime.fromisoformat(args.end_local_date + "T00:00:00")
    step = timedelta(hours=args.step_hours)
    cur = start
    while cur <= end:
        label = f"range_{cur.strftime('%Y%m%dT%H%M')}"
        cmd = [
            sys.executable,
            "scripts/run_pipeline.py",
            "--config",
            args.config,
            "--target-local-datetime",
            cur.isoformat(timespec="minutes"),
            "--run-label",
            label,
            "--mode",
            "custom_range",
        ]
        if args.preset:
            cmd.extend(["--preset", args.preset])
        for key in ('lon_min','lon_max','lat_min','lat_max'):
            v=getattr(args,key)
            if v is not None: cmd.extend(['--'+key.replace('_','-'),str(v)])
        subprocess.run(cmd, check=True)
        cur += step
    subprocess.run([sys.executable, "scripts/build_pages.py", "--config", args.config], check=True)


if __name__ == "__main__":
    main()
