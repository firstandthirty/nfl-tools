import math
import requests
import smtplib
from email.mime.text import MIMEText
from collections import defaultdict
from statistics import mean
from datetime import datetime
import statsapi
import os


API_KEY = os.environ["ODDS_API_KEY"]
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]
EMAIL_TO = os.environ["EMAIL_TO"]
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

# Example placeholders — replace with the actual keys you use
SPORT = "baseball_mlb"
REGIONS = "us"
BOOKMAKERS = "fanduel"
ODDS_FORMAT = "american"

import unicodedata
from zoneinfo import ZoneInfo
from datetime import datetime

import re
import requests
from bs4 import BeautifulSoup

def fetch_mlb_starting_lineups():
    url = "https://www.mlb.com/starting-lineups"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.text

def normalize_team_name(name: str) -> str:
    if not name:
        return ""
    name = name.lower().strip()

    aliases = {
        "athletics": "oakland athletics",
        "oakland athletics": "oakland athletics",
        "a's": "oakland athletics",
        "los angeles angels": "los angeles angels",
        "la angels": "los angeles angels",
        "los angeles dodgers": "los angeles dodgers",
        "la dodgers": "los angeles dodgers",
        "new york yankees": "new york yankees",
        "new york mets": "new york mets",
        "chicago cubs": "chicago cubs",
        "chicago white sox": "chicago white sox",
        "kansas city royals": "kansas city royals",
        "tampa bay rays": "tampa bay rays",
        "san francisco giants": "san francisco giants",
        "san diego padres": "san diego padres",
        "st louis cardinals": "st louis cardinals",
    }

    return aliases.get(name, name)

def extract_lineups_from_mlb_page(html_text):
    """
    Returns normalized player-name map like:
    {
        "yandy diaz": {"confirmed": True, "batting_order": 1},
        ...
    }
    """
    lineup_map = {}

    # Simple text-based parse works well enough for this page structure
    text = BeautifulSoup(html_text, "html.parser").get_text("\n")

    # Match lines like:
    # 1. Yandy Díaz (R) DH
    pattern = re.compile(r'^\s*([1-9])\.\s+([A-Za-zÀ-ÿ\.\'\- ]+?)\s+\([RLS]\)', re.MULTILINE)

    for m in pattern.finditer(text):
        batting_order = int(m.group(1))
        raw_name = m.group(2).strip()
        lineup_map[normalize_player_name(raw_name)] = {
            "confirmed": True,
            "batting_order": batting_order,
            "player_display": raw_name,
        }

    return lineup_map

def to_et_display(commence_time_str: str) -> str:
    dt_utc = datetime.fromisoformat(commence_time_str.replace("Z", "+00:00"))
    dt_et = dt_utc.astimezone(ZoneInfo("America/New_York"))
    return dt_et.strftime("%I:%M %p ET").lstrip("0")


def normalize_player_name(name: str) -> str:
    if not name:
        return ""
    name = unicodedata.normalize("NFKD", name)
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    name = name.lower().replace(".", "").replace("'", "").replace("-", " ")
    name = " ".join(name.split())
    return name


def american_to_implied_prob(odds):
    if odds is None:
        return None

    odds = int(odds)
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)

def get_event_props(event_id: str):
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/events/{event_id}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": REGIONS,
        "bookmakers": BOOKMAKERS,
        "markets": "batter_hits_alternate",
        "oddsFormat": ODDS_FORMAT,
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


#temporary helper
def debug_player_markets(all_players, player_name_substring):
    needle = normalize_player_name(player_name_substring)

    for player_key, entries in all_players.items():
        if needle in player_key:
            print(f"\n=== DEBUG {player_key} ===")
            for entry in entries:
                print(
                    f"    book={entry.get('book')} "
                    f"market_key={entry.get('market_key')} "
                    f"over_price={entry.get('over_price')} "
                    f"over_prob={entry.get('over_prob'):.4f}"
                )


def get_events():
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/events"
    params = {
        "apiKey": API_KEY,
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def get_mlb_games_for_date(game_date: str):
    # game_date: YYYY-MM-DD
    return statsapi.schedule(date=game_date)

def find_matching_game_pk(event, mlb_games):
    home = normalize_team_name(event["home_team"])
    away = normalize_team_name(event["away_team"])

    for g in mlb_games:
        h = normalize_team_name(g.get("home_name", ""))
        a = normalize_team_name(g.get("away_name", ""))
        if h == home and a == away:
            return g["game_id"]

    return None

def extract_confirmed_lineup(game_pk: int):
    lineup = {}

    data = statsapi.get("game", {"gamePk": game_pk})
    teams = data.get("liveData", {}).get("boxscore", {}).get("teams", {})

    for side in ["home", "away"]:
        team_block = teams.get(side, {})
        players = team_block.get("players", {})

        for p in players.values():
            person = p.get("person", {})
            raw_name = person.get("fullName")
            batting_order_raw = p.get("battingOrder")

            if not raw_name or not batting_order_raw:
                continue

            try:
                batting_order = int(str(batting_order_raw)) // 100
            except Exception:
                batting_order = None

            if batting_order is None:
                continue

            lineup[normalize_player_name(raw_name)] = {
                "confirmed": True,
                "batting_order": batting_order,
                "player_display": raw_name,
            }

    return lineup

def build_lineup_map(events):
    et_now = datetime.now(ZoneInfo("America/New_York"))
    game_date = et_now.strftime("%Y-%m-%d")
    mlb_games = get_mlb_games_for_date(game_date)

    print(f"MLB schedule games found: {len(mlb_games)} for ET date {game_date}")
    print(f"MLB games loaded: {len(mlb_games)}")

    lineup_map = {}

    # First pass: StatsAPI
    for event in events:
        try:
            game_pk = find_matching_game_pk(event, mlb_games)
            if game_pk:
                print(f"Matched Odds API event '{event.get('away_team')} at {event.get('home_team')}' to MLB gamePk {game_pk}")
                confirmed = extract_confirmed_lineup(game_pk)
                print(f"Starters found for gamePk {game_pk}: {len(confirmed)}")
                lineup_map.update(confirmed)
            else:
                print(f"Unmatched Odds API event: '{event.get('away_team')} at {event.get('home_team')}'")

        except Exception as e:
            print(
                f"Lineup check failed for "
                f"{event.get('away_team')} at {event.get('home_team')}: {e}"
            )

    # Fallback: MLB starting-lineups page
    try:
        html_text = fetch_mlb_starting_lineups()
        mlb_page_lineups = extract_lineups_from_mlb_page(html_text)

        # Only fill missing players; don't overwrite StatsAPI if already present
        for player_key, info in mlb_page_lineups.items():
            if player_key not in lineup_map:
                lineup_map[player_key] = info

        print(f"Lineup map players found after MLB.com fallback: {len(lineup_map)}")

    except Exception as e:
        print(f"MLB.com starting-lineups fallback failed: {e}")

    return lineup_map

def lineup_priority(row):
    bo = row.get("batting_order")
    if bo is None:
        return 99
    return bo


def score_players(all_players, lineup_map=None, player_game_info=None):
    results = []

    for player_key, entries in all_players.items():
        if not entries:
            continue

        p_hit = mean(x["over_prob"] for x in entries)
        source_market = "FanDuel 1+ hit"

        confirmed = None
        batting_order = None
        if lineup_map and player_key in lineup_map:
            confirmed = lineup_map[player_key]["confirmed"]
            batting_order = lineup_map[player_key]["batting_order"]

        game_info = player_game_info.get(player_key, {}) if player_game_info else {}
        display_name = entries[0].get("player_display", player_key)
        odds_text = " / ".join(
            f"+{entry['over_price']}" if entry['over_price'] > 0 else str(entry['over_price'])
            for entry in entries
        )

        results.append({
            "player": display_name,
            "player_key": player_key,
            "p_hit": p_hit,
            "source_market": source_market,
            "odds_text": odds_text,
            "confirmed": confirmed,
            "batting_order": batting_order,
            "start_time_et": game_info.get("start_time_et"),
            "matchup": game_info.get("matchup"),
        })

    results.sort(key=lambda x: x["p_hit"], reverse=True)
    return results

def build_email_body(results):
    lines = []
    lines.append("TOP BTS PICKS")
    lines.append("")

    for i, row in enumerate(results[:10], start=1):
<<<<<<< HEAD
        if row["confirmed"] is True:
            bo = row.get("batting_order")
            if bo is not None:
                lineup_status = f"confirmed batting {bo}{'st' if bo==1 else 'nd' if bo==2 else 'rd' if bo==3 else 'th'}"
            else:
                lineup_status = "confirmed"
        else:
            lineup_status = "lineup not confirmed"

        game = row.get("matchup", "game TBD")
        game_time_et = row.get("start_time_et", "time TBD")

        lines.append(
            f"{i}. {row['player']} — {row['odds_text']} — {row['p_hit']:.1%} — {lineup_status} — {game} — {game_time_et}"
=======
        lines.append(
            f"{i}. {row['player']} — {row['odds_text']} — {row['p_hit']:.1%}"
>>>>>>> 0def92b18825037544045efebf7e1c0a0f226936
        )

    return "\n".join(lines)

def extract_hit_markets(event_data):
    players = defaultdict(list)

    for bookmaker in event_data.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market.get("key") != "batter_hits_alternate":
                continue

            for outcome in market.get("outcomes", []):
                if outcome.get("name") != "Over":
                    continue
                if float(outcome.get("point", -1)) != 0.5:
                    continue

                raw_player = outcome.get("description") or outcome.get("name")
                if not raw_player:
                    continue

                price = outcome.get("price")
                if price is None:
                    continue

                implied_prob = american_to_implied_prob(price)
                if implied_prob is None:
                    continue

                player_key = normalize_player_name(raw_player)
                players[player_key].append({
                    "player_display": raw_player,
                    "book": bookmaker.get("title", bookmaker.get("key", "FanDuel")),
                    "market_key": "batter_hits_alternate",
                    "point": 0.5,
                    "over_prob": implied_prob,
                    "over_price": int(price),
                })

    return players

def send_email(subject: str, body: str):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [EMAIL_TO], msg.as_string())


def main():
    events = get_events()
    print(f"Events fetched: {len(events)}")
    print(f"Odds API events loaded: {len(events)}")

    merged_players = defaultdict(list)
    player_game_info = {}

    odds_failures = 0
    odds_successes = 0

    for event in events:
        event_id = event["id"]

        try:
            data = get_event_props(event_id)
            odds_successes += 1
            players = extract_hit_markets(data)

            print(
                f"Event {event['away_team']} at {event['home_team']} "
                f"-> players with markets: {len(players)}"
            )

            start_time_et = to_et_display(event["commence_time"])
            away_team = event["away_team"]
            home_team = event["home_team"]

            for player_key, entries in players.items():
                if player_key not in player_game_info:
                    player_game_info[player_key] = {
                        "start_time_et": start_time_et,
                        "matchup": f"{away_team} at {home_team}",
                    }
                merged_players[player_key].extend(entries)

        except Exception as e:
            odds_failures += 1
            print(f"Failed odds pull for event {event_id}: {e}")

    print(f"Odds pulls succeeded: {odds_successes}")
    print(f"Odds pulls failed: {odds_failures}")
    print(f"Merged players: {len(merged_players)}")

    point_distribution = defaultdict(int)
    for entries in merged_players.values():
        for entry in entries:
            point_distribution[entry.get('point')] += 1
    print(f"Point distribution: {dict(point_distribution)}")

    if not merged_players:
        body = (
            "Beat the Streak script ran, but no batter hit props were loaded.\n\n"
            "Most likely causes:\n"
            "- The Odds API key does not have access to these markets\n"
            "- The API key/subscription is invalid\n"
            "- The request hit rate/usage limits\n\n"
            "Check GitHub Actions logs for 401/429 errors."
        )
        print(body)
        send_email("Beat the Streak picks - ERROR", body)
        print("\nEmail sent successfully.")
        return

    lineup_map = build_lineup_map(events)
    print(f"Lineup map players found: {len(lineup_map)}")

    results = score_players(
        merged_players,
        lineup_map=lineup_map,
        player_game_info=player_game_info,
    )

    print(f"Results after scoring: {len(results)}")
    if results:
        print("Top 5 preview:")
        for row in results[:5]:
            print(
                f"  {row['player']} - {row['p_hit']:.1%} | {row['odds_text']} | "
                f"{row.get('start_time_et', 'time TBD')} | {row.get('matchup', 'matchup TBD')} | {row['source_market']}"
            )

    if not results:
        raise RuntimeError("No Beat the Streak results found after scoring.")

    body = build_email_body(results)
    print(body)

    send_email("Beat the Streak picks", body)
    print("\nEmail sent successfully.")
    
if __name__ == "__main__":
    main()
