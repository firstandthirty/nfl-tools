import csv
import html
import json
import os
import smtplib
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo


# ============================================================================
# CONFIG
# ============================================================================

SPORT = "americanfootball_nfl"
MARKET = "spreads"
ODDS_FORMAT = "american"

API_URL = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"

SCRIPT_DIR = Path(__file__).resolve().parent
NFL_TOOLS_DIR = SCRIPT_DIR.parent

# Local credentials live here:
# C:\Users\brady\OneDrive\Desktop\nfl-tools\player_props\.env
LOCAL_ENV_FILE = NFL_TOOLS_DIR / "player_props" / ".env"

OUTPUT_FILE = SCRIPT_DIR / "line_shop_output.csv"

EASTERN = ZoneInfo("America/New_York")


# Massachusetts books ONLY.
#
# Tie-break priority is the order requested:
# DraftKings > FanDuel > BetMGM > Caesars > Fanatics > theScore
#
# Note: The Odds API still uses "espnbet" as the key for theScore Bet.
BOOKMAKERS = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "betmgm": "BetMGM",
    "williamhill_us": "Caesars",
    "fanatics": "Fanatics",
    "espnbet": "theScore Bet",
}

BOOK_PRIORITY = {
    "draftkings": 0,
    "fanduel": 1,
    "betmgm": 2,
    "williamhill_us": 3,
    "fanatics": 4,
    "espnbet": 5,
}


# Email configuration.
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


# ============================================================================
# ENVIRONMENT / SECRETS
# ============================================================================

def load_local_env():
    """
    Loads variables from:
        ../player_props/.env

    Environment variables already set by GitHub Actions take precedence.
    """

    if not LOCAL_ENV_FILE.exists():
        return

    with LOCAL_ENV_FILE.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)

            key = key.strip()
            value = value.strip().strip('"').strip("'")

            # Do not overwrite variables GitHub Actions already provided.
            os.environ.setdefault(key, value)


def get_credentials():
    load_local_env()

    required = [
        "ODDS_API_KEY",
        "SMTP_USER",
        "SMTP_PASS",
        "EMAIL_TO",
    ]

    missing = [
        name
        for name in required
        if not os.environ.get(name)
    ]

    if missing:
        raise RuntimeError(
            "Missing required environment variable(s): "
            + ", ".join(missing)
        )

    return {
        "api_key": os.environ["ODDS_API_KEY"],
        "smtp_user": os.environ["SMTP_USER"],
        "smtp_pass": os.environ["SMTP_PASS"],
        "email_to": os.environ["EMAIL_TO"],
    }


# ============================================================================
# ODDS API
# ============================================================================

def fetch_odds(api_key):
    """
    Fetch current NFL spread markets.

    The response is later filtered to the six Massachusetts sportsbooks.
    """

    params = {
        "apiKey": api_key,
        "regions": "us,us2",
        "markets": MARKET,
        "oddsFormat": ODDS_FORMAT,
        "dateFormat": "iso",
    }

    url = f"{API_URL}?{urllib.parse.urlencode(params)}"

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "nfl-line-shop/2.0",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )

            usage = {
                "remaining": response.headers.get(
                    "x-requests-remaining"
                ),
                "used": response.headers.get(
                    "x-requests-used"
                ),
                "last": response.headers.get(
                    "x-requests-last"
                ),
            }

            return data, usage

    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8")
            error_data = json.loads(body)

            message = error_data.get(
                "message",
                body,
            )

        except Exception:
            message = f"HTTP {exc.code}"

        raise RuntimeError(
            f"The Odds API request failed: {message}"
        ) from None

    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach The Odds API: {exc.reason}"
        ) from None


# ============================================================================
# LINE SHOPPING
# ============================================================================

def parse_datetime(value):
    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )


def format_spread(point):
    if point > 0:
        return f"+{point:g}"

    return f"{point:g}"


def format_price(price):
    if price > 0:
        return f"+{price}"

    return str(price)


def best_offer(offers):
    """
    Best line from the bettor's perspective.

    Priority:
        1. Best spread
        2. Best price
        3. Preferred sportsbook order

    Examples:
        +3.5 -110 beats +3 -105
        -2.5 -110 beats -3 -105
        +3 -105 beats +3 -110

    If everything is identical:
        DraftKings > FanDuel > BetMGM > Caesars > Fanatics > theScore
    """

    return max(
        offers,
        key=lambda x: (
            x["point"],
            x["price"],
            -BOOK_PRIORITY[x["bookmaker_key"]],
        ),
    )


def worst_offer(offers):
    """
    Worst line from the bettor's perspective.

    Priority:
        1. Worst spread
        2. Worst price

    For an exact tie, the lowest-priority sportsbook is shown.
    This makes it easy to see the full book range when everything
    else is identical.
    """

    return min(
        offers,
        key=lambda x: (
            x["point"],
            x["price"],
            -BOOK_PRIORITY[x["bookmaker_key"]],
        ),
    )


def find_lines(games):
    now = datetime.now(timezone.utc)

    rows = []

    for game in games:

        commence_time = parse_datetime(
            game["commence_time"]
        )

        # Ignore games that have already started.
        if commence_time <= now:
            continue

        away_team = game["away_team"]
        home_team = game["home_team"]

        offers_by_team = {
            away_team: [],
            home_team: [],
        }

        for bookmaker in game.get(
            "bookmakers",
            [],
        ):
            book_key = bookmaker.get("key")

            # Massachusetts books only.
            if book_key not in BOOKMAKERS:
                continue

            book_name = BOOKMAKERS[book_key]

            for market in bookmaker.get(
                "markets",
                [],
            ):
                if market.get("key") != "spreads":
                    continue

                for outcome in market.get(
                    "outcomes",
                    [],
                ):
                    team = outcome.get("name")
                    point = outcome.get("point")
                    price = outcome.get("price")

                    if team not in offers_by_team:
                        continue

                    if point is None or price is None:
                        continue

                    offers_by_team[team].append(
                        {
                            "bookmaker_key": book_key,
                            "bookmaker": book_name,
                            "point": float(point),
                            "price": int(price),
                            "last_update": market.get(
                                "last_update",
                                bookmaker.get(
                                    "last_update"
                                ),
                            ),
                        }
                    )

        for team in (
            away_team,
            home_team,
        ):

            offers = offers_by_team[team]

            if not offers:
                continue

            best = best_offer(offers)
            worst = worst_offer(offers)

            all_same = all(
                offer["point"] == best["point"]
                and offer["price"] == best["price"]
                for offer in offers
            )

            unique_spreads = len({
                offer["point"]
                for offer in offers
            })

            unique_prices = len({
                (
                    offer["point"],
                    offer["price"],
                )
                for offer in offers
            })

            rows.append(
                {
                    "event_id": game["id"],
                    "commence_time_utc":
                        commence_time.isoformat(),

                    "commence_time_et":
                        commence_time.astimezone(
                            EASTERN
                        ).strftime(
                            "%a %b %-d, %-I:%M %p ET"
                            if os.name != "nt"
                            else "%a %b %#d, %#I:%M %p ET"
                        ),

                    "away_team": away_team,
                    "home_team": home_team,
                    "team": team,

                    "best_spread": best["point"],
                    "best_price": best["price"],
                    "best_book": best["bookmaker"],
                    "best_book_key":
                        best["bookmaker_key"],

                    "worst_spread": worst["point"],
                    "worst_price": worst["price"],
                    "worst_book": worst["bookmaker"],
                    "worst_book_key":
                        worst["bookmaker_key"],

                    "books_available": len(offers),

                    "all_same": all_same,

                    "unique_spreads": unique_spreads,
                    "unique_offers": unique_prices,
                }
            )

    rows.sort(
        key=lambda x: (
            x["commence_time_utc"],
            x["away_team"],
            x["team"] != x["away_team"],
        )
    )

    return rows


# ============================================================================
# CONSOLE OUTPUT
# ============================================================================

def print_results(rows):
    print()
    print("=" * 88)
    print("NFL MASSACHUSETTS SPREAD LINE SHOP")
    print("=" * 88)

    if not rows:
        print("No upcoming NFL spread markets found.")
        return

    games = {}

    for row in rows:
        games.setdefault(
            row["event_id"],
            [],
        ).append(row)

    for game_rows in games.values():

        first = game_rows[0]

        print()
        print(
            f"{first['away_team']} @ "
            f"{first['home_team']}"
        )

        print(first["commence_time_et"])

        print("-" * 88)

        for row in game_rows:

            best = (
                f"{format_spread(row['best_spread'])} "
                f"{format_price(row['best_price'])}"
            )

            worst = (
                f"{format_spread(row['worst_spread'])} "
                f"{format_price(row['worst_price'])}"
            )

            if row["all_same"]:
                market_note = "ALL SAME"
            elif row["best_spread"] == row["worst_spread"]:
                market_note = "SAME SPREAD"
            else:
                market_note = ""

            print(
                f"{row['team']:<27} "
                f"BEST: {best:>11} "
                f"{row['best_book']:<12} | "
                f"WORST: {worst:>11} "
                f"{row['worst_book']:<12} "
                f"{market_note}"
            )

    print()
    print("=" * 88)


# ============================================================================
# CSV
# ============================================================================

def write_csv(rows):
    fields = [
        "event_id",
        "commence_time_utc",
        "commence_time_et",
        "away_team",
        "home_team",
        "team",

        "best_spread",
        "best_price",
        "best_book",
        "best_book_key",

        "worst_spread",
        "worst_price",
        "worst_book",
        "worst_book_key",

        "books_available",
        "all_same",
        "unique_spreads",
        "unique_offers",
    ]

    with OUTPUT_FILE.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()
        writer.writerows(rows)

    print(
        f"\nCSV saved to:\n{OUTPUT_FILE}"
    )


# ============================================================================
# EMAIL
# ============================================================================

def build_email_html(rows, usage):
    generated = datetime.now(
        EASTERN
    ).strftime("%B %d, %Y at %I:%M %p ET")

    games = {}

    for row in rows:
        games.setdefault(
            row["event_id"],
            [],
        ).append(row)

    game_sections = []

    for game_rows in games.values():

        first = game_rows[0]

        team_rows = []

        for row in game_rows:

            best_spread = format_spread(
                row["best_spread"]
            )

            best_price = format_price(
                row["best_price"]
            )

            worst_spread = format_spread(
                row["worst_spread"]
            )

            worst_price = format_price(
                row["worst_price"]
            )

            if row["all_same"]:
                status = (
                    '<strong style="color:#256029; font-size:11px;">'
                    'ALL SAME'
                    '</strong>'
                )

            elif row["best_spread"] == row["worst_spread"]:
                status = (
                    '<strong style="color:#8a4b08; font-size:11px;">'
                    'SAME SPREAD'
                    '</strong>'
                )

            else:
                status = ""

            team_rows.append(
                f"""
                <tr>
                    <td style="
                        padding:10px 8px;
                        border-bottom:1px solid #e5e7eb;
                        font-weight:600;
                    ">
                        {html.escape(row["team"])}
                        <div style="margin-top:4px;">
                            {status}
                        </div>
                    </td>

                    <td style="
                        padding:10px 8px;
                        border-bottom:1px solid #e5e7eb;
                    ">
                        <strong>
                            {best_spread} {best_price}
                        </strong>
                        <br>
                        <span style="
                            color:#555;
                            font-size:12px;
                        ">
                            {html.escape(row["best_book"])}
                        </span>
                    </td>

                    <td style="
                        padding:10px 8px;
                        border-bottom:1px solid #e5e7eb;
                    ">
                        <strong>
                            {worst_spread} {worst_price}
                        </strong>
                        <br>
                        <span style="
                            color:#555;
                            font-size:12px;
                        ">
                            {html.escape(row["worst_book"])}
                        </span>
                    </td>

                    <td style="
                        padding:10px 8px;
                        border-bottom:1px solid #e5e7eb;
                        text-align:center;
                    ">
                        {row["books_available"]}
                    </td>
                </tr>
                """
            )

        game_sections.append(
            f"""
            <div style="
                margin-bottom:24px;
                border:1px solid #dcdfe4;
                border-radius:8px;
                overflow:hidden;
            ">

                <div style="
                    padding:12px 14px;
                    background:#f5f6f8;
                ">
                    <div style="
                        font-size:17px;
                        font-weight:bold;
                    ">
                        {html.escape(first["away_team"])}
                        @
                        {html.escape(first["home_team"])}
                    </div>

                    <div style="
                        margin-top:3px;
                        color:#555;
                        font-size:13px;
                    ">
                        {html.escape(first["commence_time_et"])}
                    </div>
                </div>

                <table
                    width="100%"
                    cellpadding="0"
                    cellspacing="0"
                    style="
                        border-collapse:collapse;
                        font-size:14px;
                    "
                >
                    <thead>
                        <tr style="background:#fafafa;">
                            <th style="
                                text-align:left;
                                padding:8px;
                            ">
                                Team
                            </th>

                            <th style="
                                text-align:left;
                                padding:8px;
                            ">
                                Best Line
                            </th>

                            <th style="
                                text-align:left;
                                padding:8px;
                            ">
                                Worst Line
                            </th>

                            <th style="
                                text-align:center;
                                padding:8px;
                            ">
                                Books
                            </th>
                        </tr>
                    </thead>

                    <tbody>
                        {''.join(team_rows)}
                    </tbody>
                </table>

            </div>
            """
        )

    if not game_sections:
        game_sections.append(
            """
            <p>
                No upcoming NFL spread markets were found.
            </p>
            """
        )

    usage_html = ""

    if usage.get("remaining") is not None:
        usage_html += (
            f"API credits remaining: "
            f"{html.escape(str(usage['remaining']))}"
        )

    if usage.get("last") is not None:

        if usage_html:
            usage_html += " &nbsp; | &nbsp; "

        usage_html += (
            f"Credits used this request: "
            f"{html.escape(str(usage['last']))}"
        )

    return f"""
    <!DOCTYPE html>
    <html>
    <body style="
        margin:0;
        padding:0;
        background:#f3f4f6;
        font-family:Arial, Helvetica, sans-serif;
        color:#1f2937;
    ">

        <div style="
            max-width:800px;
            margin:0 auto;
            padding:24px 12px;
        ">

            <div style="
                background:white;
                border-radius:10px;
                padding:22px;
            ">

                <h1 style="
                    margin:0 0 4px 0;
                    font-size:23px;
                ">
                    NFL Spread Line Shop
                </h1>

                <div style="
                    color:#666;
                    font-size:13px;
                    margin-bottom:22px;
                ">
                    Massachusetts Sportsbooks Only
                    <br>
                    Generated {generated}
                </div>

                {''.join(game_sections)}

                <div style="
                    margin-top:20px;
                    padding-top:12px;
                    border-top:1px solid #ddd;
                    color:#777;
                    font-size:11px;
                    line-height:1.5;
                ">
                    Books:
                    DraftKings, FanDuel, BetMGM,
                    Caesars, Fanatics, theScore Bet
                    <br>

                    Best-line tie priority:
                    DraftKings → FanDuel → BetMGM →
                    Caesars → Fanatics → theScore Bet

                    {
                        "<br>" + usage_html
                        if usage_html
                        else ""
                    }
                </div>

            </div>

        </div>

    </body>
    </html>
    """


def build_email_text(rows):
    lines = []

    lines.append("NFL SPREAD LINE SHOP")
    lines.append("Massachusetts sportsbooks only")
    lines.append("")

    if not rows:
        lines.append(
            "No upcoming NFL spread markets found."
        )

        return "\n".join(lines)

    games = {}

    for row in rows:
        games.setdefault(
            row["event_id"],
            [],
        ).append(row)

    for game_rows in games.values():

        first = game_rows[0]

        lines.append(
            f"{first['away_team']} @ "
            f"{first['home_team']}"
        )

        lines.append(
            first["commence_time_et"]
        )

        for row in game_rows:

            best = (
                f"{format_spread(row['best_spread'])} "
                f"{format_price(row['best_price'])} "
                f"({row['best_book']})"
            )

            worst = (
                f"{format_spread(row['worst_spread'])} "
                f"{format_price(row['worst_price'])} "
                f"({row['worst_book']})"
            )

            if row["all_same"]:
                status = " [ALL SAME]"

            elif (
                row["best_spread"]
                == row["worst_spread"]
            ):
                status = " [SAME SPREAD]"

            else:
                status = ""

            lines.append(
                f"  {row['team']}"
            )

            lines.append(
                f"    Best:  {best}"
            )

            lines.append(
                f"    Worst: {worst}{status}"
            )

        lines.append("")

    return "\n".join(lines)


def send_email(
    rows,
    usage,
    smtp_user,
    smtp_pass,
    email_to,
):
    today = datetime.now(
        EASTERN
    ).strftime("%b %d")

    subject = (
        f"NFL Spread Line Shop - {today}"
    )

    message = MIMEMultipart(
        "alternative"
    )

    message["Subject"] = subject
    message["From"] = smtp_user
    message["To"] = email_to

    text_body = build_email_text(rows)
    html_body = build_email_html(
        rows,
        usage,
    )

    message.attach(
        MIMEText(
            text_body,
            "plain",
        )
    )

    message.attach(
        MIMEText(
            html_body,
            "html",
        )
    )

    with smtplib.SMTP(
        SMTP_HOST,
        SMTP_PORT,
        timeout=30,
    ) as server:

        server.ehlo()
        server.starttls()
        server.ehlo()

        server.login(
            smtp_user,
            smtp_pass,
        )

        server.sendmail(
            smtp_user,
            [email_to],
            message.as_string(),
        )

    print(
        f"\nEmail sent to {email_to}"
    )


# ============================================================================
# GITHUB ACTIONS SUMMARY
# ============================================================================

def write_github_summary(
    rows,
    usage,
):
    summary_path = os.getenv(
        "GITHUB_STEP_SUMMARY"
    )

    if not summary_path:
        return

    with open(
        summary_path,
        "a",
        encoding="utf-8",
    ) as f:

        f.write(
            "# NFL Spread Line Shop\n\n"
        )

        f.write(
            "Massachusetts sportsbooks only.\n\n"
        )

        if usage.get("last"):
            f.write(
                f"API credits used: "
                f"**{usage['last']}**  \n"
            )

        if usage.get("remaining"):
            f.write(
                f"API credits remaining: "
                f"**{usage['remaining']}**\n\n"
            )

        if not rows:
            f.write(
                "No upcoming NFL spreads found.\n"
            )

            return

        f.write(
            "| Game | Team | Best | Book | Worst | Book |\n"
        )

        f.write(
            "|---|---|---:|---|---:|---|\n"
        )

        for row in rows:

            game = (
                f"{row['away_team']} @ "
                f"{row['home_team']}"
            )

            best = (
                f"{format_spread(row['best_spread'])} "
                f"{format_price(row['best_price'])}"
            )

            worst = (
                f"{format_spread(row['worst_spread'])} "
                f"{format_price(row['worst_price'])}"
            )

            f.write(
                f"| {game} "
                f"| {row['team']} "
                f"| {best} "
                f"| {row['best_book']} "
                f"| {worst} "
                f"| {row['worst_book']} |\n"
            )


# ============================================================================
# MAIN
# ============================================================================

def main():
    try:

        credentials = get_credentials()

        print(
            "Fetching current NFL spread odds..."
        )

        print(
            "Books: DraftKings, FanDuel, BetMGM, "
            "Caesars, Fanatics, theScore Bet"
        )

        games, usage = fetch_odds(
            credentials["api_key"]
        )

        print(
            f"Games returned by API: {len(games)}"
        )

        if usage.get("last") is not None:
            print(
                f"API credits used this request: "
                f"{usage['last']}"
            )

        if usage.get("remaining") is not None:
            print(
                f"API credits remaining: "
                f"{usage['remaining']}"
            )

        rows = find_lines(games)

        print_results(rows)

        write_csv(rows)

        write_github_summary(
            rows,
            usage,
        )

        send_email(
            rows=rows,
            usage=usage,
            smtp_user=credentials["smtp_user"],
            smtp_pass=credentials["smtp_pass"],
            email_to=credentials["email_to"],
        )

    except Exception as exc:

        print(
            f"\nERROR: {exc}",
            file=sys.stderr,
        )

        sys.exit(1)


if __name__ == "__main__":
    main()