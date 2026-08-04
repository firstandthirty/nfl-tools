from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from projection_registry.registry import build_projection_registry


def main() -> None:
    parser = argparse.ArgumentParser(description="Build projection snapshot registry and coverage reports")
    parser.add_argument("--source")
    parser.add_argument("--season", type=int)
    parser.add_argument("--week", type=int)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()

    result = build_projection_registry(
        project_root=PROJECT_ROOT,
        output_root=args.output_root,
        source=args.source,
        season=args.season,
        week=args.week,
        rebuild=args.rebuild,
    )

    print("[processed snapshots discovered]", len(result["registry_rows"]))
    print("[registry rows added]", result["added_rows"])
    print("[registry rows unchanged]", result["unchanged_rows"])
    print("[conflicts found]", len(result["conflicts"]))
    print("[coverage reports written]", result["coverage_reports_written"])
    print("[weekly coverage rows written]", result["weekly_coverage_rows_written"])
    print("[snapshot comparison rows written]", result["snapshot_comparison_rows_written"])
    print("[output paths]", result["output_paths"])
    print("[warnings]", result["warnings"])


if __name__ == "__main__":
    main()
