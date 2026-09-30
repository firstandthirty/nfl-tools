from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pff_content.snap_participation import build_week_snap_participation, write_week_snap_participation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build true PFF player snap participation from processed summary datasets.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = write_week_snap_participation(args.season, args.week)
    df = build_week_snap_participation(args.season, args.week)
    print(
        json.dumps(
            {
                "season": args.season,
                "week": args.week,
                "output": str(path),
                "rows": len(df),
                "players": int(df["player_id"].nunique()) if not df.empty else 0,
                "offense_rows": int((df["offensive_snaps"] > 0).sum()) if not df.empty else 0,
                "defense_rows": int((df["defensive_snaps"] > 0).sum()) if not df.empty else 0,
                "special_rows": int((df["special_teams_snaps"] > 0).sum()) if not df.empty else 0,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
