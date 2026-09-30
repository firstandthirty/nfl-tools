from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pff_enrichment import enrich_official_run, latest_official_run_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enrich canonical official injury records with processed PFF identity and usage.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--official-run-dir", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_dir = args.official_run_dir or latest_official_run_dir(args.season, args.week)
    _records, manifest, out_dir = enrich_official_run(
        season=args.season,
        week=args.week,
        official_run_dir=run_dir,
    )
    print(
        json.dumps(
            {
                "output_dir": str(out_dir),
                "official_meaningful_players": manifest["total_meaningful_injured_players"],
                "pff_matched": manifest["pff_matched"],
                "exact_matches": manifest["exact_matches"],
                "normalized_matches": manifest["normalized_matches"],
                "persisted_matches": manifest["persisted_matches"],
                "review_required": manifest["review_required_matches"],
                "unmatched": manifest["unmatched"],
                "candidate_yes": manifest["candidates"],
                "candidate_no": manifest["non_candidates"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
