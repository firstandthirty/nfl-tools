from __future__ import annotations

import argparse
import json

from .injury_schema import load_teams, validate_team_abbr
from .official_injury_reports import run_ingestion


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch and parse official NFL team injury reports.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--team", action="append", help="Team abbreviation. May be supplied more than once.")
    parser.add_argument("--all", action="store_true", help="Fetch all configured teams.")
    parser.add_argument("--delay", type=float, default=0.25, help="Delay in seconds between team requests.")
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--retries", type=int, default=2)
    return parser.parse_args()


def selected_teams(args: argparse.Namespace) -> list[str]:
    if args.all:
        return [team["abbr"] for team in load_teams()]
    if not args.team:
        raise ValueError("Supply --team at least once or use --all.")
    return [validate_team_abbr(team) for team in args.team]


def main() -> None:
    args = parse_args()
    out_dir, records, manifest = run_ingestion(
        season=args.season,
        week=args.week,
        selected_team_abbrs=selected_teams(args),
        delay_seconds=args.delay,
        timeout=args.timeout,
        retries=args.retries,
    )
    summary = {
        "output_dir": str(out_dir),
        "teams": len(manifest),
        "records": len(records),
        "source_rows": sum(item.get("parsed_source_rows", 0) for item in manifest),
        "meaningful_injury_records": sum(item.get("meaningful_injury_records", item.get("players_found", 0)) for item in manifest),
        "fetch_ok": sum(1 for item in manifest if item["fetch_status"] == "OK"),
        "parse_ok": sum(1 for item in manifest if item["parse_status"] == "OK"),
        "current": sum(1 for item in manifest if item["current_week_status"] == "SUCCESS_CURRENT"),
        "match_confirmed": sum(1 for item in manifest if item.get("match_validation") == "MATCH_CONFIRMED"),
        "match_context_unavailable": sum(1 for item in manifest if item.get("match_validation") == "MATCH_CONTEXT_UNAVAILABLE"),
        "match_mismatch": sum(1 for item in manifest if item.get("match_validation") == "MATCH_MISMATCH"),
        "no_report_yet": sum(1 for item in manifest if item["current_week_status"] == "NO_REPORT_YET"),
        "stale": sum(1 for item in manifest if item["current_week_status"] == "SUCCESS_BUT_STALE"),
        "parse_failed": sum(1 for item in manifest if item["parse_status"] == "PARSE_FAILED"),
        "fetch_failed": sum(1 for item in manifest if item["fetch_status"] != "OK"),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
