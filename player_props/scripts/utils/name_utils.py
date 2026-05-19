import re
import unicodedata


SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

NAME_ALIASES = {}

TEAM_ALIASES = {
    "ARI": "ARI", "ATL": "ATL", "BAL": "BAL", "BUF": "BUF",
    "CAR": "CAR", "CHI": "CHI", "CIN": "CIN", "CLE": "CLE",
    "DAL": "DAL", "DEN": "DEN", "DET": "DET",
    "GB": "GB", "GNB": "GB",
    "HOU": "HOU", "IND": "IND",
    "JAC": "JAX", "JAX": "JAX",
    "KC": "KC", "KAN": "KC",
    "LAC": "LAC", "SD": "LAC",
    "LAR": "LAR", "LA": "LAR",
    "LV": "LV", "OAK": "LV",
    "MIA": "MIA", "MIN": "MIN",
    "NE": "NE", "NWE": "NE",
    "NO": "NO", "NOR": "NO",
    "NYG": "NYG", "NYJ": "NYJ",
    "PHI": "PHI", "PIT": "PIT", "SEA": "SEA",
    "SF": "SF", "SFO": "SF",
    "TB": "TB", "TAM": "TB",
    "TEN": "TEN",
    "WAS": "WSH", "WSH": "WSH",
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
        return None

    team = str(team).strip().upper()
    return TEAM_ALIASES.get(team, team)