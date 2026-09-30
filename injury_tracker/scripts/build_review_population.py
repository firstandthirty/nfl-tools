from __future__ import annotations

import argparse
import json

try:
    from .review import load_review_bundle
except ImportError:  # pragma: no cover
    from review import load_review_bundle  # type: ignore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build injury tracker review population and reviewed outputs.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    bundle = load_review_bundle(args.season, args.week)
    print(json.dumps(bundle["summary"], indent=2, sort_keys=True))
    print(f"Reviewed outputs: {bundle['paths'].output_dir}")


if __name__ == "__main__":
    main()
