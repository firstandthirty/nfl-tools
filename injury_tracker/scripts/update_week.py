from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .injury_schema import PROJECT_ROOT, load_teams
from .nfl_reserve_transactions import (
    attach_events_to_current_reserves,
    enriched_reserve_columns,
    reconciliation_columns,
    write_csv,
)
from .official_injury_reports import run_ingestion as run_injury_ingestion
from .official_roster_reserves import run_ingestion as run_reserve_ingestion
from .pff_enrichment import enrich_official_run
from .review import load_review_bundle
from .schedule_context import load_schedule_context
from .week_config import resolve_season_week


REPO_ROOT = PROJECT_ROOT.parent
PFF_ROOT = REPO_ROOT / "pff_content"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update injury tracker data for one NFL week.")
    parser.add_argument("--season", type=int)
    parser.add_argument("--week", type=int)
    parser.add_argument("--config", type=Path, help="JSON file with season/week. Defaults to injury_tracker/config/current_week.json.")
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--skip-live-fetch", action="store_true", help="For tests only: do not fetch live injury/roster sources.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    season, week = resolve_season_week(args)
    summary = update_week(
        season=season,
        week=week,
        delay_seconds=args.delay,
        timeout=args.timeout,
        retries=args.retries,
        skip_live_fetch=args.skip_live_fetch,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


def update_week(
    *,
    season: int,
    week: int,
    delay_seconds: float = 0.25,
    timeout: int = 25,
    retries: int = 2,
    skip_live_fetch: bool = False,
) -> dict[str, Any]:
    stages: list[dict[str, Any]] = []
    contexts = [context for context in load_schedule_context() if context.season == season and context.week == week]
    stages.append({"stage": "schedule_context", "teams": len(contexts), "games": len({context.game_id if hasattr(context, "game_id") else tuple(sorted([context.team, context.opponent])) for context in contexts})})

    pff_stage = ensure_current_season_pff(season, week)
    stages.append({"stage": "pff_participation", **pff_stage})

    if skip_live_fetch:
        review = load_review_bundle(season, week)
        stages.append({"stage": "review_population", "summary": review["summary"]})
        return {"season": season, "week": week, "stages": stages, "review_output_dir": str(review["paths"].output_dir)}

    teams = [team["abbr"] for team in load_teams()]
    injury_dir, injury_records, injury_manifest = run_injury_ingestion(
        season=season,
        week=week,
        selected_team_abbrs=teams,
        delay_seconds=delay_seconds,
        timeout=timeout,
        retries=retries,
    )
    stages.append({"stage": "official_injury_reports", **injury_summary(injury_dir, injury_records, injury_manifest)})

    _enriched, pff_manifest, official_dir = enrich_official_run(season=season, week=week, official_run_dir=injury_dir)
    stages.append({"stage": "pff_injury_enrichment", **pff_manifest_summary(pff_manifest), "output_dir": str(official_dir)})

    reserve_dir, reserve_records, reserve_manifest = run_reserve_ingestion(
        season=season,
        week=week,
        selected_team_abbrs=teams,
        delay_seconds=delay_seconds,
        timeout=timeout,
        retries=retries,
    )
    stages.append({"stage": "official_roster_reserves", **reserve_summary(reserve_dir, reserve_records, reserve_manifest)})

    tx_stage = attach_existing_transactions(reserve_dir, season=season)
    stages.append({"stage": "reserve_transaction_history", **tx_stage})

    review = load_review_bundle(season, week)
    stages.append({"stage": "review_population", "summary": review["summary"], "output_dir": str(review["paths"].output_dir)})
    summary = {"season": season, "week": week, "stages": stages, "review_output_dir": str(review["paths"].output_dir)}
    (review["paths"].output_dir / "update_week_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def ensure_current_season_pff(season: int, week: int) -> dict[str, Any]:
    through_week = week - 1
    results = []
    for pff_week in range(1, through_week + 1):
        snap_path = PFF_ROOT / "data" / "processed" / "pff" / str(season) / f"week_{pff_week:02d}" / "snap_participation.csv"
        if snap_path.exists():
            results.append({"week": pff_week, "snap_participation": "exists", "path": str(snap_path)})
            continue
        processed_dir = PFF_ROOT / "data" / "processed" / "pff" / str(season) / f"week_{pff_week:02d}"
        if not (processed_dir / "offense_summary.csv").exists() or not (processed_dir / "defense_summary.csv").exists() or not (processed_dir / "special_summary.csv").exists():
            run_pff_command(["py", "scripts\\fetch_week.py", "--season", str(season), "--week", str(pff_week)])
            run_pff_command(["py", "scripts\\build_processed_week.py", "--season", str(season), "--week", str(pff_week), "--fetch-missing"])
        run_pff_command(["py", "scripts\\build_snap_participation.py", "--season", str(season), "--week", str(pff_week)])
        results.append({"week": pff_week, "snap_participation": "built", "path": str(snap_path)})
    return {"through_week": through_week, "weeks": results}


def run_pff_command(command: list[str]) -> None:
    subprocess.run(command, cwd=PFF_ROOT, check=True)


def attach_existing_transactions(reserve_dir: Path, *, season: int) -> dict[str, Any]:
    transaction_path = latest_existing_transaction_file(season)
    current_reserves = json.loads((reserve_dir / "reserve_players.json").read_text(encoding="utf-8"))
    if transaction_path is None:
        events: list[dict[str, Any]] = []
    else:
        events = json.loads(transaction_path.read_text(encoding="utf-8"))
    enriched_reserves, reconciliation_rows = attach_events_to_current_reserves(current_reserves, events)
    (reserve_dir / "reserve_players_with_transaction_history.json").write_text(json.dumps(enriched_reserves, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (reserve_dir / "reserve_transaction_reconciliation.json").write_text(json.dumps(reconciliation_rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_csv(reserve_dir / "reserve_players_with_transaction_history.csv", enriched_reserves, enriched_reserve_columns())
    write_csv(reserve_dir / "reserve_transaction_reconciliation.csv", reconciliation_rows, reconciliation_columns())
    return {
        "transaction_source": str(transaction_path) if transaction_path else None,
        "transaction_events": len(events),
        "reserve_players_with_transaction_history": len(enriched_reserves),
    }


def latest_existing_transaction_file(season: int) -> Path | None:
    candidates = list((PROJECT_ROOT / "data" / "processed" / str(season)).glob("week_*/*/nfl_reserve_transactions.json"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def injury_summary(out_dir: Path, records: list[dict[str, Any]], manifest: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "output_dir": str(out_dir),
        "teams": len(manifest),
        "records": len(records),
        "fetch_ok": sum(1 for item in manifest if item["fetch_status"] == "OK"),
        "parse_ok": sum(1 for item in manifest if item["parse_status"] == "OK"),
        "current": sum(1 for item in manifest if item["current_week_status"] == "SUCCESS_CURRENT"),
        "no_report_yet": sum(1 for item in manifest if item["current_week_status"] == "NO_REPORT_YET"),
        "stale": sum(1 for item in manifest if item["current_week_status"] == "SUCCESS_BUT_STALE"),
        "parse_failed": sum(1 for item in manifest if item["parse_status"] == "PARSE_FAILED"),
        "fetch_failed": sum(1 for item in manifest if item["fetch_status"] != "OK"),
        "match_mismatch": sum(1 for item in manifest if item.get("match_validation") == "MATCH_MISMATCH"),
    }


def pff_manifest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "official_meaningful_players": manifest["total_meaningful_injured_players"],
        "pff_matched": manifest["pff_matched"],
        "review_required": manifest["review_required_matches"],
        "unmatched": manifest["unmatched"],
        "candidate_yes": manifest["candidates"],
        "candidate_no": manifest["non_candidates"],
    }


def reserve_summary(out_dir: Path, records: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "output_dir": str(out_dir),
        "teams": len(manifest["teams_requested"]),
        "fetch_ok": manifest["fetch_ok"],
        "parse_ok": manifest["parse_ok"],
        "injury_related_reserve_players": len(records),
        "pff_identity_matched": manifest["pff"]["pff_identity_matched"],
        "pff_review_required": manifest["pff"]["pff_identity_review_required"],
        "pff_unmatched": manifest["pff"]["pff_identity_unmatched"],
        "candidates": manifest["pff"]["candidates"],
        "prior_season_fallback_promotions": manifest["pff"].get("prior_season_fallback_promotions"),
    }


if __name__ == "__main__":
    main()
