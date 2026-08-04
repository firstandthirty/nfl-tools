from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from projection_consensus.aggregation import build_consensus_rows
from projection_consensus.loader import load_snapshot_registry
from projection_consensus.reporting import build_consensus_outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Build source-agnostic projection consensus outputs")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--as-of")
    parser.add_argument("--source")
    parser.add_argument("--sources", nargs="*")
    parser.add_argument("--required-sources", nargs="*")
    parser.add_argument("--market")
    parser.add_argument("--min-sources", type=int, default=3)
    parser.add_argument("--max-projection-std", type=float)
    parser.add_argument("--max-projection-range", type=float)
    parser.add_argument("--max-snapshot-age-hours", type=float)
    parser.add_argument("--max-source-time-gap-hours", type=float)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    project_root = PROJECT_ROOT
    registry_path = args.registry or project_root / "data" / "processed" / "projections" / "snapshot_registry.csv"
    registry = load_snapshot_registry(registry_path, project_root=project_root)
    sources = args.sources or ([args.source] if args.source else None)
    selected_result = build_consensus_rows(
        registry=registry,
        project_root=project_root,
        season=args.season,
        week=args.week,
        as_of=args.as_of,
        sources=sources,
        min_sources=args.min_sources,
        max_projection_std=args.max_projection_std,
        max_projection_range=args.max_projection_range,
        required_sources=args.required_sources,
        max_snapshot_age_hours=args.max_snapshot_age_hours,
        max_source_time_gap_hours=args.max_source_time_gap_hours,
    )
    output_dir = args.output_root / "data" / "processed" / "projection_consensus" / str(args.season) / f"week_{args.week}"
    if args.as_of:
        slug = args.as_of.replace(":", "").replace("-", "").replace("+", "")
        output_dir = output_dir / f"asof_{slug}"
    else:
        output_dir = output_dir / "asof_now"
    build_consensus_outputs(selected_result, output_dir=output_dir, overwrite=args.overwrite)

    print("[selected_snapshots]", len(selected_result["selected_snapshots"]))
    print("[selected_projection_rows]", len(selected_result["selected_source_projections"]))
    print("[consensus_rows]", len(selected_result["consensus_rows"]))
    print("[output_dir]", output_dir)


if __name__ == "__main__":
    main()
