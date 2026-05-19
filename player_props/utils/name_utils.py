import re
import unicodedata

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

NAME_ALIASES = {}

TEAM_ALIASES = {
    # Free agent / missing
    "": "FA",
    "FA": "FA",
    "NAN": "FA",
    "NONE": "FA",
    "NULL": "FA",

    # Arizona Cardinals
    "ARI": "ARI",
    "ARZ": "ARI",

    # Atlanta Falcons
    "ATL": "ATL",

    # Baltimore Ravens
    "BAL": "BAL",
    "BLT": "BAL",

    # Buffalo Bills
    "BUF": "BUF",

    # Carolina Panthers
    "CAR": "CAR",

    # Chicago Bears
    "CHI": "CHI",

    # Cincinnati Bengals
    "CIN": "CIN",

    # Cleveland Browns
    "CLE": "CLE",
    "CLV": "CLE",

    # Dallas Cowboys
    "DAL": "DAL",

    # Denver Broncos
    "DEN": "DEN",

    # Detroit Lions
    "DET": "DET",

    # Green Bay Packers
    "GB": "GB",
    "GNB": "GB",

    # Houston Texans
    "HOU": "HOU",
    "HST": "HOU",

    # Indianapolis Colts
    "IND": "IND",

    # Jacksonville Jaguars
    "JAC": "JAX",
    "JAX": "JAX",

    # Kansas City Chiefs
    "KC": "KC",
    "KAN": "KC",
    "KCC": "KC",

    # Los Angeles Chargers
    "LAC": "LAC",
    "SD": "LAC",
    "SDG": "LAC",

    # Los Angeles Rams
    "LAR": "LAR",
    "LA": "LAR",
    "STL": "LAR",

    # Las Vegas Raiders
    "LV": "LV",
    "LVR": "LV",
    "OAK": "LV",
    "RAI": "LV",

    # Miami Dolphins
    "MIA": "MIA",

    # Minnesota Vikings
    "MIN": "MIN",

    # New England Patriots
    "NE": "NE",
    "NWE": "NE",
    "NEP": "NE",

    # New Orleans Saints
    "NO": "NO",
    "NOR": "NO",
    "NOS": "NO",

    # New York Giants
    "NYG": "NYG",

    # New York Jets
    "NYJ": "NYJ",

    # Philadelphia Eagles
    "PHI": "PHI",

    # Pittsburgh Steelers
    "PIT": "PIT",

    # Seattle Seahawks
    "SEA": "SEA",

    # San Francisco 49ers
    "SF": "SF",
    "SFO": "SF",
    "SFN": "SF",

    # Tampa Bay Buccaneers
    "TB": "TB",
    "TAM": "TB",
    "TBB": "TB",

    # Tennessee Titans
    "TEN": "TEN",
    "TIT": "TEN",

    # Washington Commanders / Football Team / Redskins
    "WAS": "WSH",
    "WSH": "WSH",
}


def clean_player_name(name):
    if name is None:
        return None

    name = unicodedata.normalize("NFKD", str(name).strip().lower())
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()

    parts = name.split()
    while parts and parts[-1] in SUFFIXES:
        parts = parts[:-1]

    cleaned = " ".join(parts)
    return NAME_ALIASES.get(cleaned, cleaned)


def clean_team(team):
    if team is None:
        return "FA"

    team = str(team).strip().upper()

    if team in {"", "NAN", "NONE", "NULL"}:
        return "FA"

    return TEAM_ALIASES.get(team, team)