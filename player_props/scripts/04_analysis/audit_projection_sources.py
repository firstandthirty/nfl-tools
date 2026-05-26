import argparse
import json
import re
from io import StringIO
from pathlib import Path

import pandas as pd


OUT_FILE = Path("data/analysis/diagnostics/projection_source_inventory.csv")
POSITIONS = {"RB", "WR", "TE"}
ROSTER_CHECKS = {
    "Derrick Henry": "TEN",
    "Saquon Barkley": "NYG",
    "Stefon Diggs": "BUF",
    "Keenan Allen": "LAC",
}


def clean_name(value):
    text = str(value).lower().replace(".", "").replace("'", "")
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", text)
    return " ".join(text.split()).strip()


def summarize_range(values):
    values = pd.to_numeric(values, errors="coerce").dropna().astype(int).sort_values().unique()
    return ",".join(str(v) for v in values)


def parse_player_team(value):
    parts = str(value).strip().split()
    if len(parts) < 2:
        return str(value).strip(), None
    return " ".join(parts[:-1]), parts[-1].upper()


def normalize_projection_frame(df):
    frame = df.copy()
    player_col = next((c for c in ["player", "player_name", "player_clean"] if c in frame.columns), None)
    if not player_col:
        return pd.DataFrame()
    frame["player"] = frame[player_col].astype(str)
    if "player_clean" not in frame.columns:
        frame["player_clean"] = frame["player"].map(clean_name)
    if "team" not in frame.columns:
        frame["team"] = pd.NA
    if "position" not in frame.columns:
        frame["position"] = pd.NA
    return frame


def load_csv_candidate(path):
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception as exc:
        return None, f"read error: {exc}"

    columns = set(df.columns)
    filename = path.name.lower()
    direct_receiving = "fp_receiving_yds" in columns
    other_projection_source = (
        ("projection" in filename or "fantasypros" in filename or "ffa" in filename)
        and "season" in columns and "week" in columns
        and any(c in columns for c in ["player", "player_name", "player_clean"])
    )
    if not direct_receiving and not other_projection_source:
        return None, None

    return normalize_projection_frame(df), None


def load_raw_web():
    root = Path("data/raw/fantasypros/receiving_web")
    rows = []
    for path in sorted(root.rglob("fantasypros_*_*.html")):
        match = re.search(r"fantasypros_(rb|wr|te)_(\d{4})_week_(\d+)\.html$", path.name, re.I)
        if not match:
            continue
        position, season, week = match.group(1).upper(), int(match.group(2)), int(match.group(3))
        try:
            tables = pd.read_html(StringIO(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        for table in tables:
            if not isinstance(table.columns, pd.MultiIndex):
                continue
            player_col = next((c for c in table.columns if str(c[-1]).upper() == "PLAYER"), None)
            rec_yds_col = next(
                (c for c in table.columns if str(c[0]).upper() == "RECEIVING" and str(c[-1]).upper() == "YDS"),
                None,
            )
            if player_col is None or rec_yds_col is None:
                continue
            for _, row in table.iterrows():
                player, team = parse_player_team(row[player_col])
                rows.append(
                    {
                        "season": season,
                        "week": week,
                        "position": position,
                        "player": player,
                        "player_clean": clean_name(player),
                        "team": team,
                        "fp_receiving_yds": pd.to_numeric(row[rec_yds_col], errors="coerce"),
                    }
                )
            break
    return pd.DataFrame(rows)


def load_raw_api():
    root = Path("data/raw/fantasypros/api_weekly_projections")
    rows = []
    for path in sorted(root.glob("fantasypros_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        season = data.get("season")
        week = data.get("week")
        for player in data.get("players", []):
            stats = player.get("stats") or {}
            rows.append(
                {
                    "season": season,
                    "week": week,
                    "position": player.get("position_id") or data.get("positions"),
                    "player": player.get("name"),
                    "player_clean": clean_name(player.get("name")),
                    "team": player.get("team_id"),
                    "fp_receiving_yds": stats.get("rec_yds"),
                }
            )
    return pd.DataFrame(rows)


def roster_team(frame, player_name):
    if frame.empty or not {"player_clean", "team"}.issubset(frame.columns):
        return ""
    target = clean_name(player_name)
    match = frame.loc[frame["player_clean"].eq(target), "team"].dropna().astype(str).drop_duplicates()
    return "|".join(sorted(match)) if len(match) else ""


def assess_source(source_name, source_type, path, frame, notes=""):
    columns = list(frame.columns) if not frame.empty else []
    has_stat = "fp_receiving_yds" in columns and pd.to_numeric(frame["fp_receiving_yds"], errors="coerce").notna().any()
    has_2023 = not frame.empty and pd.to_numeric(frame.get("season"), errors="coerce").eq(2023).any()
    week_one = frame.loc[
        pd.to_numeric(frame.get("season"), errors="coerce").eq(2023)
        & pd.to_numeric(frame.get("week"), errors="coerce").eq(1)
        & frame["position"].astype(str).str.upper().isin(POSITIONS)
    ].copy() if has_2023 else pd.DataFrame()

    teams = {player: roster_team(week_one, player) for player in ROSTER_CHECKS}
    passed = sum(teams[player] == expected for player, expected in ROSTER_CHECKS.items())
    wrong = [f"{player}={teams[player] or 'missing'} expected {expected}" for player, expected in ROSTER_CHECKS.items() if teams[player] and teams[player] != expected]
    missing = [player for player in ROSTER_CHECKS if not teams[player]]

    if not has_stat:
        viability = "not_usable_missing_fp_receiving_yds"
    elif not has_2023:
        viability = "not_usable_no_2023_rows"
    elif wrong:
        viability = "invalid_hindsight_roster_assignments"
    elif missing:
        viability = "inconclusive_missing_roster_checks"
    else:
        viability = "viable_2023_roster_checks_passed"

    detail = "; ".join(filter(None, [notes, "; ".join(wrong), f"missing checks: {', '.join(missing)}" if missing else ""]))
    result = {
        "source_name": source_name,
        "source_type": source_type,
        "path": str(path),
        "row_count": len(frame),
        "seasons": summarize_range(frame["season"]) if "season" in frame else "",
        "weeks_2023": summarize_range(frame.loc[pd.to_numeric(frame.get("season"), errors="coerce").eq(2023), "week"]) if has_2023 else "",
        "relevant_columns": ", ".join(c for c in ["season", "week", "position", "player", "team", "fp_receiving_yds"] if c in columns),
        "has_fp_receiving_yds": has_stat,
        "week1_rb_wr_te_rows_2023": len(week_one),
        "derrick_henry_team_2023_w1": teams["Derrick Henry"] or "NOT_FOUND",
        "saquon_barkley_team_2023_w1": teams["Saquon Barkley"] or "NOT_FOUND",
        "stefon_diggs_team_2023_w1": teams["Stefon Diggs"] or "NOT_FOUND",
        "keenan_allen_team_2023_w1": teams["Keenan Allen"] or "NOT_FOUND",
        "roster_checks_passed": passed,
        "viability": viability,
        "notes": detail,
    }
    return result, week_one


def find_csv_candidates():
    for path in sorted(Path("data").rglob("*.csv")):
        if path == OUT_FILE:
            continue
        frame, error = load_csv_candidate(path)
        if frame is not None:
            yield path, frame, error or ""


def print_sample(name, sample):
    if sample.empty:
        print(f"\n{name}: no 2023 Week 1 RB/WR/TE sample rows")
        return
    cols = [c for c in ["position", "player", "team", "fp_receiving_yds"] if c in sample.columns]
    print(f"\n{name}: 2023 Week 1 RB/WR/TE sample")
    print(sample.groupby("position", sort=True, group_keys=False).head(4)[cols].to_string(index=False))


def main():
    parser = argparse.ArgumentParser(description="Audit local projection sources for valid historical receiving-yard inputs.")
    parser.add_argument("--output", type=Path, default=OUT_FILE)
    args = parser.parse_args()

    results = []
    samples = {}

    for path, frame, notes in find_csv_candidates():
        result, sample = assess_source(path.name, "csv", path, frame, notes)
        results.append(result)
        if "fantasypros" in path.name.lower() or result["has_fp_receiving_yds"]:
            samples[result["source_name"]] = sample

    raw_sources = [
        ("fantasypros_receiving_web_raw_html", "raw_html_collection", Path("data/raw/fantasypros/receiving_web"), load_raw_web()),
        ("fantasypros_api_weekly_raw_json", "raw_json_collection", Path("data/raw/fantasypros/api_weekly_projections"), load_raw_api()),
    ]
    for name, kind, path, frame in raw_sources:
        result, sample = assess_source(name, kind, path, frame)
        results.append(result)
        samples[name] = sample

    inventory = pd.DataFrame(results).sort_values(["viability", "source_name"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    inventory.to_csv(args.output, index=False)

    print("===== PROJECTION SOURCE INVENTORY =====")
    display_cols = [
        "source_name", "source_type", "row_count", "seasons", "weeks_2023",
        "derrick_henry_team_2023_w1", "saquon_barkley_team_2023_w1",
        "stefon_diggs_team_2023_w1", "keenan_allen_team_2023_w1", "viability",
    ]
    print(inventory[display_cols].to_string(index=False))
    for name, sample in samples.items():
        print_sample(name, sample)

    viable = inventory.loc[inventory["viability"].eq("viable_2023_roster_checks_passed") & inventory["has_fp_receiving_yds"]]
    print(f"\n[saved] {args.output}")
    if viable.empty:
        print("\nCONCLUSION: No valid local 2023 fp_receiving_yds projection source was identified.")
        print("Options: obtain true historical FantasyPros weekly projections; use another validated historical projection source; or limit expanded 2023 work to props/context/actual analysis.")
    else:
        print("\nVIABLE 2023 SOURCES:")
        print(viable[["source_name", "path"]].to_string(index=False))


if __name__ == "__main__":
    main()
