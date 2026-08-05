from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from odds_asof.loader import load_odds_registry
from odds_asof.reporting import write_odds_asof_outputs
from odds_asof.selection import select_odds_asof


def _slug(value: str) -> str:
    return value.replace(":", "").replace("-", "").replace("+", "")


def main() -> None:
    parser = argparse.ArgumentParser(description="Select latest saved odds snapshots as of a timestamp")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--sportsbook", action="append")
    parser.add_argument("--sportsbooks", nargs="*")
    parser.add_argument("--market")
    parser.add_argument("--registry", type=Path, default=PROJECT_ROOT / "data" / "processed" / "odds" / "snapshot_registry.csv")
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    books = args.sportsbooks or args.sportsbook
    registry = load_odds_registry(args.registry, project_root=PROJECT_ROOT)
    result = select_odds_asof(registry=registry, project_root=PROJECT_ROOT, season=args.season, week=args.week, as_of=args.as_of, sportsbooks=books, market=args.market)
    output_dir = args.output_root / "data" / "processed" / "odds_asof" / str(args.season) / f"week_{args.week:02d}" / f"asof_{_slug(args.as_of)}"
    outputs = write_odds_asof_outputs(result, output_dir=output_dir, overwrite=args.overwrite)
    print("[selected_snapshots]", len(result["selected_snapshots"]))
    print("[selected_odds]", len(result["selected_odds"]))
    print("[coverage_rows]", len(result["coverage"]))
    print("[output_paths]", outputs)


if __name__ == "__main__":
    main()
