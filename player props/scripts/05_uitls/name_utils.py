import re
import unicodedata


SUFFIXES = {
    "jr",
    "sr",
    "ii",
    "iii",
    "iv",
    "v",
}


NAME_ALIASES = {
    # Add known problem cases here
}


TEAM_ALIASES = {
    # NFL abbreviations
    "ARI": "ARI",
    "ATL": "ATL",
    "BAL": "BAL",
    "BUF": "BUF",
    "CAR": "CAR",
    "CHI": "CHI",
    "CIN": "CIN",
    "CLE": "CLE",
    "DAL": "DAL",
    "DEN": "DEN",
    "DET": "DET",
    "GB": "GB",
    "GNB": "GB",
    "HOU": "HOU",
    "IND": "IND",
    "JAC": "JAX",
    "JAX": "JAX",
    "KC": "KC",
    "KAN": "KC",
    "LAC": "LAC",
    "SD": "LAC",
    "LAR": "LAR",
    "LA": "LAR",
    "LV": "LV",
    "OAK": "LV",
    "MIA": "MIA",
    "MIN": "MIN",
    "NE": "NE",
    "NWE": "NE",
    "NO": "NO",
    "NOR": "NO",
    "NYG": "NYG",
    "NYJ": "NYJ",
    "PHI": "PHI",
    "PIT": "PIT",
    "SEA": "SEA",
    "SF": "SF",
    "SFO": "SF",
    "TB": "TB",
    "TAM": "TB",
    "TEN": "TEN",
    "WAS": "WSH",
    "WSH": "WSH",
}

NAME_ALIASES = {
    "gardner minshew": "gardner minshew",
    "gardner minshew ii": "gardner minshew",

    "patrick mahomes": "patrick mahomes",
    "patrick mahomes ii": "patrick mahomes",

    "anthony richardson": "anthony richardson",
    "anthony richardson sr": "anthony richardson",
}

def normalize_unicode(text: str) -> str:
    return unicodedata.normalize("NFKD", text)


def strip_suffixes(parts):
    while parts and parts[-1] in SUFFIXES:
        parts = parts[:-1]

    return parts


def clean_player_name(name):
    """
    Standardized player name cleaning.
    """

    if name is None:
        return None

    name = str(name).strip().lower()

    name = normalize_unicode(name)

    # Remove punctuation
    name = re.sub(r"[^\w\s]", "", name)

    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()

    parts = name.split()

    parts = strip_suffixes(parts)

    cleaned = " ".join(parts)

    cleaned = NAME_ALIASES.get(cleaned, cleaned)

    return cleaned


def clean_team(team):
    """
    Standardize NFL team abbreviations.
    """

    if team is None:
        return None

    team = str(team).strip().upper()

    return TEAM_ALIASES.get(team, team)