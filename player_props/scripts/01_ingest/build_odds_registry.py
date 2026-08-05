from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from odds_registry.registry import build_odds_registry


def main() -> None:
    parser = argparse.ArgumentParser(description="Build saved sportsbook odds snapshot registry")
    parser.add_argument("--source")
    parser.add_argument("--season", type=int)
    parser.add_argument("--week", type=int)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    result = build_odds_registry(PROJECT_ROOT, output_root=args.output_root, source=args.source, season=args.season, week=args.week, rebuild=args.rebuild)
    print("[registry_rows]", len(result["registry_rows"]))
    print("[added_rows]", result["added_rows"])
    print("[unchanged_rows]", result["unchanged_rows"])
    print("[conflicts]", len(result["conflicts"]))
    print("[paths]", {"registry": result["registry_path"], "conflicts": result["conflicts_path"]})


if __name__ == "__main__":
    main()

