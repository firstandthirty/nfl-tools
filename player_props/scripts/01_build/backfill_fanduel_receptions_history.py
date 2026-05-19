from pathlib import Path
import argparse
import os
import json
import shutil
import time
from datetime import datetime, timedelta, timezone

import requests
import pandas as pd
from dotenv import load_dotenv


load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")
if not API_KEY:
    raise RuntimeError("ODDS_API_KEY not found in .env")

SPORT = "americanfootball_nfl"
BOOKMAKER = "fanduel"
MARKET = "player_receptions"

SEASONS = [2023, 2024, 2025]

RAW_DIR = Path("data/raw/odds_api/fanduel_receptions")
OUT_FILE = Path("data/processed/fanduel_receptions_history.csv")
EVENT_SOURCE_FILE = Path("data/processed/merged_props_with_rolling.csv")
ARCHIVE_DIR = OUT_FILE.parent / "archive"

REQUEST_SLEEP = 1.05
LAST_API_HEADERS = {"remaining": None, "used": None, "last": None}
DEBUG_EVENT_LOGGED = False


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def season_date_range(season):
    # Use NFL season window: include September of season through mid-February of next calendar year
    # This ensures Week 18 (played in early January) and potential late Jan games are included.
    start = f"{season}-09-01"
    end = f"{season+1}-02-15"
    return start, end


def estimate_week_from_commence(commence_time_iso, season):
    if not commence_time_iso:
        return None
    try:
        commence = datetime.fromisoformat(commence_time_iso.replace("Z", "+00:00")).date()
        start_str, _ = season_date_range(season)
        season_start = datetime.fromisoformat(start_str).date()
        delta = (commence - season_start).days
        if delta < 0:
            return 1
        return delta // 7 + 1
    except Exception:
        return None


def daterange(start_date, end_date):
    start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def get_json(url, params, raw_file):
    if raw_file.exists():
        try:
            data = json.loads(raw_file.read_text(encoding="utf-8"))
            return data, True
        except json.JSONDecodeError:
            print(f"[cache] invalid cached response {raw_file}, refetching")

    attempts = 3
    for attempt in range(1, attempts + 1):
        r = requests.get(url, params=params, timeout=30)

        LAST_API_HEADERS["remaining"] = r.headers.get("x-requests-remaining")
        LAST_API_HEADERS["used"] = r.headers.get("x-requests-used")
        LAST_API_HEADERS["last"] = r.headers.get("x-requests-last")

        print(
            f"[status] {r.status_code} "
            f"remaining={LAST_API_HEADERS['remaining']} "
            f"used={LAST_API_HEADERS['used']} "
            f"cost={LAST_API_HEADERS['last']}"
        )

        if r.status_code == 200:
            data = r.json()
            raw_file.parent.mkdir(parents=True, exist_ok=True)
            raw_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            time.sleep(REQUEST_SLEEP)
            return data, False

        payload = {"status": r.status_code, "body": r.text}
        raw_file.parent.mkdir(parents=True, exist_ok=True)
        raw_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        if r.status_code == 404:
            print(f"[warn] 404 not found for {url}")
            return payload, False

        if r.status_code == 429 or 500 <= r.status_code < 600:
            if attempt < attempts:
                backoff = REQUEST_SLEEP * attempt
                print(f"[retry] attempt={attempt} backoff={backoff:.1f}s")
                time.sleep(backoff)
                continue

        r.raise_for_status()

    raise RuntimeError(f"Failed to fetch {url} after {attempts} attempts")


def fetch_events_for_date(day):
    date_str = iso(day + timedelta(hours=12))

    url = f"https://api.the-odds-api.com/v4/historical/sports/{SPORT}/events"
    params = {
        "apiKey": API_KEY,
        "date": date_str,
    }

    raw_file = RAW_DIR / "events" / f"events_{day.date()}.json"

    print(f"[events] {day.date()}")

    data, cached = get_json(url, params, raw_file)

    events = data.get("data", data)
    if not isinstance(events, list):
        return []

    # Keep events commencing on this UTC date or nearby.
    return events


def load_events_from_existing_props(seasons=None):
    if not EVENT_SOURCE_FILE.exists():
        raise FileNotFoundError(f"Missing event source file: {EVENT_SOURCE_FILE}")

    df = pd.read_csv(EVENT_SOURCE_FILE)
    df = df[df["sport_key"] == SPORT].copy()

    if seasons is not None:
        df = df[df["season"].isin(seasons)]

    keep = [
        "event_id",
        "commence_time",
        "home_team",
        "away_team",
        "season",
        "week",
    ]

    events = (
        df[keep]
        .dropna(subset=["event_id", "commence_time"])
        .drop_duplicates("event_id")
        .rename(columns={"event_id": "id"})
        .to_dict("records")
    )

    return events


def fetch_event_odds(event):
    global DEBUG_EVENT_LOGGED

    event_id = event["id"]
    commence_time = datetime.fromisoformat(
        event["commence_time"].replace("Z", "+00:00")
    )
    snapshot_time = commence_time - timedelta(minutes=90)

    url = (
        f"https://api.the-odds-api.com/v4/historical/"
        f"sports/{SPORT}/events/{event_id}/odds"
    )

    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": MARKET,
        "bookmakers": BOOKMAKER,
        "date": iso(snapshot_time),
    }

    raw_file = RAW_DIR / "event_odds_v2_props_only" / f"{event_id}_{iso(snapshot_time).replace(':', '')}.json"

    print(
        f"[odds] {event.get('away_team')} @ {event.get('home_team')} "
        f"kickoff={event.get('commence_time')} snapshot={iso(snapshot_time)}"
    )

    if not DEBUG_EVENT_LOGGED:
        print(f"[prop_request] url={url}")
        print(
            f"[prop_request] markets={params['markets']} "
            f"bookmakers={params['bookmakers']} regions={params['regions']} "
            f"date={params['date']}"
        )

    prop_data, _ = get_json(url, params, raw_file)

    event_data = prop_data.get("data", {})
    books = event_data.get("bookmakers", [])

    prop_rows_exist = False
    market_keys = set()

    for book in books:
        for market in book.get("markets", []):
            market_keys.add(market.get("key"))
            if market.get("key") == MARKET and market.get("outcomes"):
                prop_rows_exist = True

    print(f"[prop_response] market_keys={sorted(market_keys)}")

    if not prop_rows_exist:
        print("[skip] no target prop market found; skipping context request")
        return prop_data, None

    context_data = fetch_event_odds_context(event_id, snapshot_time)

    return prop_data, context_data

def fetch_event_odds_context(event_id, snapshot_time):
    """Fetch spreads/totals/h2h for the same event/snapshot in separate request"""
    url = (
        f"https://api.the-odds-api.com/v4/historical/"
        f"sports/{SPORT}/events/{event_id}/odds"
    )

    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": "spreads,totals,h2h",
        # Don't filter to single bookmaker for context, try all available
        "date": iso(snapshot_time),
    }

    raw_file = RAW_DIR / "event_odds_context" / f"{event_id}_{iso(snapshot_time).replace(':', '')}.json"

    print(f"[context_request] markets={params.get('markets')} bookmakers=all regions={params.get('regions')} date={params.get('date')}")

    try:
        data, cached = get_json(url, params, raw_file)
        
        event_data = data.get("data", {})
        bookmakers = event_data.get("bookmakers", [])
        response_markets = set()
        for book in bookmakers:
            for market in book.get("markets", []):
                response_markets.add(market.get("key"))
        
        print(f"[context_response] market_keys={sorted(response_markets)}")
        return data
    except Exception as e:
        print(f"[context_request] failed: {e}")
        return None


def merge_context_into_props(props_data, context_data):
    """Merge game context bookmakers into props response.
    If FanDuel exists in both, merge markets into the existing FanDuel bookmaker.
    Otherwise append new bookmakers.
    """
    global DEBUG_EVENT_LOGGED
    try:
        props_event = props_data.get("data", {})
        context_event = context_data.get("data", {})
        
        context_bookmakers = context_event.get("bookmakers", [])
        props_bookmakers = props_event.get("bookmakers", [])
        
        # Find FanDuel in both responses
        props_fd = None
        context_fd = None
        for i, book in enumerate(props_bookmakers):
            if book.get("key") == BOOKMAKER:
                props_fd = book
                break
        for book in context_bookmakers:
            if book.get("key") == BOOKMAKER:
                context_fd = book
                break
        
        # If FanDuel in both, merge markets into existing FanDuel from props
        if props_fd and context_fd:
            existing_market_keys = {m.get("key") for m in props_fd.get("markets", [])}
            for market in context_fd.get("markets", []):
                if market.get("key") not in existing_market_keys:
                    props_fd.get("markets", []).append(market)
        
        # Append context bookmakers that don't exist in props
        added_books = {book.get("key") for book in props_bookmakers}
        for book in context_bookmakers:
            if book.get("key") not in added_books:
                props_bookmakers.append(book)
        
        props_event["bookmakers"] = props_bookmakers
        props_data["data"] = props_event
        
        # Debug: print merged bookmaker structure for first event
        if DEBUG_EVENT_LOGGED and not hasattr(merge_context_into_props, "_debug_printed"):
            merge_context_into_props._debug_printed = True
            print(f"[merge_context] total bookmakers after merge: {len(props_bookmakers)}")
            for book in props_bookmakers:
                mkeys = sorted([m.get("key") for m in book.get("markets", [])])
                print(f"[merge_context]   {book.get('key')}: markets={mkeys}")
            # Show FanDuel in detail if it exists
            for book in props_bookmakers:
                if book.get("key") == BOOKMAKER:
                    print(f"[merge_context] FanDuel detail:")
                    for market in book.get("markets", []):
                        mkey = market.get("key")
                        if mkey == "spreads":
                            outcomes = [(o.get("name"), o.get("point")) for o in market.get("outcomes", [])[:3]]
                            print(f"[merge_context]   spreads outcomes: {outcomes}")
                        elif mkey in {"totals", "total"}:
                            outcomes = [(o.get("name"), o.get("point")) for o in market.get("outcomes", [])[:2]]
                            print(f"[merge_context]   totals outcomes: {outcomes}")
                        elif mkey in {"h2h", "moneyline"}:
                            outcomes = [(o.get("name"), o.get("price")) for o in market.get("outcomes", [])[:3]]
                            print(f"[merge_context]   h2h outcomes: {outcomes}")
        
        print(f"[merge_context] merged {len(context_bookmakers)} context bookmakers")
        return props_data
    except Exception as e:
        print(f"[merge_context] failed: {e}")
        return props_data
    
def extract_game_context(payload, base):
    event = payload.get("data", {}) if isinstance(payload, dict) else {}

    home_team = base.get("home_team")
    away_team = base.get("away_team")

    empty = {
        "book_used": None,
        "spreads": {},
        "game_total": None,
        "moneyline": {},
    }

    books = event.get("bookmakers", [])
    if not books:
        return empty

    def score_book(book):
        keys = {m.get("key") for m in book.get("markets", [])}
        score = 0
        if "spreads" in keys:
            score += 1
        if "totals" in keys:
            score += 1
        if "h2h" in keys:
            score += 1
        if book.get("key") == BOOKMAKER:
            score += 10
        return score

    books = sorted(books, key=score_book, reverse=True)

    for book in books:
        ctx = {
            "book_used": book.get("key"),
            "spreads": {},
            "game_total": None,
            "moneyline": {},
        }

        for market in book.get("markets", []):
            mkey = market.get("key")

            if mkey == "spreads":
                for out in market.get("outcomes", []):
                    name = out.get("name")
                    point = out.get("point")
                    if name is not None and point is not None:
                        ctx["spreads"][name] = point

            elif mkey == "totals":
                for out in market.get("outcomes", []):
                    point = out.get("point")
                    if point is not None:
                        ctx["game_total"] = point
                        break

            elif mkey == "h2h":
                for out in market.get("outcomes", []):
                    name = out.get("name")
                    price = out.get("price")
                    if name is not None and price is not None:
                        ctx["moneyline"][name] = price

        if ctx["spreads"] or ctx["game_total"] is not None or ctx["moneyline"]:
            print(f"[context_selected] book={ctx['book_used']}")
            print(f"[context_selected] spreads={ctx['spreads']}")
            print(f"[context_selected] total={ctx['game_total']}")
            print(f"[context_selected] moneyline={ctx['moneyline']}")
            return ctx

    return empty



def flatten_event_odds(payload, context_payload=None):
    global DEBUG_EVENT_LOGGED
    rows = []

    timestamp = payload.get("timestamp")
    previous_timestamp = payload.get("previous_timestamp")
    next_timestamp = payload.get("next_timestamp")

    event = payload.get("data", {})

    base = {
        "requested_snapshot_time": timestamp,
        "previous_timestamp": previous_timestamp,
        "next_timestamp": next_timestamp,
        "event_id": event.get("id"),
        "sport_key": event.get("sport_key"),
        "commence_time": event.get("commence_time"),
        "home_team": event.get("home_team"),
        "away_team": event.get("away_team"),
    }

    # Collect game-level context (prefer BOOKMAKER if present)
    game_ctx = {
        "book_used": None,
        "spreads": {},
        "game_total": None,
        "moneyline": {},
    }

    # Debug: log first event structure
    if not DEBUG_EVENT_LOGGED:
        DEBUG_EVENT_LOGGED = True
        print("[DEBUG] First event structure:")
        print(f"[DEBUG] event_id={event.get('id')} home_team={base.get('home_team')} away_team={base.get('away_team')}")
        print(f"[DEBUG] bookmakers present: {len(event.get('bookmakers', []))}")
        for book in event.get("bookmakers", []):
            print(f"[DEBUG]   bookmaker: {book.get('key')}")
            mkeys = [m.get('key') for m in book.get('markets', [])]
            print(f"[DEBUG]     markets: {mkeys}")
            if book.get("key") == BOOKMAKER:
                for market in book.get("markets", []):
                    if market.get("key") == "spreads":
                        print(f"[DEBUG]     spreads outcomes: {[(o.get('name'), o.get('point')) for o in market.get('outcomes', [])[:3]]}")
                    if market.get("key") in {"totals", "total"}:
                        print(f"[DEBUG]     totals outcomes: {[(o.get('name'), o.get('point')) for o in market.get('outcomes', [])[:3]]}")
                    if market.get("key") in {"h2h", "moneyline"}:
                        print(f"[DEBUG]     h2h outcomes: {[(o.get('name'), o.get('price')) for o in market.get('outcomes', [])[:3]]}")

    game_ctx = extract_game_context(context_payload or payload, base)

    print(
        f"[game_context] spread_found={bool(game_ctx.get('spreads'))} "
        f"total_found={game_ctx.get('game_total') is not None} "
        f"moneyline_found={bool(game_ctx.get('moneyline'))} "
        f"book={game_ctx.get('book_used')}"
    )

    for book in event.get("bookmakers", []):
        for market in book.get("markets", []):
            if market.get("key") != MARKET:
                continue

            grouped = {}

            for outcome in market.get("outcomes", []):
                player = outcome.get("description")
                side = outcome.get("name")
                point = outcome.get("point")
                price = outcome.get("price")

                if not player or side not in {"Over", "Under"}:
                    continue

                key = (player, point)
                grouped.setdefault(key, {
                    **base,
                    "bookmaker_key": book.get("key"),
                    "bookmaker_title": book.get("title"),
                    "bookmaker_last_update": book.get("last_update"),
                    "market_key": market.get("key"),
                    "market_last_update": market.get("last_update"),
                    "player": player,
                    "line": point,
                    "over_price": None,
                    "under_price": None,
                })

                if side == "Over":
                    grouped[key]["over_price"] = price
                elif side == "Under":
                    grouped[key]["under_price"] = price

            rows.extend(grouped.values())

    # Attach game-level context to each row (always add columns, even if null)
    for r in rows:
        # Game context book
        r["game_context_book"] = game_ctx.get("book_used")
        # Home/away teams already in base, ensure they're set
        r["home_team"] = base.get("home_team")
        r["away_team"] = base.get("away_team")
        # Always initialize game-context columns (with None defaults)
        r["home_spread"] = None
        r["away_spread"] = None
        r["game_total"] = None
        r["home_moneyline"] = None
        r["away_moneyline"] = None
        r["team"] = None
        r["opponent"] = None
        r["is_home"] = None
        r["team_spread"] = None
        r["opponent_spread"] = None
        r["is_favorite"] = None
        r["is_underdog"] = None
        r["spread_abs"] = None
        r["spread_bucket"] = None
        r["total_bucket"] = None
        r["team_moneyline"] = None
        r["opponent_moneyline"] = None

        # Populate from game_ctx: spreads
        spreads = game_ctx.get("spreads", {})
        # Match home_team name to spreads keys (could be team name, abbreviation, or 'Home')
        home_sp = None
        for key in spreads.keys():
            if key.lower() == base.get("home_team", "").lower():
                home_sp = spreads[key]
                break
        # Try alternate keys if not found
        if home_sp is None and "Home" in spreads:
            home_sp = spreads["Home"]
        if home_sp is None:
            # Try first available spread (might be home or away, we'll guess)
            for k, v in spreads.items():
                if k not in {"Over", "Under"}:
                    home_sp = v
                    break

        if home_sp is not None:
            r["home_spread"] = home_sp
            r["away_spread"] = -home_sp
            r["spread_abs"] = abs(home_sp)

        # Populate from game_ctx: game_total and total_bucket
        if game_ctx.get("game_total") is not None:
            r["game_total"] = game_ctx.get("game_total")
            tt = game_ctx.get("game_total")
            if tt < 42:
                r["total_bucket"] = "low_total_<42"
            elif 42 <= tt < 47:
                r["total_bucket"] = "mid_total_42_47"
            else:
                r["total_bucket"] = "high_total_47_plus"

        # Populate from game_ctx: moneyline
        moneyline = game_ctx.get("moneyline", {})
        # Match home_team and away_team to moneyline keys
        for key, ml in moneyline.items():
            if key.lower() == base.get("home_team", "").lower():
                r["home_moneyline"] = ml
            if key.lower() == base.get("away_team", "").lower():
                r["away_moneyline"] = ml

    # Log game context availability
    print(
        f"[game_context] spread_found={bool(game_ctx.get('spreads'))} total_found={game_ctx.get('game_total') is not None} moneyline_found={bool(game_ctx.get('moneyline'))} book={game_ctx.get('book_used')}"
    )
    return rows


def parse_args():
    parser = argparse.ArgumentParser(
        description="Backfill FanDuel NFL receptions props from existing event dataset"
    )
    parser.add_argument(
        "--seasons",
        nargs="+",
        type=int,
        default=SEASONS,
        help="Seasons to backfill, e.g. 2023 2024 2025",
    )
    parser.add_argument(
        "--refresh-events",
        action="store_true",
        help="Ignore EVENT_SOURCE_FILE and freshly discover events from the Odds API.",
    )
    return parser.parse_args()


def main(seasons=None, refresh_events=False):
    if seasons is None:
        seasons = SEASONS

    # Print parsed seasons config
    print(f"[config] seasons={seasons}")

    all_events = []
    # Build a mapping from event_id -> week from the existing EVENT_SOURCE_FILE (if available)
    id_to_week = {}
    try:
        existing_events = load_events_from_existing_props(None)
        for e in existing_events:
            if e.get("id") and e.get("week"):
                id_to_week[e.get("id")] = e.get("week")
    except FileNotFoundError:
        existing_events = []
    # Discover events per-season to ensure seasons actually drive discovery
    for season in seasons:
        # Compute the date window for this NFL season and print it
        start_date, end_date = season_date_range(season)
        print(f"[season {season}] date window: start={start_date}, end={end_date}")

        # First try loading events from the existing props/source file filtered to this season
        if refresh_events:
            print(f"[season {season}] refresh_events=True, skipping EVENT_SOURCE_FILE")
            props_events = []
        else:
            try:
                props_events = load_events_from_existing_props([season])
            except FileNotFoundError:
                props_events = []

        if props_events:
            # Ensure season is set on events from the props file
            for e in props_events:
                if not e.get("season"):
                    e["season"] = season

            # compute latest commence_time in props_events
            latest = None
            for e in props_events:
                ct = e.get("commence_time")
                if not ct:
                    continue
                try:
                    dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                except Exception:
                    continue
                if latest is None or dt > latest:
                    latest = dt

            latest_str = latest.strftime("%Y-%m-%dT%H:%M:%SZ") if latest else "n/a"
            print(f"[season {season}] events discovered: {len(props_events)} (source: EVENT_SOURCE_FILE)")
            print(f"[season {season}] latest commence_time: {latest_str}")

            # dedupe by id
            unique = {e.get("id"): e for e in props_events if e.get("id")}
            all_events.extend(unique.values())
            continue

        # Fallback: discover events via the odds API over the season date range
        discovered = {}
        for day in daterange(start_date, end_date):
            try:
                day_events = fetch_events_for_date(day)
            except Exception as e:
                print(f"[warn] failed fetching events for {day.date()}: {e}")
                day_events = []

            for ev in day_events:
                ev_id = ev.get("id")
                if not ev_id:
                    continue
                # tag the discovered event with the season we're scanning for
                ev["season"] = season
                discovered[ev_id] = ev

        # compute latest commence_time in discovered
        latest = None
        for e in discovered.values():
            ct = e.get("commence_time")
            if not ct:
                continue
            try:
                dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
            except Exception:
                continue
            if latest is None or dt > latest:
                latest = dt

        latest_str = latest.strftime("%Y-%m-%dT%H:%M:%SZ") if latest else "n/a"
        print(f"[season {season}] events discovered: {len(discovered)} (source: odds_api historical events)")
        print(f"[season {season}] latest commence_time: {latest_str}")

        if len(discovered) == 0:
            print("[ERROR]" + " " * 1 + f"No events found for season {season}.")
            print(
                f"[ERROR] Source check: {EVENT_SOURCE_FILE} contained no rows for season {season}, and API discovery across {start_date} to {end_date} returned 0 events."
            )

        all_events.extend(discovered.values())

    print(f"\n[event count] {len(all_events):,}")

    all_rows = []

    # Build player -> team mapping from EVENT_SOURCE_FILE when available
    player_team_map = {}
    if EVENT_SOURCE_FILE.exists():
        try:
            src = pd.read_csv(EVENT_SOURCE_FILE)
            # pick a reasonable player column
            player_col = None
            for c in ["player", "player_name", "player_display_name"]:
                if c in src.columns:
                    player_col = c
                    break
            team_col = None
            for c in ["team", "team_name", "team_abbr"]:
                if c in src.columns:
                    team_col = c
                    break
            if player_col and team_col:
                src["player_norm"] = src[player_col].astype(str).str.lower().str.replace(".", "", regex=False).str.replace("'", "", regex=False).str.strip()
                for _, r in src.iterrows():
                    eid = r.get("event_id") or r.get("event_id_str") or r.get("id")
                    if pd.isna(eid) or pd.isna(r.get("player_norm")):
                        continue
                    key = (str(eid), r.get("player_norm"))
                    player_team_map[key] = r.get(team_col)
        except Exception:
            player_team_map = {}

    print("\n===== FETCH ODDS =====")

    for i, event in enumerate(all_events, start=1):
        print(
            f"\n[season {event.get('season')}] [{i}/{len(all_events)}] "
            f"{event.get('away_team')} @ {event.get('home_team')} "
            f"kickoff={event.get('commence_time')}"
        )

        try:
            payload, context_payload = fetch_event_odds(event)
            rows = flatten_event_odds(payload, context_payload)
            
            for row in rows:
                row["season_guess"] = event.get("season")
                # Prefer explicit week on the event, then lookup by event_id from source file,
                # otherwise estimate from commence_time and the season start date.
                wk = event.get("week")
                if not wk:
                    wk = id_to_week.get(event.get("id"))
                if not wk:
                    wk = estimate_week_from_commence(event.get("commence_time"), row.get("season_guess"))
                row["week_guess"] = wk

                # attempt to attach team/opponent/is_home using player_team_map
                player_norm = str(row.get("player", "")).lower().replace(".", "").replace("'", "").strip()
                key = (str(row.get("event_id")), player_norm)
                team = player_team_map.get(key)
                if team:
                    row["team"] = team
                    # determine home/away
                    if row.get("home_team") and row.get("home_team") == team:
                        row["is_home"] = True
                        row["opponent"] = row.get("away_team")
                    else:
                        row["is_home"] = False
                        row["opponent"] = row.get("home_team")
                    # compute team_spread if home_spread present
                    if row.get("home_spread") is not None:
                        if row["is_home"]:
                            row["team_spread"] = row.get("home_spread")
                            row["opponent_spread"] = row.get("away_spread")
                        else:
                            row["team_spread"] = row.get("away_spread")
                            row["opponent_spread"] = row.get("home_spread")
                        # favorite if team_spread < 0 (negative means favored)
                        ts = row.get("team_spread")
                        row["is_favorite"] = False if pd.isna(ts) else (ts < 0)
                        row["is_underdog"] = False if pd.isna(ts) else (ts > 0)
                        row["spread_abs"] = abs(row.get("team_spread"))
                        # spread bucket
                        def s_bucket(v):
                            if pd.isna(v):
                                return None
                            if v == 0:
                                return "pickem"
                            if v < -7:
                                return "favorite_7_plus"
                            if -7 <= v < -3:
                                return "favorite_3_to_7"
                            if -3 <= v < 0:
                                return "favorite_0_to_3"
                            av = abs(v)
                            if av <= 3:
                                return "dog_0_to_3"
                            if 3 < av <= 7:
                                return "dog_3_to_7"
                            return "dog_7_plus"
                        row["spread_bucket"] = s_bucket(row.get("team_spread"))
                    # attach moneylines if present
                    if row.get("home_moneyline") is not None or row.get("away_moneyline") is not None:
                        if row["is_home"]:
                            row["team_moneyline"] = row.get("home_moneyline")
                            row["opponent_moneyline"] = row.get("away_moneyline")
                        else:
                            row["team_moneyline"] = row.get("away_moneyline")
                            row["opponent_moneyline"] = row.get("home_moneyline")
                    # attach total bucket
                    if row.get("game_total") is not None:
                        tt = row.get("game_total")
                        if tt < 42:
                            row["total_bucket"] = "low_total_<42"
                        elif 42 <= tt < 47:
                            row["total_bucket"] = "mid_total_42_47"
                        else:
                            row["total_bucket"] = "high_total_47_plus"

            print(f"[flatten] rows={len(rows)}")
            all_rows.extend(rows)

        except Exception as e:
            print(f"[error] event_id={event.get('id')} error={e}")

    if not all_rows:
        raise RuntimeError("No rows collected.")

    df = pd.DataFrame(all_rows)

    if "bookmaker_key" in df.columns:
        df["sportsbook"] = df["bookmaker_key"]
    else:
        df["sportsbook"] = BOOKMAKER

    if "actual_value" in df.columns and "line" in df.columns:
        df["actual_minus_line"] = df["actual_value"] - df["line"]
        df["hit_over"] = df["actual_value"] > df["line"]

    duplicate_subset = [
        "season_guess",
        "event_id",
        "player",
        "line",
        "requested_snapshot_time",
    ]
    if df.duplicated(subset=duplicate_subset).any():
        dup_count = df.duplicated(subset=duplicate_subset).sum()
        print(f"[warning] duplicate rows detected: {dup_count}, deduping on {duplicate_subset}")
        df = df.drop_duplicates(subset=duplicate_subset, keep="first")

    if "market_key" in df.columns:
        markets = set(df["market_key"].dropna().astype(str).unique())
        if markets != {MARKET}:
            print(f"[warning] unexpected market_key values: {sorted(markets)}")

    if "sportsbook" in df.columns:
        sportsbooks = set(df["sportsbook"].dropna().astype(str).str.lower().unique())
        if any(s != BOOKMAKER for s in sportsbooks):
            print(f"[warning] unexpected sportsbook values: {sorted(sportsbooks)}")

    # Coerce week_guess to numeric for checks
    if "week_guess" in df.columns:
        df["week_guess_numeric"] = pd.to_numeric(df["week_guess"], errors="coerce")
        max_week_by_season = df.groupby("season_guess")["week_guess_numeric"].max()
        for season in seasons:
            max_week = max_week_by_season.get(season)
            if pd.notna(max_week) and max_week < 18:
                print(f"[WARNING] season {season} max week_guess = {int(max_week)} (<18)")
    else:
        max_week_by_season = {}

    # Default modeling filter: keep only weeks <= 18 (or null week_guess)
    df_model = df
    if "week_guess_numeric" in df.columns:
        df_model = df[(df["week_guess_numeric"].isna()) | (df["week_guess_numeric"] <= 18)].copy()

    # Compute rows by season and warn for low counts
    rows_by_season = df_model.groupby("season_guess").size()
    for season, count in rows_by_season.items():
        if count == 0:
            print(f"[warning] season {season} returned 0 rows")
        elif count < 350:
            print(f"[warning] season {season} returned only {count} rows")

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    df_model.to_csv(OUT_FILE, index=False)

    archive_file = ARCHIVE_DIR / f"fanduel_receptions_history_{'_'.join(map(str, sorted(seasons)))}_v1.csv"
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    df_model.to_csv(archive_file, index=False)

    # Verify game-context columns were written
    print("\n[game_context_columns]")
    game_ctx_cols = [
        "home_spread",
        "away_spread",
        "game_total",
        "home_moneyline",
        "away_moneyline",
        "team_spread",
        "is_favorite",
        "spread_bucket",
        "total_bucket",
    ]
    for col in game_ctx_cols:
        exists = col in df_model.columns
        non_null_rate = 0.0
        if exists:
            non_null_rate = df_model[col].notna().sum() / len(df_model) if len(df_model) > 0 else 0.0
        print(f"{col} exists={exists} non_null_rate={non_null_rate:.1%}")

    print("\n===== BACKFILL COMPLETE =====")
    print(f"events: {len(all_events):,}")
    print(f"rows: {len(df_model):,}")
    print(f"raw_rows_before_model_filter: {len(df):,}")
    print(f"output: {OUT_FILE}")
    print(f"archive: {archive_file}")

    print("\nRows by season_guess:")
    print(rows_by_season)

    print("\nRows by season_guess/week_guess:")
    if "week_guess" in df.columns:
        try:
            print(df_model.groupby(["season_guess", "week_guess"], dropna=False).size())
        except TypeError:
            # Older pandas versions may not support dropna; fall back to filling NA explicitly
            tmp = df.copy()
            tmp["week_guess_filled"] = tmp["week_guess"].fillna("<NULL>")
            print(tmp.groupby(["season_guess", "week_guess_filled"]).size())
    else:
        print("week_guess column not available")

    # Summary: null week_guess rows by season_guess
    if "week_guess" in df.columns:
        null_mask = df_model["week_guess"].isna()
        if null_mask.any():
            print("\nNull week_guess rows by season_guess:")
            print(df[null_mask].groupby("season_guess").size())
        else:
            print("\nNull week_guess rows by season_guess: None")

    print("\nRows by market_key:")
    if "market_key" in df.columns:
        print(df_model.groupby("market_key").size())
    else:
        print("market_key column not available")

    print("\nRows by sportsbook:")
    print(df_model.groupby("sportsbook").size())


    print("\nAPI credits:")
    print(f"remaining: {LAST_API_HEADERS['remaining']}")
    print(f"used: {LAST_API_HEADERS['used']}")
    print(f"last cost: {LAST_API_HEADERS['last']}")

    print("\nSample:")
    print(df_model.head(20).to_string(index=False))


if __name__ == "__main__":
    args = parse_args()
    main(args.seasons, refresh_events=args.refresh_events)
