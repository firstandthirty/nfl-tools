from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the PFF content package for a week, season-to-date, or both.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int)
    parser.add_argument("--through-week", type=int)
    parser.add_argument("--period", choices=["week", "season", "both"], default="week")
    parser.add_argument("--allow-incomplete", action="store_true")
    return parser.parse_args()


def run(script: str, args: argparse.Namespace) -> None:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / script),
        "--season",
        str(args.season),
        "--period",
        args.period,
    ]
    if args.week is not None:
        cmd.extend(["--week", str(args.week)])
    if args.through_week is not None:
        cmd.extend(["--through-week", str(args.through_week)])
    if args.allow_incomplete:
        cmd.append("--allow-incomplete")
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> None:
    args = parse_args()
    for script in ["build_weekly_analysis.py", "build_charts.py", "build_leaderboards.py", "build_content_discovery.py"]:
        run(script, args)


if __name__ == "__main__":
    main()
