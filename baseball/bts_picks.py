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

from datetime import datetime
from zoneinfo import ZoneInfo

player_game_info = {}

def to_et_display(commence_time_str):
    dt_utc = datetime.fromisoformat(commence_time_str.replace("Z", "+00:00"))
    dt_et = dt_utc.astimezone(ZoneInfo("America/New_York"))
    return dt_et.strftime("%-I:%M %p ET")

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

def normalize_team_name(name: str) -> str:
    return (
        name.lower()
        .replace(".", "")
        .replace("st louis", "st. louis")
        .replace("chi white sox", "chicago white sox")
        .replace("chi cubs", "chicago cubs")
        .strip()
    )

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
            name = person.get("fullName")

            batting_order_raw = p.get("battingOrder")

            if not name or not batting_order_raw:
                continue

            try:
                batting_order = int(str(batting_order_raw)) // 100
            except:
                batting_order = None

            lineup[name] = {
                "confirmed": True,
                "batting_order": batting_order
            }

    return lineup

def build_lineup_map(events):
    today = datetime.now().strftime("%Y-%m-%d")
    mlb_games = get_mlb_games_for_date(today)

    print(f"MLB schedule games found: {len(mlb_games)}")

    lineup_map = {}

    for event in events:
        try:
            print(f"Checking event: {event.get('away_team')} at {event.get('home_team')}")
            game_pk = find_matching_game_pk(event, mlb_games)

            if not game_pk:
                print("  -> No matching MLB game found")
                continue

            print(f"  -> Matched game_pk: {game_pk}")

            confirmed = extract_confirmed_lineup(game_pk)
            print(f"  -> Confirmed lineup players found in this game: {len(confirmed)}")

            lineup_map.update(confirmed)

        except Exception as e:
            print(f"Lineup check failed for {event.get('home_team')} vs {event.get('away_team')}: {e}")

    return lineup_map

def lineup_priority(row):
    bo = row.get("batting_order")
    if bo is None:
        return 99
    return bo


def score_players(all_players, lineup_map=None, player_game_info=None):
    results = []

    for player, ladders in all_players.items():
        p_ge_1_list = []
        p_ge_2_list = []

        if 0.5 in ladders:
            p_ge_1_list.extend(x["over_prob"] for x in ladders[0.5])

        if 1.5 in ladders:
            p_ge_2_list.extend(x["over_prob"] for x in ladders[1.5])

        if not p_ge_1_list and not p_ge_2_list:
            continue

        if p_ge_1_list:
            p1 = mean(p_ge_1_list)
            lmbda = lambda_from_p_ge_1(p1)
        else:
            p_ge_2 = mean(p_ge_2_list)
            lmbda = lambda_from_p_ge_2(p_ge_2)
            p1 = poisson_p_ge_1(lmbda)

        confirmed = None
        batting_order = None
        if lineup_map and player in lineup_map:
            confirmed = lineup_map[player]["confirmed"]
            batting_order = lineup_map[player]["batting_order"]

        game_info = player_game_info.get(player, {}) if player_game_info else {}

        results.append({
            "player": player,
            "lambda": lmbda,
            "p_hit": p1,
            "books_0_5": len(ladders.get(0.5, [])),
            "books_1_5": len(ladders.get(1.5, [])),
            "confirmed": confirmed,
            "batting_order": batting_order,
            "start_time_et": game_info.get("start_time_et"),
            "matchup": game_info.get("matchup"),
        })

    # split confirmed vs unconfirmed
    confirmed_results = [r for r in results if r["confirmed"] is True]
    unconfirmed_results = [r for r in results if r["confirmed"] is not True]

    # sort each group
    confirmed_results.sort(key=lambda x: (-x["p_hit"], lineup_priority(x)))
    unconfirmed_results.sort(key=lambda x: (-x["p_hit"], lineup_priority(x)))

    if confirmed_results:
        return confirmed_results + unconfirmed_results

    return unconfirmed_results

def build_email_body(results):
    lines = []
    lines.append("Top Beat the Streak candidates for today\n")
    lines.append("----------------------------------------\n")

    for i, row in enumerate(results[:10], start=1):
        bo = row["batting_order"]
        if row["confirmed"] is True:
            status = "CONFIRMED"
        else:
            status = "unconfirmed"

        bo_txt = f", batting_order={bo}" if bo is not None else ""

        lines.append(
            f"{i}. {row['player']}: "
            f"P(1+ hit)={row['p_hit']:.1%}, "
            f"books(0.5)={row['books_0_5']}, "
            f"books(1.5)={row['books_1_5']}, "
            f"{status}{bo_txt}"
        )

    return "\n".join(lines)

def extract_hit_markets(event_data):
    players = defaultdict(lambda: defaultdict(list))

    for bookmaker in event_data.get("bookmakers", []):
        book_title = bookmaker.get("title", bookmaker.get("key", "Unknown"))

        for market in bookmaker.get("markets", []):
            market_key = market.get("key")
            if market_key not in {"batter_hits", "batter_hits_alternate"}:
                continue

            grouped = defaultdict(dict)

            for outcome in market.get("outcomes", []):
                # Odds API player props typically use description for player name
                player = outcome.get("description") or outcome.get("name")
                point = outcome.get("point")
                side = (outcome.get("name") or "").strip().lower()
                price = outcome.get("price")

                if player is None or point is None or price is None:
                    continue

                if side not in {"over", "under"}:
                    continue

                grouped[(player, float(point))][side] = price

            for (player, point), sides in grouped.items():
                if "over" not in sides or "under" not in sides:
                    continue

                over_prob = american_to_prob(int(sides["over"]))
                under_prob = american_to_prob(int(sides["under"]))
                fair_over, fair_under = no_vig_prob(over_prob, under_prob)

                players[player][point].append({
                    "book": book_title,
                    "market_key": market_key,
                    "over_prob": fair_over,
                    "under_prob": fair_under,
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

            for player, ladders in players.items():
                if player not in player_game_info:
                    player_game_info[player] = {
                        "start_time_et": start_time_et,
                        "matchup": f"{away_team} at {home_team}",
                    }

                for point, entries in ladders.items():
                    merged_players[player][point].extend(entries)

        except Exception as e:
            print(f"Failed odds pull for event {event_id}: {e}")

    point_counts = defaultdict(int)
    for player, ladders in merged_players.items():
        for point in ladders.keys():
            point_counts[point] += 1

    print("Point distribution:")
    for point in sorted(point_counts.keys()):
        print(f"  {point}: {point_counts[point]}")

    lineup_map = build_lineup_map(events)
    print(f"Lineup map players found: {len(lineup_map)}")

    results = score_players(
        merged_players,
        lineup_map=lineup_map,
        player_game_info=player_game_info
    )

    confirmed_results = sum(1 for r in results if r.get("confirmed") is True)
    print(f"Players scored: {len(results)}")
    print(f"Confirmed players in results: {confirmed_results}")

    body = build_email_body(results)
    print(body)

    try:
        send_email("Beat the Streak picks", body)
        print("\nEmail sent successfully.")
    except Exception as e:
        print(f"\nEmail failed: {e}")


if __name__ == "__main__":
    main()
