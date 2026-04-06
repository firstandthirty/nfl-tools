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
BOOKMAKERS = "draftkings,fanduel,betmgm,caesars,bovada"
ODDS_FORMAT = "american"

import unicodedata
from zoneinfo import ZoneInfo
from datetime import datetime


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


def american_to_prob(odds: int) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    return (-odds) / ((-odds) + 100)


def decimal_to_prob(decimal_odds: float) -> float:
    return 1.0 / decimal_odds


def no_vig_prob(over_prob: float, under_prob: float) -> tuple[float, float]:
    total = over_prob + under_prob
    if total == 0:
        return over_prob, under_prob
    return over_prob / total, under_prob / total


def poisson_p_ge_1(lmbda: float) -> float:
    return 1 - math.exp(-lmbda)


def poisson_p_ge_2(lmbda: float) -> float:
    return 1 - math.exp(-lmbda) * (1 + lmbda)


def lambda_from_p_ge_1(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return -math.log(1 - p)

def get_event_props(event_id: str):
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/events/{event_id}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": REGIONS,
        "bookmakers": BOOKMAKERS,
        "markets": "batter_hits,batter_hits_alternate",
        "oddsFormat": ODDS_FORMAT,
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def lambda_from_p_ge_2(target_p: float, lo=1e-6, hi=10.0, tol=1e-8) -> float:
    target_p = min(max(target_p, 1e-9), 1 - 1e-9)

    for _ in range(100):
        mid = (lo + hi) / 2
        val = poisson_p_ge_2(mid)
        if val < target_p:
            lo = mid
        else:
            hi = mid
        if abs(val - target_p) < tol:
            break
    return (lo + hi) / 2

#temporary helper
def debug_player_markets(all_players, player_name_substring):
    needle = normalize_player_name(player_name_substring)

    for player_key, ladders in all_players.items():
        if needle in player_key:
            print(f"\n=== DEBUG {player_key} ===")
            for point in sorted(ladders.keys()):
                print(f"  point {point}:")
                for entry in ladders[point]:
                    print(
                        f"    book={entry.get('book')} "
                        f"market_key={entry.get('market_key')} "
                        f"over_price={entry.get('over_price')} "
                        f"under_price={entry.get('under_price')} "
                        f"over_prob={entry.get('over_prob'):.4f}"
                    )


def fit_lambda_from_markets(p_ge_1_list, p_ge_2_list, lo=1e-6, hi=10.0):
    def loss(lmbda: float) -> float:
        err = 0.0
        for p in p_ge_1_list:
            err += (poisson_p_ge_1(lmbda) - p) ** 2
        for p in p_ge_2_list:
            err += (poisson_p_ge_2(lmbda) - p) ** 2
        return err

    # simple grid search is plenty for this use case
    best_lambda = None
    best_loss = float("inf")
    steps = 2000
    for i in range(steps + 1):
        lmbda = lo + (hi - lo) * i / steps
        cur = loss(lmbda)
        if cur < best_loss:
            best_loss = cur
            best_lambda = lmbda
    return best_lambda


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

    lineup_map = {}

    for event in events:
        try:
            game_pk = find_matching_game_pk(event, mlb_games)
            if not game_pk:
                continue

            confirmed = extract_confirmed_lineup(game_pk)
            lineup_map.update(confirmed)

        except Exception as e:
            print(
                f"Lineup check failed for "
                f"{event.get('away_team')} at {event.get('home_team')}: {e}"
            )

    return lineup_map

def lineup_priority(row):
    bo = row.get("batting_order")
    if bo is None:
        return 99
    return bo


def score_players(all_players, lineup_map=None, player_game_info=None):
    results = []

    for player_key, ladders in all_players.items():
        # Prefer FanDuel 1+ hit if available, then any 1+ hit market,
        # then fall back to inferring from 2+ hit markets.
        fd_05 = sorted(
            x["over_prob"]
            for x in ladders.get(0.5, [])
            if "fan" in x.get("book", "").lower()
        )
        all_05 = sorted(x["over_prob"] for x in ladders.get(0.5, []))
        all_15 = sorted(x["over_prob"] for x in ladders.get(1.5, []))

        if not all_05 and not all_15:
            continue

        if fd_05:
            p1 = mean(fd_05)
            lmbda = lambda_from_p_ge_1(p1)
            source_market = "FD 0.5"
        elif all_05:
            p1 = mean(all_05)
            lmbda = lambda_from_p_ge_1(p1)
            source_market = "market 0.5"
        else:
            p_ge_2 = mean(all_15)
            lmbda = lambda_from_p_ge_2(p_ge_2)
            p1 = poisson_p_ge_1(lmbda)
            source_market = "inferred 1.5"

        confirmed = None
        batting_order = None
        if lineup_map and player_key in lineup_map:
            confirmed = lineup_map[player_key]["confirmed"]
            batting_order = lineup_map[player_key]["batting_order"]

        game_info = player_game_info.get(player_key, {}) if player_game_info else {}

        display_name = None
        if ladders.get(0.5):
            display_name = ladders[0.5][0].get("player_display")
        elif ladders.get(1.5):
            display_name = ladders[1.5][0].get("player_display")
        else:
            display_name = player_key

        results.append({
            "player": display_name,
            "player_key": player_key,
            "lambda": lmbda,
            "p_hit": p1,
            "source_market": source_market,
            "books_0_5": len(ladders.get(0.5, [])),
            "books_1_5": len(ladders.get(1.5, [])),
            "confirmed": confirmed,
            "batting_order": batting_order,
            "start_time_et": game_info.get("start_time_et"),
            "matchup": game_info.get("matchup"),
        })

    results.sort(key=lambda x: x["p_hit"], reverse=True)
    return results

def build_email_body(results):
    lines = []
    lines.append("Top Beat the Streak candidates for today")
    lines.append("")
    lines.append("----------------------------------------")
    lines.append("")

    for i, row in enumerate(results[:10], start=1):
        if row["confirmed"] is True:
            status = "CONFIRMED"
        else:
            status = "unconfirmed"

        bo_txt = f" | batting {row['batting_order']}" if row.get("batting_order") else ""
        time_txt = row.get("start_time_et") or "time TBD"
        matchup_txt = row.get("matchup") or "matchup TBD"

        lines.append(
            f"{i}. {row['player']} — "
            f"{row['p_hit']:.1%} | "
            f"{time_txt} | "
            f"{matchup_txt} | "
            f"{status}{bo_txt}"
        )

    return "\n".join(lines)

def extract_hit_markets(event_data):
    """
    Dedupes by (normalized_player, point, book), so the same book/point
    does not get counted twice if it appears in both batter_hits and
    batter_hits_alternate.
    """
    players = defaultdict(lambda: defaultdict(dict))

    for bookmaker in event_data.get("bookmakers", []):
        book_title = bookmaker.get("title", bookmaker.get("key", "Unknown"))

        for market in bookmaker.get("markets", []):
            market_key = market.get("key")
            if market_key not in {"batter_hits", "batter_hits_alternate"}:
                continue

            grouped = defaultdict(dict)

            for outcome in market.get("outcomes", []):
                raw_player = outcome.get("description") or outcome.get("name")
                point = outcome.get("point")
                side = (outcome.get("name") or "").strip().lower()
                price = outcome.get("price")

                if raw_player is None or point is None or price is None:
                    continue
                if side not in {"over", "under"}:
                    continue

                player_key = normalize_player_name(raw_player)
                grouped[(player_key, raw_player, float(point))][side] = price

            for (player_key, raw_player, point), sides in grouped.items():
                if "over" not in sides or "under" not in sides:
                    continue

                over_prob = american_to_prob(int(sides["over"]))
                under_prob = american_to_prob(int(sides["under"]))
                fair_over, fair_under = no_vig_prob(over_prob, under_prob)

                new_entry = {
                    "player_display": raw_player,
                    "book": book_title,
                    "market_key": market_key,
                    "over_prob": fair_over,
                    "under_prob": fair_under,
                    "over_price": int(sides["over"]),
                    "under_price": int(sides["under"]),
                }

                existing = players[player_key][point].get(book_title)

                # Prefer the non-alternate market if both exist for same book/point.
                if existing is None or (
                    existing["market_key"] == "batter_hits_alternate"
                    and market_key == "batter_hits"
                ):
                    players[player_key][point][book_title] = new_entry

    # Convert nested dicts back to list structure expected downstream.
    out = defaultdict(lambda: defaultdict(list))
    for player_key, ladders in players.items():
        for point, by_book in ladders.items():
            out[player_key][point] = list(by_book.values())

    return out

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

    merged_players = defaultdict(lambda: defaultdict(list))
    player_game_info = {}

    for event in events:
        event_id = event["id"]

        try:
            data = get_event_props(event_id)
            players = extract_hit_markets(data)

            start_time_et = to_et_display(event["commence_time"])
            away_team = event["away_team"]
            home_team = event["home_team"]

            for player_key, ladders in players.items():
                if player_key not in player_game_info:
                    player_game_info[player_key] = {
                        "start_time_et": start_time_et,
                        "matchup": f"{away_team} at {home_team}",
                    }

                for point, entries in ladders.items():
                    merged_players[player_key][point].extend(entries)

        except Exception as e:
            print(f"Failed odds pull for event {event_id}: {e}")

    point_counts = defaultdict(int)
    for player_key, ladders in merged_players.items():
        for point in ladders.keys():
            point_counts[point] += 1

    print("Point distribution:")
    for point in sorted(point_counts.keys()):
        print(f"  {point}: {point_counts[point]}")

    lineup_map = build_lineup_map(events)
    print(f"Lineup map players found: {len(lineup_map)}")

    debug_player_markets(merged_players, "Jeremy Pena")
    debug_player_markets(merged_players, "Yordan Alvarez")
    debug_player_markets(merged_players, "Jose Altuve")
    debug_player_markets(merged_players, "Trea Turner")

    results = score_players(
        merged_players,
        lineup_map=lineup_map,
        player_game_info=player_game_info,
    )

    confirmed_results = sum(1 for r in results if r.get("confirmed") is True)
    print(f"Players scored: {len(results)}")
    print(f"Confirmed players in results: {confirmed_results}")

    body = build_email_body(results)
    print(body)

    send_email("Beat the Streak picks", body)
    print("\nEmail sent successfully.")
    
if __name__ == "__main__":
    main()
