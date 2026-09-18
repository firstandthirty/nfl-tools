from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pff_content.cache import RawCache
from pff_content.client import PFFClient
from pff_content.datasets import DATASETS, dataset_by_name
from pff_content.week_status import (
    completeness_from_games_body,
    decide_cache_policy,
    read_week_status,
    status_summary,
    write_week_status,
)


PARAMS_KEYS = {"league": "nfl"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch cached PFF weekly raw datasets.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args()


def weekly_params(season: int, week: int) -> dict[str, object]:
    return {"league": "nfl", "season": season, "week": week}


def all_week_cache_exists(cache: RawCache, season: int, week: int) -> bool:
    params = weekly_params(season, week)
    for spec in DATASETS:
        body_path, _ = cache.paths(season=season, week=week, dataset=spec.name, path=spec.endpoint, params=params)
        if not body_path.exists():
            return False
    return True


def cached_games_status(cache: RawCache, season: int, week: int):
    games = dataset_by_name("games")
    body = cache.read(season=season, week=week, dataset=games.name, path=games.endpoint, params=weekly_params(season, week))
    if body is None:
        return None
    return completeness_from_games_body(body, season=season, week=week)


def fetch_all(client: PFFClient, season: int, week: int, *, use_cache: bool) -> tuple[list[dict[str, object]], int, int, object]:
    params = weekly_params(season, week)
    rows = []
    api_calls = 0
    cache_hits = 0
    games_body = None
    for spec in DATASETS:
        response = client.get(
            spec.endpoint,
            params=params,
            dataset=spec.name,
            season=season,
            week=week,
            table=spec.table,
            use_cache=use_cache,
        )
        table_rows = response.body.get(spec.table, []) if isinstance(response.body, dict) else []
        api_calls += 0 if response.cache_hit else 1
        cache_hits += 1 if response.cache_hit else 0
        rows.append({"dataset": spec.name, "status": response.status, "cache_hit": response.cache_hit, "rows": len(table_rows)})
        if spec.name == "games":
            games_body = response.body
    return rows, api_calls, cache_hits, games_body


def print_status_message(status, *, transition_complete: bool = False, finalized_reuse: bool = False) -> None:
    if finalized_reuse:
        print(f"Week {status.week} finalized cache found.")
        print("Using cached data.")
        return
    if status.is_complete:
        print(f"Week {status.week} is now fully processed by PFF." if transition_complete else f"Week {status.week} is fully processed by PFF.")
        print(f"{status.games_with_stats}/{status.total_games} games have stats.")
        if transition_complete:
            print("Refreshing all weekly datasets to create a consistent finalized snapshot.")
        return
    print(f"Week {status.week} is not fully processed by PFF.")
    print(f"{status.games_with_stats}/{status.total_games} games currently have stats.")
    if status.incomplete_matchups:
        print("Missing stats:")
        for matchup in status.incomplete_matchups:
            print(f"* {matchup}")
    print("Cached data should be treated as provisional.")


def main() -> None:
    args = parse_args()
    client = PFFClient()
    cache = RawCache()
    saved_status = read_week_status(args.season, args.week)
    cached_status = cached_games_status(cache, args.season, args.week)
    cache_exists = all_week_cache_exists(cache, args.season, args.week)
    policy = decide_cache_policy(
        refresh=args.refresh,
        all_cache_exists=cache_exists,
        saved_status=saved_status,
        cached_games_status=cached_status,
    )
    api_calls = 0
    cache_hits = 0
    rows: list[dict[str, object]] = []
    final_status = saved_status or cached_status

    if policy == "reuse_finalized" and final_status is not None:
        rows, api_calls, cache_hits, games_body = fetch_all(client, args.season, args.week, use_cache=True)
        final_status = completeness_from_games_body(games_body, season=args.season, week=args.week, data_fetched_at=final_status.data_fetched_at) if games_body else final_status
        write_week_status(final_status)
        print_status_message(final_status, finalized_reuse=True)
    elif policy in {"refresh_all", "fetch_all"}:
        rows, api_calls, cache_hits, games_body = fetch_all(client, args.season, args.week, use_cache=False)
        final_status = completeness_from_games_body(games_body, season=args.season, week=args.week, data_fetched_at=final_status.checked_at if final_status else None)
        write_week_status(final_status)
        print_status_message(final_status)
    else:
        games = dataset_by_name("games")
        current_games = client.get(
            games.endpoint,
            params=weekly_params(args.season, args.week),
            dataset=games.name,
            season=args.season,
            week=args.week,
            table=games.table,
            use_cache=False,
        )
        api_calls += 1
        current_status = completeness_from_games_body(current_games.body, season=args.season, week=args.week)
        policy = decide_cache_policy(
            refresh=args.refresh,
            all_cache_exists=cache_exists,
            saved_status=saved_status,
            cached_games_status=cached_status,
            current_games_status=current_status,
        )
        if policy == "refresh_all_finalized":
            print_status_message(current_status, transition_complete=True)
            rows, refresh_api_calls, refresh_cache_hits, games_body = fetch_all(client, args.season, args.week, use_cache=False)
            api_calls += refresh_api_calls
            cache_hits += refresh_cache_hits
            final_status = completeness_from_games_body(games_body, season=args.season, week=args.week, data_fetched_at=current_status.checked_at)
            write_week_status(final_status)
        else:
            final_status = current_status
            write_week_status(final_status)
            print_status_message(final_status)
            rows, reuse_api_calls, reuse_cache_hits, _ = fetch_all(client, args.season, args.week, use_cache=True)
            api_calls += reuse_api_calls
            cache_hits += reuse_cache_hits

    print(json.dumps({"season": args.season, "week": args.week, "api_calls": api_calls, "cache_hits": cache_hits, "week_status": final_status.to_dict() if final_status else None, "datasets": rows}, indent=2))


if __name__ == "__main__":
    main()
