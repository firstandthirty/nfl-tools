from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pff_content" / "src"))

from pff_content.client import PFFClient  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search PFF player directory for unmatched injury-report players.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    enriched_path = args.run_dir / "pff_enriched_injuries.json"
    rows = json.loads(enriched_path.read_text(encoding="utf-8"))
    unmatched = [row for row in rows if row.get("match_status") == "UNMATCHED"]
    client = PFFClient()
    diagnostics = []
    for row in unmatched:
        params = {"league": "nfl", "name": row["player_name"]}
        response = client.get(
            "/v1/players",
            params=params,
            dataset="player_search",
            season=args.season,
            week=args.week,
            table="players",
            use_cache=True,
        )
        players = response.body.get("players", []) if isinstance(response.body, dict) else []
        exact = [player for player in players if normalize_name(player_name(player)) == normalize_name(row["player_name"])]
        diagnostics.append(
            {
                "team": row["team"],
                "player_name": row["player_name"],
                "source_position": row.get("source_position"),
                "game_status": row.get("game_status"),
                "pff_directory_matches": len(players),
                "pff_exact_name_matches": len(exact),
                "pff_exists": bool(exact),
                "pff_player_ids": "|".join(str(player.get("id")) for player in exact),
                "pff_player_names": "|".join(player_name(player) for player in exact),
                "pff_positions": "|".join(str(player.get("position") or "") for player in exact),
                "pff_current_teams": "|".join(team_abbr(player.get("team")) for player in exact),
                "appears_in_snap_participation": False,
                "likely_unmatched_reason": classify_reason(row, exact),
                "cache_hit": response.cache_hit,
            }
        )
    json_path = args.run_dir / "pff_unmatched_player_search.json"
    csv_path = args.run_dir / "pff_unmatched_player_search.csv"
    json_path.write_text(json.dumps(diagnostics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_csv(csv_path, diagnostics)
    print(json.dumps({"unmatched": len(unmatched), "diagnostics": len(diagnostics), "exists_in_pff_directory": sum(1 for row in diagnostics if row["pff_exists"]), "output_json": str(json_path), "output_csv": str(csv_path)}, indent=2, sort_keys=True))


def player_name(player: dict) -> str:
    first = str(player.get("first_name") or "").strip()
    last = str(player.get("last_name") or "").strip()
    full = f"{first} {last}".strip()
    return full or str(player.get("name") or "").strip()


def team_abbr(team: object) -> str:
    if isinstance(team, dict):
        return str(team.get("abbreviation") or "").strip()
    return ""


def normalize_name(value: str) -> str:
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", str(value).strip().lower())
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    suffixes = {"jr", "sr", "ii", "iii", "iv", "v"}
    parts = text.split()
    while parts and parts[-1] in suffixes:
        parts.pop()
    return " ".join(parts)


def classify_reason(row: dict, exact: list[dict]) -> str:
    if not exact:
        return "not_found_in_pff_player_search"
    if row.get("source_position") in {"K", "P", "LS"}:
        return "directory_match_no_snap_participation_specialist_or_no_week1_2_usage"
    return "directory_match_no_week1_2_snap_participation"


def write_csv(path: Path, rows: list[dict]) -> None:
    columns = [
        "team",
        "player_name",
        "source_position",
        "game_status",
        "pff_directory_matches",
        "pff_exact_name_matches",
        "pff_exists",
        "pff_player_ids",
        "pff_player_names",
        "pff_positions",
        "pff_current_teams",
        "appears_in_snap_participation",
        "likely_unmatched_reason",
        "cache_hit",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


if __name__ == "__main__":
    main()
