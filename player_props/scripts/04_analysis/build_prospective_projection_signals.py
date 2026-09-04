from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSING_DIR = PROJECT_ROOT / "scripts" / "02_processing"
MODELING_DIR = PROJECT_ROOT / "scripts" / "03_modeling"
for path in [PROCESSING_DIR, MODELING_DIR]:
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from odds_asof.loader import load_odds_registry
from odds_asof.selection import select_odds_asof
from projection_consensus.aggregation import build_consensus_rows
from projection_consensus.loader import DEFAULT_TZ, load_snapshot_registry, parse_as_of
from prospective_projection_signal import (
    build_manifest,
    build_projection_signal_rows,
    load_policy,
    summarize_source_state,
)


DEFAULT_CONFIG = PROJECT_ROOT / "config" / "projection_signal_sources.json"


def _timestamp_slug(value: datetime) -> str:
    return value.isoformat().replace(":", "").replace("-", "").replace("+", "")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def run(args: argparse.Namespace) -> dict:
    policy = load_policy(args.config)
    as_of_dt = parse_as_of(args.as_of)
    as_of = as_of_dt.isoformat()
    run_timestamp = datetime.now(DEFAULT_TZ).isoformat()
    run_slug = _timestamp_slug(datetime.now(DEFAULT_TZ))

    projection_registry = load_snapshot_registry(args.projection_registry, project_root=PROJECT_ROOT)
    projection_result = build_consensus_rows(
        registry=projection_registry,
        project_root=PROJECT_ROOT,
        season=args.season,
        week=args.week,
        as_of=as_of,
        sources=list(policy.active_sources),
        min_sources=1,
    )
    source_state = summarize_source_state(
        registry=projection_registry,
        selected_snapshots=projection_result["selected_snapshots"],
        policy=policy,
        season=args.season,
        week=args.week,
    )

    odds_registry = load_odds_registry(args.odds_registry, project_root=PROJECT_ROOT)
    odds_result = select_odds_asof(
        registry=odds_registry,
        project_root=PROJECT_ROOT,
        season=args.season,
        week=args.week,
        as_of=as_of,
        sportsbooks=args.sportsbooks,
    )

    signal_result = build_projection_signal_rows(
        projections=projection_result["selected_source_projections"],
        selected_snapshots=projection_result["selected_snapshots"],
        odds=odds_result["selected_odds"],
        policy=policy,
        season=args.season,
        week=args.week,
        as_of=as_of,
    )

    base_dir = args.output_root / "data" / "analysis" / "prospective_signals" / str(args.season) / f"week_{args.week:02d}"
    snapshot_dir = base_dir / "snapshots"
    diagnostics_dir = base_dir / "diagnostics"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    outputs = {
        "research_rows": str(snapshot_dir / f"projection_signal_rows_{run_slug}.csv"),
        "candidates": str(snapshot_dir / f"projection_signal_candidates_{run_slug}.csv"),
        "source_details": str(snapshot_dir / f"projection_signal_source_details_{run_slug}.csv"),
        "manifest": str(snapshot_dir / f"projection_signal_manifest_{run_slug}.json"),
        "diagnostics": str(diagnostics_dir / f"projection_signal_distribution_{run_slug}.csv"),
        "diagnostics_by_line_type": str(diagnostics_dir / f"projection_signal_distribution_by_line_type_{run_slug}.csv"),
        "candidate_gate_counts": str(diagnostics_dir / f"projection_signal_candidate_gate_counts_{run_slug}.csv"),
        "extreme_alternate_examples": str(diagnostics_dir / f"projection_signal_extreme_alternate_examples_{run_slug}.csv"),
    }

    signal_result["research_rows"].to_csv(outputs["research_rows"], index=False)
    signal_result["candidate_rows"].to_csv(outputs["candidates"], index=False)
    signal_result["source_details"].to_csv(outputs["source_details"], index=False)
    signal_result["diagnostics"].to_csv(outputs["diagnostics"], index=False)
    signal_result["diagnostics_by_line_type"].to_csv(outputs["diagnostics_by_line_type"], index=False)
    signal_result["candidate_gate_counts"].to_csv(outputs["candidate_gate_counts"], index=False)
    signal_result["extreme_alternate_examples"].to_csv(outputs["extreme_alternate_examples"], index=False)

    manifest = build_manifest(
        policy=policy,
        source_state=source_state,
        odds_snapshots=odds_result["selected_snapshots"],
        outputs=outputs,
        season=args.season,
        week=args.week,
        as_of=as_of,
        run_timestamp=run_timestamp,
        research_rows=signal_result["research_rows"],
        candidate_rows=signal_result["candidate_rows"],
    )
    _write_json(Path(outputs["manifest"]), manifest)
    return {
        "manifest": manifest,
        "research_rows": signal_result["research_rows"],
        "candidate_rows": signal_result["candidate_rows"],
        "diagnostics": signal_result["diagnostics"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build prospective source-agnostic projection-signal rows")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--sportsbooks", nargs="*")
    parser.add_argument("--projection-registry", type=Path, default=PROJECT_ROOT / "data" / "processed" / "projections" / "snapshot_registry.csv")
    parser.add_argument("--odds-registry", type=Path, default=PROJECT_ROOT / "data" / "processed" / "odds" / "snapshot_registry.csv")
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    result = run(args)
    manifest = result["manifest"]
    print("[output_manifest]", manifest["outputs"]["manifest"])
    print("[research_rows]", manifest["research_rows"])
    print("[candidate_rows]", manifest["candidate_rows"])
    print("[green_light_rows]", manifest["green_light_rows"])
    print("[green_light_candidates]", manifest["green_light_candidates"])
    print("[available_sources]", "|".join(manifest["source_state"]["available_sources"]))
    print("[required_source_count]", manifest["policy"]["required_source_count"])


if __name__ == "__main__":
    main()
