# build_tracker.py
# Outputs:
#   nfl_offseason_tracker.md
#   nfl_offseason_tracker.html
#
# Inputs:
#   data/cap.csv -> https://www.spotrac.com/nfl/cap
#   data/free_agents.csv -> https://www.spotrac.com/nfl/free-agents
#   data/trade_value.csv
#   data/coaches.csv
#   Tankathon draft order (scraped)
#   NFL free agent moves (scraped)

from io import StringIO
import pandas as pd
import requests
import re
import html as html_lib
import time
from datetime import datetime

DRAFT_URL = "https://www.tankathon.com/nfl/full_draft"
ADDITIONS_URL = "https://www.nfl.com/news/2026-nfl-free-agency-tracker-latest-signings-trades-contract-info-for-all-32-teams"
DEPARTURES_URL = "https://www.nfl.com/news/2026-nfl-free-agency-free-agents-notable-departures-for-all-32-teams"

TEAM_ABBR_TO_FULL = {
    "ARI": "Arizona Cardinals",
    "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers",
    "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",
    "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos",
    "DET": "Detroit Lions",
    "GB":  "Green Bay Packers",
    "HOU": "Houston Texans",
    "IND": "Indianapolis Colts",
    "JAX": "Jacksonville Jaguars",
    "KC":  "Kansas City Chiefs",
    "LV":  "Las Vegas Raiders",
    "LAC": "Los Angeles Chargers",
    "LAR": "Los Angeles Rams",
    "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings",
    "NE":  "New England Patriots",
    "NO":  "New Orleans Saints",
    "NYG": "New York Giants",
    "NYJ": "New York Jets",
    "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks",
    "SF":  "San Francisco 49ers",
    "TB":  "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders",
    "WSH": "Washington Commanders",  # Tankathon alt
}

CITY_TO_FULL = {
    "Arizona": "Arizona Cardinals",
    "Atlanta": "Atlanta Falcons",
    "Baltimore": "Baltimore Ravens",
    "Buffalo": "Buffalo Bills",
    "Carolina": "Carolina Panthers",
    "Chicago": "Chicago Bears",
    "Cincinnati": "Cincinnati Bengals",
    "Cleveland": "Cleveland Browns",
    "Dallas": "Dallas Cowboys",
    "Denver": "Denver Broncos",
    "Detroit": "Detroit Lions",
    "Green Bay": "Green Bay Packers",
    "Houston": "Houston Texans",
    "Indianapolis": "Indianapolis Colts",
    "Jacksonville": "Jacksonville Jaguars",
    "Kansas City": "Kansas City Chiefs",
    "Las Vegas": "Las Vegas Raiders",
    "LA Chargers": "Los Angeles Chargers",
    "LA Rams": "Los Angeles Rams",
    "Chargers": "Los Angeles Chargers",
    "Rams": "Los Angeles Rams",
    "Miami": "Miami Dolphins",
    "Minnesota": "Minnesota Vikings",
    "New England": "New England Patriots",
    "New Orleans": "New Orleans Saints",
    "NY Giants": "New York Giants",
    "NY Jets": "New York Jets",
    "Philadelphia": "Philadelphia Eagles",
    "Pittsburgh": "Pittsburgh Steelers",
    "San Francisco": "San Francisco 49ers",
    "Seattle": "Seattle Seahawks",
    "Tampa Bay": "Tampa Bay Buccaneers",
    "Tennessee": "Tennessee Titans",
    "Washington": "Washington Commanders",
}

TEAM_TO_DIVISION = {
    "Buffalo Bills": "AFC East",
    "Miami Dolphins": "AFC East",
    "New England Patriots": "AFC East",
    "New York Jets": "AFC East",

    "Baltimore Ravens": "AFC North",
    "Cincinnati Bengals": "AFC North",
    "Cleveland Browns": "AFC North",
    "Pittsburgh Steelers": "AFC North",

    "Houston Texans": "AFC South",
    "Indianapolis Colts": "AFC South",
    "Jacksonville Jaguars": "AFC South",
    "Tennessee Titans": "AFC South",

    "Denver Broncos": "AFC West",
    "Kansas City Chiefs": "AFC West",
    "Las Vegas Raiders": "AFC West",
    "Los Angeles Chargers": "AFC West",

    "Dallas Cowboys": "NFC East",
    "New York Giants": "NFC East",
    "Philadelphia Eagles": "NFC East",
    "Washington Commanders": "NFC East",

    "Chicago Bears": "NFC North",
    "Detroit Lions": "NFC North",
    "Green Bay Packers": "NFC North",
    "Minnesota Vikings": "NFC North",

    "Atlanta Falcons": "NFC South",
    "Carolina Panthers": "NFC South",
    "New Orleans Saints": "NFC South",
    "Tampa Bay Buccaneers": "NFC South",

    "Arizona Cardinals": "NFC West",
    "Los Angeles Rams": "NFC West",
    "San Francisco 49ers": "NFC West",
    "Seattle Seahawks": "NFC West",
}

ABBR_SET = set(TEAM_ABBR_TO_FULL.keys())
HEADERS = {"User-Agent": "Mozilla/5.0"}

HEADERS2 = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

def fetch_html(url: str, debug_name: str) -> str:
    r = requests.get(url, headers=HEADERS2, timeout=30, allow_redirects=True)

    print(f"[fetch] {debug_name}: status={r.status_code} final_url={r.url} bytes={len(r.text or '')}")

    # If blocked or empty, fail loudly
    if r.status_code != 200:
        raise RuntimeError(f"{debug_name} fetch failed: HTTP {r.status_code} (saved debug_{debug_name}.html)")
    if not (r.text and r.text.strip()):
        raise RuntimeError(f"{debug_name} fetch returned empty HTML (saved debug_{debug_name}.html)")

    return r.text

def fetch_text_via_jina(url: str, label: str) -> str:
    """
    Fetch readable text via Jina reader. This should NEVER crash the script.
    If Jina is down/slow, return "" so the dashboard still renders.
    """
    jina_url = "https://r.jina.ai/http://" + url.replace("https://", "").replace("http://", "")

    # Jina can be flaky; do a couple quick retries with increasing timeouts.
    timeouts = [20, 45, 75]

    for i, t in enumerate(timeouts, 1):
        try:
            r = requests.get(jina_url, headers=HEADERS2, timeout=t)
            r.raise_for_status()
            txt = r.text or ""
            print(f"[fetch] {label} via jina: status={r.status_code} bytes={len(txt)} try={i}")
            return txt
        except requests.exceptions.RequestException as e:
            print(f"[warn] {label} via jina failed (try {i}/{len(timeouts)} timeout={t}s): {e}")

    print(f"[warn] {label} via jina failed completely; continuing without it.")
    return ""

# ---------------- NORMALIZATION ---------------- #

def norm_team(name) -> str:
    if pd.isna(name):
        return ""
    s = re.sub(r"\s+", " ", str(name)).strip()
    s = s.replace("N.Y.", "NY").replace("L.A.", "LA")
    if not s or s.lower() == "nan":
        return ""
    upper = s.upper()
    if upper in TEAM_ABBR_TO_FULL:
        return TEAM_ABBR_TO_FULL[upper]
    if s in CITY_TO_FULL:
        return CITY_TO_FULL[s]
    return s

def norm_team_tankathon(raw) -> str:
    if pd.isna(raw):
        return ""
    s = re.sub(r"\s+", " ", str(raw)).strip()
    s = s.replace("N.Y.", "NY").replace("L.A.", "LA")
    if not s or s.lower() == "nan":
        return ""

    # Fix duplicated strings like "ArizonaArizona"
    if len(s) % 2 == 0:
        half = s[: len(s) // 2]
        if half and half == s[len(s) // 2:]:
            s = half

    # Remove trailing trade abbreviations (DEN / WSH / etc.)
    parts = s.split(" ")
    while parts and parts[-1].upper() in ABBR_SET:
        parts.pop()
    s = " ".join(parts).strip()

    # Fix smashed strings like "WSHWashington" / "BUFBuffalo"
    # IMPORTANT: case-sensitive startswith to avoid "Arizona" matching "ARI"
    for abbr in sorted(ABBR_SET, key=len, reverse=True):
        if s.startswith(abbr) and len(s) > len(abbr):
            remainder = s[len(abbr):].strip()
            if remainder and remainder[0].isalpha():
                s = remainder
            break

    return norm_team(s)

# ---------------- HELPERS ---------------- #

import json

def extract_nfl_article_text(html: str) -> str:
    """
    NFL.com pages embed a JSON blob that includes `"articleBody":"...."`.
    This pulls the articleBody string out, unescapes it, and returns clean text.
    """
    if not html:
        return ""

    # Find the JSON string value for articleBody.
    # This regex grabs the quoted JSON string, including escaped quotes/newlines.
    m = re.search(r'"articleBody"\s*:\s*("([^"\\]|\\.)*")', html)
    if not m:
        return ""

    raw_json_string = m.group(1)  # includes surrounding quotes
    try:
        # json.loads will decode \n, \uXXXX, etc.
        body = json.loads(raw_json_string)
    except Exception:
        return ""

    body = clean_weird_unicode(body)

    # NFL sometimes includes html entities / tags inside body. Remove tags if present.
    body = re.sub(r"<br\s*/?>", "\n", body, flags=re.IGNORECASE)
    body = re.sub(r"</p\s*>", "\n", body, flags=re.IGNORECASE)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"[ \t]+\n", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    return body

def inject_newlines_around_teams(text: str, teams_full: set[str]) -> str:
    """
    Jina sometimes returns an article as 1 mega-line.
    This inserts line breaks around full team names so our line-based parser can work.
    """
    if not text:
        return ""

    # Normalize common separators into newlines/bullets
    t = clean_weird_unicode(text)

    # Turn common bullet chars into newlines
    t = t.replace("•", "\n• ").replace("·", "\n· ")

    # If the text has almost no newlines, we definitely need this
    if t.count("\n") < 10:
        # Replace each team name with \nTEAM\n
        # Sort by length so "New York Jets" matches before "Jets" (though you only use full names)
        teams_sorted = sorted(teams_full, key=len, reverse=True)
        pattern = r"(?<!\w)(" + "|".join(re.escape(x) for x in teams_sorted) + r")(?!\w)"
        t = re.sub(pattern, r"\n\1\n", t)

        # Also break up division headers if they’re smashed together
        t = re.sub(r"(?i)(AFC|NFC)\s+(EAST|NORTH|SOUTH|WEST)", r"\n\1 \2\n", t)

    # Clean up excessive blank lines
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t

def normalize_item_line(line: str) -> str:
    if not line:
        return line

    s = line.strip()

    # Remove image markdown completely
    s = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', s)

    # Remove leftover static nfl image URLs
    s = re.sub(r'https?://static\.www\.nfl\.com[^)\s]+', '', s)

    # Convert markdown links [Name](url) -> Name
    s = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', s)

    # Remove bold markers
    s = s.replace('**', '')

    # Remove (Team) artifacts
    s = re.sub(r'\(Team\)', '', s, flags=re.IGNORECASE)

    # Remove stray brackets
    s = s.replace('[', '').replace(']', '')

    # Collapse whitespace
    s = re.sub(r'\s+', ' ', s).strip()

    # Remove inline "Image 26" / "!Image 26:" artifacts from Jina
    s = re.sub(r"!?Image\s*\d+[:\]]?", "", s, flags=re.IGNORECASE)

    # Ensure single leading bullet
    if not s.startswith('*'):
        s = '* ' + s

    return s

def deep_join_strings(data) -> str:
    strings = []

    def walk(x):
        if x is None:
            return
        if isinstance(x, str):
            s = clean_weird_unicode(x)
            if len(s) >= 2 and not s.startswith("http"):
                strings.append(s)
            return
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
            return
        if isinstance(x, list):
            for v in x:
                walk(v)
            return

    walk(data)

    # de-dupe preserving order
    seen = set()
    out = []
    for s in strings:
        if s in seen:
            continue
        seen.add(s)
        out.append(s)

    return "\n".join(out)

def money_to_float(x) -> float:
    if x is None or pd.isna(x):
        return float("nan")
    s = str(x).strip()
    if not s or s.lower() == "nan":
        return float("nan")
    s = s.replace("$", "").replace(",", "").replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return float("nan")

def rank_desc(values_by_team: dict) -> dict:
    items = [(t, v) for t, v in values_by_team.items() if t and (v == v)]
    items.sort(key=lambda tv: tv[1], reverse=True)
    return {team: i + 1 for i, (team, _) in enumerate(items)}

def percentile_from_rank(rank: int | None, n: int = 32) -> float | None:
    if rank is None or n <= 1:
        return None
    return (n - rank) / (n - 1) * 100.0

def is_new(hired_year) -> bool:
    try:
        return int(hired_year) == 2026
    except Exception:
        return False

def fmt_staff(name, hired_year):
    if pd.isna(name) or not str(name).strip():
        return "VACANT"
    label = str(name).strip()
    if is_new(hired_year):
        label += " 🆕"
    return label

def esc(s: str) -> str:
    return html_lib.escape("" if s is None else str(s), quote=True)

def clean_weird_unicode(s: str) -> str:
    # NFL.com pages often include zero-width / weird whitespace characters
    if s is None:
        return ""
    s = str(s)
    # remove common zero-width / BOM-ish characters
    s = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", s)
    # collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s

def extract_team_items_from_text(text: str, teams_full: set[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {team: [] for team in teams_full}

    lines = str(text or "").splitlines()
    current_team = None
    current_bullet = None

    def find_team_in_header_line(s: str) -> str | None:
        # Only use NON-bullet lines as possible team headers
        # so "Chicago Bears" inside a bullet won't steal the section.
        for team in teams_full:
            if team in s:
                return team
        return None

    for raw in lines:
        s = str(raw or "").strip()
        if not s:
            continue

        low = s.lower()

        # Ignore nav / division junk
        if low in {
            "search by division",
            "afc east", "afc north", "afc south", "afc west",
            "nfc east", "nfc north", "nfc south", "nfc west",
        }:
            continue

        is_bullet = s.startswith("*")

        # Team detection: ONLY on non-bullet lines
        if not is_bullet:
            found_team = find_team_in_header_line(s)
            if found_team:
                if current_team and current_bullet:
                    out[current_team].append(current_bullet.strip())
                    current_bullet = None
                current_team = found_team
                continue

        # Bullet start
        if is_bullet:
            if current_team is None:
                continue

            if current_bullet:
                out[current_team].append(current_bullet.strip())

            current_bullet = s
            continue

        # Continuation line for current bullet
        if current_team and current_bullet:
            current_bullet += " " + s

    # flush last bullet
    if current_team and current_bullet:
        out[current_team].append(current_bullet.strip())

    return out

    def as_team(line: str) -> str | None:
        """
        Return canonical full team name if this line looks like a team header.
        Handles:
          - "Buffalo Bills"
          - "Buffalo Bills:"
          - "## Buffalo Bills"
          - "### Buffalo Bills"
          - "Buffalo Bills —"
          - "**Buffalo Bills**"
        """
        s = line.strip()

        # strip markdown header markers
        s = re.sub(r"^#{1,6}\s*", "", s).strip()

        # strip bold/italic wrappers
        s = s.strip("*_ ").strip()

        # strip trailing punctuation used as separators
        s = re.sub(r"[:\-—–]\s*$", "", s).strip()

        # exact match (case-insensitive)
        key = s.lower()
        if key in teams_lower:
            return teams_lower[key]

        return None

    def is_noise(line: str) -> bool:
        if not line:
            return True

        # common junk
        low = line.lower()
        if low.startswith(("en-us", "utf-8", "viewport", "dns-prefetch", "preconnect")):
            return True
        if "r.jina.ai" in low:
            return True
        if low.startswith(("cookie", "advert", "privacy", "terms", "copyright")):
            return True

        # division headers
        if re.fullmatch(r"(afc|nfc)\s+(east|north|south|west)", line.strip(), flags=re.I):
            return True

        # page-level headings
        if "free agency tracker" in low or "notable departures" in low:
            return True

        return False

    for line in lines:
        if is_noise(line):
            continue

        team_hit = as_team(line)
        if team_hit:
            cur_team = team_hit
            out.setdefault(cur_team, [])
            continue

        if not cur_team:
            continue

        # treat anything under a team header as an item IF it looks like content
        # ignore super short tokens
        if len(line) < 3:
            continue

        # Normalize to bullet-like strings for your parsers
        if not line.startswith("*"):
            line = "* " + line

        clean = normalize_item_line(line)
        if len(clean) > 3:
            out[cur_team].append(clean)

    return out

def parse_addition_bullet(b: str) -> dict:
    s = clean_weird_unicode(b)
    s = re.sub(r'^\*\s*', '', s).strip()

    left, sep, right = s.partition(':')
    details = right.strip()

    pos = ""
    player = ""

    # First try: position at the start (ideal)
    m_pos = re.match(r"^([A-Z]{1,4})\s+(.*)$", left.strip())
    if m_pos:
        pos = m_pos.group(1)
        player = m_pos.group(2).strip()
    else:
        # Fallback: find first POS token anywhere in the left side
        m_any = re.search(r"\b([A-Z]{1,4})\b\s+([A-Z][A-Za-z\.\'\-]+(?:\s+[A-Z][A-Za-z\.\'\-]+){0,4})", left)
        if m_any:
            pos = m_any.group(1)
            player = m_any.group(2).strip()
        else:
            player = left.strip()

    # Extract position if present
    pos = ""
    m_pos = re.match(r'^([A-Z]{1,4})\s+(.*)$', left.strip())
    if m_pos:
        pos = m_pos.group(1)
        player = m_pos.group(2).strip()
    else:
        player = left.strip()

    # Final cleanup
    player = re.sub(r'[^A-Za-z\.\'\- ]', '', player).strip()
    details = re.sub(r'!\[.*?\]', '', details)
    details = re.sub(r'\s+', ' ', details).strip()

    # Classification
    dlow = details.lower()
    typ = "Other"
    if "re-signed" in dlow:
        typ = "Re-signing"
    elif "signed" in dlow:
        typ = "Signing"
    elif "franchise tag" in dlow:
        typ = "Franchise tag"
    elif "acquired" in dlow and "trade" in dlow:
        typ = "Trade in"
    elif "extended" in dlow or "extension" in dlow:
        typ = "Extension"

    return {"Type": typ, "Pos": pos, "Player": player, "Details": details}

def parse_departure_bullet(b: str) -> dict:
    s = clean_weird_unicode(b)
    s = re.sub(r'^\*\s*', '', s).strip()

    # Convert markdown links [Name](url) -> Name
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)

    note = ""
    m_note = re.search(r'\(([^)]+)\)\s*$', s)
    if m_note:
        note = m_note.group(1).strip()
        s = s[:m_note.start()].strip()

    pos = ""
    m_pos = re.match(r'^([A-Z]{1,4})\s+(.*)$', s)
    if m_pos:
        pos = m_pos.group(1)
        player = m_pos.group(2).strip()
    else:
        player = s.strip()

    player = re.sub(r'[^A-Za-z\.\'\- ]', '', player).strip()

    typ = "Loss"
    nl = note.lower()
    if "trade" in nl:
        typ = "Trade out"
    elif "retire" in nl:
        typ = "Retired"

    return {"Type": typ, "Pos": pos, "Player": player, "Details": note}

def debug_script_markers(html: str, name: str):
    for key in ["__NEXT_DATA__", "application/ld+json", "articleBody", "__APOLLO_STATE__"]:
        idx = html.find(key)
        if idx != -1:
            start = max(0, idx - 200)
            end = min(len(html), idx + 200)
            break

def pick_to_num(p: str) -> int | None:
    """
    Extract overall pick number from a string like:
    "Round 3, Pick 65" -> 65
    """
    if p is None:
        return None
    s = str(p).replace("：", ":").replace("⁠", "")
    m = re.search(r"Pick\s+(\d+)", s)
    return int(m.group(1)) if m else None


def pick_value(p: str, chart: dict[int, float]) -> float | None:
    n = pick_to_num(p)
    if n is None:
        return None
    return float(chart.get(n, 0.0))

def extract_departures_team_items(text: str, teams_full: set[str]) -> dict[str, list[str]]:
    import re
    import unicodedata
    from collections import defaultdict

    def norm(s: str) -> str:
        s = str(s or "")
        s = html_lib.unescape(s)
        s = unicodedata.normalize("NFKC", s)
        s = s.replace("\u00a0", " ").replace("\ufeff", "")
        s = re.sub(r"\s+", " ", s).strip()
        return s

    lines = [norm(x) for x in (text or "").splitlines()]
    lines = [x for x in lines if x]

    team_set = {norm(t) for t in teams_full}
    out = defaultdict(list)

    division_headers = {
        "AFC EAST", "AFC NORTH", "AFC SOUTH", "AFC WEST",
        "NFC EAST", "NFC NORTH", "NFC SOUTH", "NFC WEST",
    }

    pos_line_re = re.compile(
        r"^(QB|RB|FB|WR|TE|OT|OG|C|OL|DT|DE|DL|EDGE|LB|ILB|OLB|CB|S|FS|SS|DB|K|P|LS|NT)\b",
        re.IGNORECASE
    )

    current_team = None

    for s in lines:
        if not s:
            continue

        low = s.lower()

        # skip obvious page junk
        if any(x in low for x in [
            "skip to main content",
            "search by division",
            "top 101 free agents",
            "trade grades",
            "rankings by position",
            "original top 101",
            "news home",
            "podcasts",
            "injuries",
            "transactions",
            "nfl writers",
            "series",
            "cookie settings",
            "privacy policy",
            "terms and conditions",
            "nfl enterprises llc",
        ]):
            continue

        if s in division_headers:
            current_team = None
            continue

        if re.match(r"^(AFC|NFC)\s+(East|North|South|West):", s, flags=re.I):
            current_team = None
            continue

        if s in team_set:
            current_team = s
            continue

        if current_team and pos_line_re.match(s):
            out[current_team].append(s)

    return dict(out)

# ---------------- CSV LOADERS ---------------- #

def load_cap_csv(path: str) -> dict:
    df = pd.read_csv(path)
    team_col = next((c for c in df.columns if "team" in c.lower()), df.columns[0])
    cap_col = next((c for c in df.columns if "cap" in c.lower() and "space" in c.lower()), None)
    if cap_col is None:
        cap_col = next((c for c in df.columns if "cap" in c.lower()), None)
    if cap_col is None:
        raise ValueError(f"Couldn't find cap column in {path}. Columns={list(df.columns)}")

    out = {}
    for _, row in df.iterrows():
        t = norm_team(row[team_col])
        if not t:
            continue
        out[t] = str(row[cap_col])
    return out

def load_free_agents_csv(path: str) -> dict:
    df = pd.read_csv(path)

    def find_col(*needles):
        for c in df.columns:
            if all(n in c.lower() for n in needles):
                return c
        return None

    player_col = find_col("player") or df.columns[0]
    pos_col = find_col("pos") or find_col("position")
    team_col = find_col("team")
    age_col = find_col("age")
    prev_aav_col = find_col("prev", "aav") or find_col("aav")

    missing = [x for x in [pos_col, team_col, age_col, prev_aav_col] if x is None]
    if missing:
        raise ValueError(
            "Free agents CSV columns couldn't be mapped.\n"
            f"Columns found: {list(df.columns)}\n"
            "Need columns for Team, Position, Age, Prev AAV."
        )

    df = df[[player_col, pos_col, age_col, team_col, prev_aav_col]].copy()
    df.columns = ["Player", "Position", "Age", "Team", "Prev AAV"]

    grouped = {}
    for team, g in df.groupby("Team"):
        t = norm_team(team)
        if not t:
            continue
        grouped[t] = g.drop(columns=["Team"]).reset_index(drop=True)

    return grouped

def load_coaches_csv(path: str) -> dict:
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]

    coaches = {}
    for _, row in df.iterrows():
        team = norm_team(row["Team"])
        if not team:
            continue
        coaches[team] = {
            "HC": row.get("HC"),
            "HC_Hired": row.get("HC_Hired"),
            "OC": row.get("OC"),
            "OC_Hired": row.get("OC_Hired"),
            "DC": row.get("DC"),
            "DC_Hired": row.get("DC_Hired"),
            "PlayCaller": row.get("PlayCaller"),
            "PlayCaller_Hired": row.get("PlayCaller_Hired"),
            "GM": row.get("GM"),
            "GM_Hired": row.get("GM_Hired"),
        }
    return coaches

def load_trade_value_csv(path: str) -> dict[int, float]:
    df = pd.read_csv(path)
    pick_col = next((c for c in df.columns if "pick" in c.lower()), df.columns[0])
    val_col = next((c for c in df.columns if "value" in c.lower()), df.columns[1])

    chart = {}
    for _, row in df.iterrows():
        try:
            pick = int(float(row[pick_col]))
            val = float(row[val_col])
            chart[pick] = val
        except Exception:
            continue

    if not chart:
        raise ValueError(f"Trade value CSV loaded but no values parsed: {path}")
    return chart

# ---------------- TANKATHON DRAFT ---------------- #

def load_tankathon_draft() -> dict[str, list[str]]:
    html = requests.get(DRAFT_URL, headers=HEADERS, timeout=30).text
    tables = pd.read_html(StringIO(html))

    out: dict[str, list[str]] = {}
    round_number = 1

    for table in tables:
        if table.shape[1] != 2:
            continue
        table.columns = ["Pick", "Team"]

        for _, row in table.iterrows():
            try:
                pick = str(int(float(row["Pick"]))).strip()
            except Exception:
                continue

            team = norm_team_tankathon(row["Team"])
            if not team:
                continue

            out.setdefault(team, []).append(f"Round {round_number}, Pick {pick}")

        round_number += 1

    return out

# ---------------- SCRAPE OFFSEASON MOVES ---------------- #
def load_nfl_offseason_moves() -> dict[str, pd.DataFrame]:
    import re
    import unicodedata

    teams_full = set(TEAM_ABBR_TO_FULL.values())

    # ---------------- helpers ----------------
    def strip_invisible_chars(s: str) -> str:
        s = str(s or "")
        out = []
        for ch in s:
            cat = unicodedata.category(ch)

            # keep normal whitespace, drop weird formatting/control chars
            if ch in ("\n", "\r", "\t", " "):
                out.append(ch)
            elif cat in {"Cf", "Cc"}:
                continue
            else:
                out.append(ch)
        return "".join(out)

    def normalize_name(s: str) -> str:
        s = unicodedata.normalize("NFKC", str(s or ""))
        s = strip_invisible_chars(s)

        # known weird whitespace chars
        s = (
            s.replace("\u00a0", " ")
            .replace("⁠", "")
        )

        s = re.sub(r"\s+", " ", s).strip()
        return s.strip(" •-*—:;|")

    def normalize_line(s: str) -> str:
        s = str(s or "")
        s = s.replace("：", ":").replace("⁠", "")
        s = clean_weird_unicode(s)
        s = html_lib.unescape(s)
        s = unicodedata.normalize("NFKC", s)
        s = strip_invisible_chars(s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def contains_any_team(s: str) -> bool:
        if not s:
            return False
        return any(t in s for t in teams_full)

    def is_junk_blob(s: str) -> bool:
        low = (s or "").strip().lower()
        junk = [
            "search by division",
            "back to top",
            "afc east", "afc north", "afc south", "afc west",
            "nfc east", "nfc north", "nfc south", "nfc west",
            "news ###",
            "###",
            "seahawks.com",
            "twitter.com",
            "instagram.com",
        ]
        return any(j in low for j in junk)

    def is_junk_player(player: str, details: str = "") -> bool:
        p = normalize_name(player).lower()
        d = normalize_line(details).lower()
        blob = (p + " " + d).strip()

        # If it clearly has a departure/transaction note, don't treat as junk
        move_markers = (
            "(retire", "(retiring", "(retired",
            "(trade", "(traded",
            "(release", "(released",
            "(waive", "(waived",
            "(cut",
            "(signed",
            "(to ",
        )
        if any(m in blob for m in move_markers):
            return False

        if is_junk_blob(blob):
            return True
        if blob.strip("* -").strip() == "":
            return True
        if "--------" in blob:
            return True
        return False
    
    def looks_like_team_note(note: str) -> bool:
        n = normalize_line(note).lower().strip()

        # full team names
        if any(team.lower() == n for team in teams_full):
            return True

        # mascot / final word, e.g. "patriots", "ravens", "titans"
        if any(team.lower().split()[-1] == n for team in teams_full):
            return True

        return False

    def clean_and_merge_team_bullets(lines: list[str]) -> list[str]:
        """
        Merge continuation lines back into the prior bullet and drop nav/separator junk.
        """
        if not lines:
            return []

        out_lines: list[str] = []

        continuation_starts = (
            "* in exchange for",
            "* in return for",
            "* for ",
            "* plus ",
            "* and ",
            "* with ",
            "* to ",
        )

        for raw in lines:
            s = normalize_line(raw)
            if not s:
                continue

            low = s.lower()

            if is_junk_blob(low):
                continue
            if low.strip("* -").strip() == "":
                continue
            s = re.sub(r"\s*-{6,}\s*$", "", s).strip()
            low = s.lower()
            if not s:
                continue

            # Remove weird empty paren bullet starter like "* () * ..."
            if low.startswith("* ()"):
                s2 = re.sub(r"^\*\s*\(\)\s*\*?\s*", "* ", s).strip()
                if len(s2) < 5:
                    continue
                s = s2
                low = s.lower()

            if any(low.startswith(x) for x in continuation_starts) and out_lines:
                out_lines[-1] = (out_lines[-1].rstrip() + " " + s.lstrip("* ").strip()).strip()
                continue

            out_lines.append(s)

        return out_lines

    def clean_details(details: str) -> str:
        d = normalize_line(details)

        # markdown images + "Image 26" junk
        d = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', d)
        d = re.sub(r'!\[[^\]]*\]', '', d)
        d = re.sub(r'!?Image\s*\d+[:\]]?', '', d, flags=re.I)

        # remove "(Team)" marker
        d = re.sub(r'\s*\(Team\)\s*', ' ', d, flags=re.I)

        d = re.sub(r"\s+", " ", d).strip()
        return d

    def classify_add(details: str) -> str:
        dlow = (details or "").lower()
        if "transition tag" in dlow:
            return "Transition tag"
        if "franchise tag" in dlow:
            return "Franchise tag"
        if "re-signed" in dlow or "re-signing" in dlow or "re signing" in dlow:
            return "Re-signing"
        if "trade" in dlow and ("acquired" in dlow or "traded for" in dlow or "being acquired" in dlow):
            return "Trade in"
        if "extension" in dlow or "extended" in dlow:
            return "Extension"
        if "signed" in dlow or "signing" in dlow or "agreed to terms" in dlow or "expected to sign" in dlow:
            return "Signing"
        return "Other"

    def classify_dep(details: str) -> str:
        dlow = (details or "").lower()
        if "trade" in dlow or "traded" in dlow:
            return "Trade out"
        if "retir" in dlow or "retired" in dlow:
            return "Retired"
        return "Loss"

    def split_multi_moves(line: str) -> list[str]:
        """
        Splits glued bullets like:
        "* QB X: ... * S Y: ..."
        into separate chunks.
        """
        s = normalize_line(line)
        if not s:
            return []

        # Make [Name](url) -> Name, remove bold markers
        s = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', s)
        s = s.replace("**", "")

        # Bullet marker split first (best for Jina)
        if "*" in s:
            s2 = re.sub(r'^\*\s*', '', s)  # remove leading "*"
            parts = re.split(
                r'\s*\*\s*(?=(?:QB|RB|FB|WR|TE|OT|OG|C|OL|DT|DE|DL|EDGE|LB|ILB|OLB|CB|S|FS|SS|DB|K|P|LS|NT)\b)',
                s2,
                flags=re.IGNORECASE
            )
            chunks = []
            for p in parts:
                p = p.strip()
                if not p:
                    continue
                p = re.sub(r'^\*\s*', '', p).strip()
                if p:
                    chunks.append(p)
            if chunks:
                return chunks

        # Fallback: split before "POS Player:"
        starts = [m.start() for m in re.finditer(r'(?:^|\s)([A-Z]{1,4})\s+[A-Za-z][^:]{1,80}\s*:', s)]
        if not starts:
            return [s]

        chunks = []
        for i, start in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else len(s)
            chunk = s[start:end].strip()
            chunk = re.sub(r'^\*\s*', '', chunk).strip()
            if chunk:
                chunks.append(chunk)

        return chunks or [s]

    # ---------------- fetch/extract ----------------
    add_text = fetch_html(ADDITIONS_URL, "additions")
    dep_text = fetch_html(DEPARTURES_URL, "departures")

    debug_script_markers(add_text, "additions")
    debug_script_markers(dep_text, "departures")

    add_visible = extract_nfl_article_text(add_text)
    dep_visible = extract_nfl_article_text(dep_text)

    print(f"[parse] additions articleBody chars={len(add_visible or '')} contains_team={contains_any_team(add_visible)}")
    print(f"[parse] departures articleBody chars={len(dep_visible or '')} contains_team={contains_any_team(dep_visible)}")

    add_use_jina = (not contains_any_team(add_visible)) or (len(add_visible or "") < 5000)
    dep_use_jina = (not contains_any_team(dep_visible)) or (len(dep_visible or "") < 5000)

    if add_use_jina:
        print("[parse] additions articleBody looked weak -> trying jina fallback")
        jina_add = fetch_text_via_jina(ADDITIONS_URL, "additions")
        if jina_add:
            add_visible = jina_add
            print(f"[parse] additions using jina text chars={len(add_visible)}")
        else:
            print("[parse] additions jina returned empty; keeping articleBody text")
    else:
        print("[parse] additions using articleBody text")

    if dep_use_jina:
        print("[parse] departures articleBody looked weak -> trying jina fallback")
        jina_dep = fetch_text_via_jina(DEPARTURES_URL, "departures")
        if jina_dep:
            dep_visible = jina_dep
            print(f"[parse] departures using jina text chars={len(dep_visible)}")
        else:
            print("[parse] departures jina returned empty; keeping articleBody text")
    else:
        print("[parse] departures using articleBody text")

    add_bullets = extract_team_items_from_text(add_visible, teams_full)
    dep_bullets = extract_departures_team_items(dep_visible, teams_full)

    add_total = sum(len(v) for v in add_bullets.values())
    dep_total = sum(len(v) for v in dep_bullets.values())

    print(f"[parse] additions team bullets found={add_total}")
    print(f"[parse] departures team bullets found={dep_total}")

    sample_team = "New England Patriots"
    print(f"[debug] sample additions for {sample_team}: {add_bullets.get(sample_team, [])[:3]}")
    print(f"[debug] sample departures for {sample_team}: {dep_bullets.get(sample_team, [])[:3]}")

    # ---------------- parse ----------------
    out: dict[str, pd.DataFrame] = {}

    ALLOWED_POS = {
        "QB","RB","FB","WR","TE","OT","OG","C","OL",
        "DT","DE","DL","EDGE","LB","ILB","OLB",
        "CB","S","FS","SS","DB",
        "K","P","LS","NT"
    }

    POS_PATTERN = r"QB|RB|FB|WR|TE|OT|OG|C|OL|DT|DE|DL|EDGE|LB|ILB|OLB|CB|S|FS|SS|DB|K|P|LS|NT"
    add_pos_pat = r"(?:QB|RB|FB|WR|TE|OT|OG|C|OL|DT|DE|DL|EDGE|LB|ILB|OLB|CB|S|FS|SS|DB|K|P|LS|NT)"

    add_re = re.compile(
        rf"^(?P<pos>{add_pos_pat})\b\s+(?P<player>.+?)\s*(?::|—|\s-\s)\s*(?P<details>.+)$",
        re.IGNORECASE,
    )

    move_words_add = (
        "signed", "signing",
        "re-signed", "resigned", "re signing", "re-signing",
        "extension", "extended",
        "trade", "traded", "acquired", "being acquired",
        "released", "waived", "cut", "retired",
        "tag", "franchise", "transition",
        "agreed to terms", "expected to sign"
    )

    # departures "definitely gone" notes
    note_keywords = ("trade", "traded", "release", "released", "waive", "waived", "cut",
                     "retire", "retiring", "retired", "signed", "to ")

    for team in sorted(teams_full):
        rows: list[dict] = []

        add_lines = clean_and_merge_team_bullets(add_bullets.get(team, []))
        dep_lines = clean_and_merge_team_bullets(dep_bullets.get(team, []))

        # ---- ADDITIONS ----
        for raw in add_lines:
            base = normalize_item_line(raw)
            base = normalize_line(base)

            base = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', base)
            base = re.sub(r'【\d+†([^】]+)】', r'\1', base)
            base = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', base)
            base = base.replace("**", "")
            base = re.sub(r'^\*\s*', '* ', base).strip()

            # restore missing space between position and player
            base = re.sub(
                rf"^(\*?\s*)({POS_PATTERN})(?=[A-Z]\w)",
                r"\1\2 ",
                base,
                flags=re.IGNORECASE
            )

            base = normalize_line(base)

            for chunk in split_multi_moves(base):
                s = normalize_line(chunk)
                if not s:
                    continue

                # strip markdown/images/bold + leading bullet markers
                s = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', s)
                s = re.sub(r'【\d+†([^】]+)】', r'\1', s)
                s = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', s)
                s = s.replace("**", "")
                s = re.sub(r'^\*\s*', '', s).strip()
                s = re.sub(r'^\(\)\s*\*\s*', '', s).strip()
                s = re.sub(r'^\(\)\s*', '', s).strip()
                s = re.sub(r'^\-\-\-+\s*', '', s).strip()
                s = normalize_line(s)

                if is_junk_blob(s):
                    continue

                m = add_re.search(s)
                if not m:
                    continue

                pos = re.sub(r"[^A-Za-z]", "", normalize_line(m.group("pos"))).upper()
                if pos not in ALLOWED_POS:
                    continue

                player = normalize_name(m.group("player"))
                details = clean_details(m.group("details"))

                dlow = details.lower()
                if not any(w in dlow for w in move_words_add):
                    continue

                if len(player) < 3 or "image" in player.lower() or not re.search(r"[A-Za-z]", player):
                    continue
                if is_junk_player(player, details):
                    continue

                rows.append({
                    "Type": classify_add(details),
                    "Pos": pos,
                    "Player": player,
                    "Details": details,
                })

        # ---- DEPARTURES (token parse) ----
        dep_team_text = " ".join(dep_lines)

        for raw in dep_lines:
            t = normalize_line(raw)
            if not t:
                continue

            t = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', t)
            t = t.replace("**", "")
            t = re.sub(r'^\*\s*', '', t).strip()
            t = normalize_line(t)

            if is_junk_blob(t) or "###" in t or "news" in t.lower():
                continue

            mdep = re.search(
                r"""^(?P<pos>QB|RB|FB|WR|TE|OT|OG|C|OL|DT|DE|DL|EDGE|LB|ILB|OLB|CB|S|FS|SS|DB|K|P|LS|NT)\b
                    \s+
                    (?P<player>.+?)
                    \s*
                    (?:
                        \((?P<note_paren>[^)]+)\) |
                        [:—-]\s*(?P<note_sep>.+) |
                        (?P<note_bare>(?:signed|traded|released|waived|cut|retired|retiring)\b.+)
                    )?
                    $""",
                t,
                flags=re.IGNORECASE | re.VERBOSE
            )

            if not mdep:
                continue

            pos = re.sub(r"[^A-Za-z]", "", normalize_line(mdep.group("pos"))).upper()
            if pos not in ALLOWED_POS:
                continue

            player = normalize_name(mdep.group("player"))
            note = normalize_line(
                mdep.group("note_paren") or
                mdep.group("note_sep") or
                mdep.group("note_bare") or
                ""
            )

            note_low = note.lower()

            # only keep actual departures, not plain FAs
            if not note:
                continue
            if not any(k in note_low for k in note_keywords) and not looks_like_team_note(note_low):
                continue

            details = clean_details(f"({note})")

            if len(player) < 3 or "image" in player.lower() or not re.search(r"[A-Za-z]", player):
                continue
            if is_junk_player(player, details):
                continue

            rows.append({
                "Type": classify_dep(details),
                "Pos": pos,
                "Player": player,
                "Details": details,
            })
        df = pd.DataFrame(rows, columns=["Type", "Pos", "Player", "Details"])

        if not df.empty:
            order = {
                "Signing": 1,
                "Re-signing": 2,
                "Extension": 3,
                "Franchise tag": 4,
                "Transition tag": 5,
                "Trade in": 6,
                "Trade out": 7,
                "Retired": 8,
                "Loss": 9,
                "Other": 10,
            }
            df["_o"] = df["Type"].map(order).fillna(99).astype(int)
            df = df.sort_values(["_o", "Pos", "Player"]).drop(columns=["_o"]).reset_index(drop=True)

        dep_count = 0 if df.empty else int(df["Type"].isin(["Loss", "Trade out", "Retired"]).sum())
        if dep_count:
            print(f"[team] {team}: departures parsed={dep_count}")

        out[team] = df

    return out
# ---------------- MARKDOWN RENDER ---------------- #

def render_team_md(team: str,
                   cap_display: str,
                   cap_rank: int | None,
                   cap_pct: float | None,
                   fa_df: pd.DataFrame | None,
                   coaches: dict,
                   picks: list[str] | None,
                   draft_points: float | None,
                   draft_rank: int | None,
                   draft_pct: float | None,
                   moves_df: pd.DataFrame | None) -> str:
    s = []
    s.append(f"## {team}\n\n")

    s.append("**Cap Space:**\n")
    if cap_rank is not None:
        pct_txt = f", {cap_pct:.0f}th pct" if cap_pct is not None else ""
        s.append(f"- Projected: **{cap_display}** (#{cap_rank}{pct_txt})\n\n")
    else:
        s.append(f"- Projected: **{cap_display}**\n\n")
    
    s.append("**Offseason Moves (NFL.com):**\n\n")
    if moves_df is None or moves_df.empty:
        s.append("_No moves found yet._\n\n")
    else:
        cols = [c for c in ["Type", "Pos", "Player"] if c in moves_df.columns]
        show_df = moves_df[cols].copy()
        s.append(show_df.to_markdown(index=False))
        s.append("\n\n")

    staff = coaches.get(team, {})
    s.append("**Coaching Staff:**\n")
    s.append(f"- HC: {fmt_staff(staff.get('HC'), staff.get('HC_Hired'))}\n")
    s.append(f"- OC: {fmt_staff(staff.get('OC'), staff.get('OC_Hired'))}\n")
    s.append(f"- DC: {fmt_staff(staff.get('DC'), staff.get('DC_Hired'))}\n")
    s.append(f"- Play Caller: {fmt_staff(staff.get('PlayCaller'), staff.get('PlayCaller_Hired'))}\n")
    s.append(f"- GM: {fmt_staff(staff.get('GM'), staff.get('GM_Hired'))}\n\n")

    s.append("**Free Agents:**\n\n")
    if fa_df is None or fa_df.empty:
        s.append("_No free agents found._\n\n")
    else:
        s.append(fa_df.to_markdown(index=False))
        s.append("\n\n")

    if draft_points is not None and draft_rank is not None:
        pct_txt = f", {draft_pct:.0f}th pct" if draft_pct is not None else ""
        s.append(f"**Draft Capital:** **{draft_points:.1f} pts** (#{draft_rank}{pct_txt})\n\n")
    else:
        s.append("**Draft Capital:**\n\n")

    if not picks:
        s.append("_No picks found._\n\n")
    else:
        for i, p in enumerate(picks, 1):
            s.append(f"{i}. {p}\n")
        s.append("\n")

    s.append("---\n\n")
    return "".join(s)

# ---------------- HTML RENDER ---------------- #

def badge_bar(pct: float | None, label: str) -> str:
    if pct is None:
        return (
            '<div class="metric">'
            f'<div class="metric-top"><span class="metric-label">{esc(label)}</span><span class="metric-val">N/A</span></div>'
            '<div class="bar"><div class="fill" style="width:0%"></div></div>'
            '</div>'
        )
    width = max(0.0, min(100.0, float(pct)))
    return f"""
    <div class="metric">
      <div class="metric-top">
        <span class="metric-label">{esc(label)}</span>
        <span class="metric-val">{width:.0f}th pct</span>
      </div>
      <div class="bar"><div class="fill" style="width:{width:.1f}%"></div></div>
    </div>
    """

def render_team_html(
    team: str,
    cap_display: str,
    cap_rank: int | None,
    cap_pct: float | None,
    fa_df: pd.DataFrame | None,
    moves_df: pd.DataFrame | None,
    coaches: dict,
    picks: list[str] | None,
    draft_points: float | None,
    draft_rank: int | None,
    draft_pct: float | None,
    chart: dict[int, float],
) -> str:
    # ---- staff ----
    staff = coaches.get(team, {})
    hc = fmt_staff(staff.get("HC"), staff.get("HC_Hired"))
    oc = fmt_staff(staff.get("OC"), staff.get("OC_Hired"))
    dc = fmt_staff(staff.get("DC"), staff.get("DC_Hired"))
    pc = fmt_staff(staff.get("PlayCaller"), staff.get("PlayCaller_Hired"))
    gm = fmt_staff(staff.get("GM"), staff.get("GM_Hired"))

    # ---- division mapping ----
    division = TEAM_TO_DIVISION.get(team, "")
    division_slug = division.lower().replace(" ", "-")

    # ---- cap/draft meta lines ----
    cap_line = "N/A" if cap_display is None else str(cap_display)
    if cap_rank is not None:
        cap_line = f"{cap_line} (#{cap_rank})"

    draft_line = "N/A"
    if draft_points is not None and draft_rank is not None:
        draft_line = f"{draft_points:.1f} pts (#{draft_rank})"

    # ---- move helpers ----
    def type_to_badge(t) -> str:
        tl = str(t).lower()
        if "re-sign" in tl:
            cls = "resigning"
        elif "trade" in tl:
            cls = "trade"
        elif "loss" in tl or "retire" in tl:
            cls = "loss"
        elif "sign" in tl:
            cls = "signing"
        elif "franchise" in tl:
            cls = "tag"
        elif "transition" in tl:
            cls = "tag"
        elif "extension" in tl:
            cls = "resigning"
        else:
            cls = "other"
        return f'<span class="badge {cls}">{esc(t)}</span>'

    def render_moves_table(df: pd.DataFrame) -> str:
        if df is None or df.empty:
            return '<div class="muted">None.</div>'

        cols = [c for c in ["Type", "Pos", "Player"] if c in df.columns]
        show_df = df[cols].copy() if cols else df.copy()

        if "Type" in show_df.columns:
            show_df["Type"] = show_df["Type"].apply(type_to_badge)

        table_html = show_df.to_html(index=False, classes="table", border=0, escape=False)
        return f'<div class="table-wrap">{table_html}</div>'

    # ---- offseason moves grouped ----
    moves_html = '<div class="muted">No moves found yet.</div>'
    if moves_df is not None and not moves_df.empty:
        move_type = moves_df["Type"].fillna("").astype(str) if "Type" in moves_df.columns else pd.Series([], dtype=str)

        additions_mask = move_type.isin(["Signing", "Trade in"])
        retentions_mask = move_type.isin(["Re-signing", "Extension", "Franchise tag", "Transition tag"])
        departures_mask = move_type.isin(["Loss", "Trade out", "Retired"])

        additions_df = moves_df[additions_mask].copy()
        retentions_df = moves_df[retentions_mask].copy()
        departures_df = moves_df[departures_mask].copy()
        other_df = moves_df[~(additions_mask | retentions_mask | departures_mask)].copy()

        additions_n = len(additions_df)
        retentions_n = len(retentions_df)
        departures_n = len(departures_df)
        other_n = len(other_df)

        summary_bits = [
            f"<span><strong>{additions_n}</strong> additions</span>",
            f"<span><strong>{retentions_n}</strong> retentions</span>",
            f"<span><strong>{departures_n}</strong> departures</span>",
        ]
        if other_n:
            summary_bits.append(f"<span><strong>{other_n}</strong> other</span>")

        sections = []

        sections.append(f"""
        <div class="moves-group">
          <div class="moves-group-title">Additions</div>
          {render_moves_table(additions_df)}
        </div>
        """)

        sections.append(f"""
        <div class="moves-group">
          <div class="moves-group-title">Retentions</div>
          {render_moves_table(retentions_df)}
        </div>
        """)

        sections.append(f"""
        <div class="moves-group">
          <div class="moves-group-title">Departures</div>
          {render_moves_table(departures_df)}
        </div>
        """)

        if other_n:
            sections.append(f"""
            <div class="moves-group">
              <div class="moves-group-title">Other</div>
              {render_moves_table(other_df)}
            </div>
            """)

        moves_html = f"""
        <div class="moves-summary">
          {'<span class="dot">•</span>'.join(summary_bits)}
        </div>
        <div class="moves-groups">
          {''.join(sections)}
        </div>
        """

    # ---- free agents table ----
    fa_html = '<div class="muted">No free agents found.</div>'
    if fa_df is not None and not fa_df.empty:
        table_html = fa_df.to_html(index=False, classes="table", border=0, escape=True)
        fa_html = f'<div class="table-wrap">{table_html}</div>'

    # ---- picks ----
    picks_html = '<div class="muted">No picks found.</div>'
    if picks:
        lis = []
        for p in picks:
            val = pick_value(p, chart)
            if val is None:
                lis.append(f"<li>{esc(p)}</li>")
            else:
                lis.append(f"<li>{esc(p)} <span class='pick-val'>({val:.1f})</span></li>")

        picks_html = "<ol class='picks'>\n" + "\n".join(lis) + "\n</ol>"
        
    cap_num = money_to_float(cap_display)
    cap_sort = "" if pd.isna(cap_num) else f"{cap_num:.6f}"
    draft_sort = "" if draft_points is None else f"{float(draft_points):.6f}"

    return f"""
    
<section class="card team"
  data-team="{esc(team).lower()}"
  data-team-display="{esc(team)}"
  data-division="{esc(division_slug)}"
  data-cap-value="{cap_sort}"
  data-draft-value="{draft_sort}">  <div class="card-header">
    <div class="team-head">
      <div class="team-name">{esc(team)}</div>
      <div class="meta">
        <div class="meta-item"><span class="k">Division</span><span class="v">{esc(division)}</span></div>
        <div class="meta-item"><span class="k">Cap Space</span><span class="v">{esc(cap_line)}</span></div>
        <div class="meta-item"><span class="k">Draft Capital</span><span class="v">{esc(draft_line)}</span></div>
      </div>
    </div>
  </div>

  <div class="metrics">
    {badge_bar(cap_pct, "Cap Space")}
    {badge_bar(draft_pct, "Draft Capital")}
  </div>

  <div class="grid grid-top">
    <div class="panel">
      <div class="panel-title">Coaching</div>
      <ul class="staff">
        <li><span class="role">HC</span><span class="name">{esc(hc)}</span></li>
        <li><span class="role">OC</span><span class="name">{esc(oc)}</span></li>
        <li><span class="role">DC</span><span class="name">{esc(dc)}</span></li>
        <li><span class="role">Play Caller</span><span class="name">{esc(pc)}</span></li>
        <li><span class="role">GM</span><span class="name">{esc(gm)}</span></li>
      </ul>
    </div>

    <div class="panel">
      <div class="panel-title">Draft Picks</div>
      {picks_html}
    </div>
  </div>

  <div class="panel moves-panel" data-collapsible="moves">
    <div class="panel-toggle" role="button" tabindex="0">
      <span class="chev">›</span>
      <div class="panel-title panel-title-inline">Offseason Moves</div>
    </div>
    <div class="panel-body">
      {moves_html}
    </div>
  </div>

  <div class="panel" data-collapsible="fa">
    <div class="panel-toggle" role="button" tabindex="0">
      <span class="chev">›</span>
      <div class="panel-title panel-title-inline">Free Agents</div>
    </div>
    <div class="panel-body">
      {fa_html}
    </div>
  </div>
</section>
""".strip()

def build_html_page(team_sections_html: str, last_updated: str) -> str:
    template = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>NFL Offseason Tracker</title>
<style>
  :root{
    --bg:#0b0f17;
    --card:#121a26;
    --muted:#9aa4b2;
    --text:#e7edf5;
    --border:rgba(255,255,255,0.08);
    --accent:#5aa2ff;
  }

  *{ box-sizing:border-box; }

  body{
    margin:0;
    font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
    background: linear-gradient(180deg,#070a10 0%, var(--bg) 60%);
    color:var(--text);
  }

  .wrap{ max-width:1100px; margin:0 auto; padding:24px 16px 80px; }

  header{
    position:sticky; top:0; z-index:50;
    backdrop-filter: blur(10px);
    background: rgba(11,15,23,0.75);
    border-bottom:1px solid var(--border);
  }

  .topbar{
    display:flex;
    gap:12px;
    align-items:center;
    flex-wrap:wrap;
    padding:14px 16px;
    max-width:1100px;
    margin:0 auto;
  }

  .brand{
    display:flex;
    align-items:center;
    gap:12px;
    text-decoration:none;
    color:inherit;
    min-width:0;
  }

  .brand-logo{
    width:42px;
    height:42px;
    border-radius:10px;
    display:block;
    object-fit:contain;
    flex:0 0 auto;
    background: rgba(255,255,255,0.04);
    border:1px solid var(--border);
  }

  .brand-text{
    min-width:0;
  }

  .title{ font-weight:800; letter-spacing:.3px; }
  .hint{ color:var(--muted); font-size:12px; }

  .search{
    display:flex;
    align-items:center;
    gap:8px;
    background: rgba(255,255,255,0.05);
    border:1px solid var(--border);
    border-radius:12px;
    padding:8px 10px;
    min-width:260px;
  }

  .search input{
    width:100%;
    background:transparent;
    border:0;
    color:var(--text);
    outline:none;
    font-size:14px;
  }

  .division-filter,
  .sort-control{
    display:flex;
    align-items:center;
    gap:8px;
  }

  .division-filter select,
  .sort-control select{
    background: rgba(255,255,255,0.05);
    color: var(--text);
    border:1px solid var(--border);
    border-radius:12px;
    padding:8px 10px;
    font-size:12px;
    font-weight:700;
    outline:none;
  }

  .division-filter select option,
  .sort-control select option{
    background: var(--card);
    color: var(--text);
  }

  .card{
    background: rgba(18,26,38,0.9);
    border:1px solid var(--border);
    border-radius:18px;
    padding:16px;
    box-shadow: 0 8px 30px rgba(0,0,0,0.35);
    margin:14px 0;
    transition: transform .15s ease, box-shadow .15s ease;
  }

  .card:hover{
    transform: translateY(-2px);
    box-shadow: 0 12px 34px rgba(0,0,0,0.45);
  }

  .pick-val {
    color: var(--muted);
    font-weight: 700;
    font-size: 12px;
    margin-left: 6px;
  }

  .panel-title-inline{
    margin:0;
  }

  .grid-top{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:12px;
    margin-top:10px;
  }

  .moves-panel{
    margin-top:12px;
  }

  .moves-summary{
    display:flex;
    flex-wrap:wrap;
    gap:8px;
    align-items:center;
    color:var(--muted);
    font-size:12px;
    font-weight:700;
    margin-bottom:12px;
  }

  .moves-summary .dot{
    opacity:.6;
  }

  .moves-groups{
    display:grid;
    gap:12px;
  }

  .moves-group{
    background: rgba(255,255,255,0.02);
    border:1px solid var(--border);
    border-radius:12px;
    padding:10px;
  }

  .moves-group .table-wrap {
    margin-top: 4px;
  }

  .moves-group-title{
    font-size:12px;
    font-weight:900;
    color:#cdd6e3;
    text-transform:uppercase;
    letter-spacing:.4px;
    margin-bottom:8px;
  }

  .team-name{
    margin:0;
    font-weight:800;
    letter-spacing:.2px;
    font-size:20px;
    line-height:1.15;
  }

  .panel-title{
    margin:0 0 10px;
    font-size:14px;
    color:#cdd6e3;
    font-weight:800;
  }

  .team-head{
    display:flex;
    align-items:flex-start;
    justify-content:space-between;
    gap:14px;
    width:100%;
  }

  .meta{
    display:flex;
    gap:10px;
    flex-wrap:wrap;
    justify-content:flex-end;
  }

  .meta-item{
    background: rgba(255,255,255,0.04);
    border:1px solid var(--border);
    border-radius:12px;
    padding:8px 10px;
    display:flex;
    gap:8px;
    align-items:baseline;
    white-space:nowrap;
  }

  .meta-item .k{ color:var(--muted); font-size:12px; }
  .meta-item .v{ font-weight:800; font-size:13px; }

  .metrics{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:12px;
    margin:12px 0 6px;
  }

  .metric{
    background: rgba(255,255,255,0.035);
    border:1px solid var(--border);
    border-radius:14px;
    padding:10px 12px;
  }

  .metric-top{
    display:flex;
    justify-content:space-between;
    align-items:center;
    margin-bottom:8px;
  }

  .metric-label{ color:var(--muted); font-size:12px; }
  .metric-val{ font-weight:900; font-size:12px; }

  .bar{
    height:10px;
    background: rgba(255,255,255,0.06);
    border-radius:999px;
    overflow:hidden;
    border:1px solid rgba(255,255,255,0.06);
  }

  .fill{
    height:100%;
    width:0%;
    border-radius:999px;
    background: linear-gradient(90deg, rgba(120,255,163,0.95), rgba(90,162,255,0.95));
  }

  .grid { min-width: 0; }
  .panel { min-width: 0; }
  .panel-body { min-width: 0; }

  .grid{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:12px;
    margin-top:10px;
  }

  .panel{
    background: rgba(255,255,255,0.02);
    border:1px solid var(--border);
    border-radius:14px;
    padding:12px;
  }

  .staff{
    list-style:none;
    padding:0;
    margin:0;
    display:grid;
    gap:8px;
  }

  .staff li{
    display:grid;
    grid-template-columns:90px 1fr;
    gap:10px;
    align-items:baseline;
  }

  .role{ color:var(--muted); font-size:12px; }

  .name{
    font-weight:800;
    font-size:13px;
    text-align:right;
    overflow-wrap:anywhere;
    word-break:break-word;
  }

  .picks{ margin:0; padding-left:18px; color:#dbe4f2; }
  .picks li{ margin:4px 0; font-size:13px; }

  .muted{ color:var(--muted); font-size:13px; }

  .table-wrap{
    position: relative;
    display: block;
    width: 100%;
    max-width: 100%;
    overflow-x: auto;
    overflow-y: hidden;
    -webkit-overflow-scrolling: touch;
    touch-action: pan-x;
  }

  .table{
    border-collapse: collapse;
    width: max-content;
    min-width: 100%;
    white-space: nowrap;
  }

  .table th,
  .table td{
    border-bottom: 1px solid var(--border);
    padding: 8px 10px;
    text-align: left;
    font-size: 12px;
    vertical-align: top;
    white-space: nowrap;
  }

  .table th{
    color:#cdd6e3;
    font-weight:900;
    background: rgba(255,255,255,0.03);
  }

  .badge{
    display:inline-block;
    padding:2px 8px;
    border-radius:999px;
    font-weight:900;
    font-size:11px;
    border:1px solid var(--border);
  }

  .badge.signing{ background: rgba(120,255,163,0.12); }
  .badge.resigning{ background: rgba(90,162,255,0.12); }
  .badge.trade{ background: rgba(255,210,120,0.12); }
  .badge.loss{ background: rgba(255,120,120,0.12); }
  .badge.tag{ background: rgba(200,160,255,0.12); }
  .badge.other{ background: rgba(200,200,200,0.08); }

  .panel-toggle{
    display:inline-flex;
    align-items:center;
    gap:8px;
    cursor:pointer;
    user-select:none;
    margin-bottom:10px;
  }

  .panel-toggle .chev{ transform: rotate(0deg); transition: transform .15s ease; }
  .panel.open .panel-toggle .chev{ transform: rotate(90deg); }

  .panel[data-collapsible="fa"] .panel-body{ display:none; }
  .panel[data-collapsible="fa"].open .panel-body{ display:block; }

  .panel[data-collapsible="moves"] .panel-toggle{ display:none; }
  .panel[data-collapsible="moves"] .panel-body{ display:block; }

  @media (max-width:860px){
    .wrap{ padding:16px 12px 60px; }
    .hint{ display:none; }
    .search{ min-width:0; width:100%; }

    .card{ padding:14px; border-radius:16px; }

    header{
      position:static;
      top:auto;
      backdrop-filter:none;
      background: transparent;
      border-bottom:0;
    }

    .topbar{
      padding:12px 0 14px;
    }

    .team-head{ flex-direction:column; align-items:flex-start; }
    .meta{ justify-content:flex-start; }
    .team-name{ font-size:18px; }

    .metrics{ grid-template-columns:1fr; }
    .grid{ grid-template-columns:1fr; }

    .staff li{ grid-template-columns:80px 1fr; }
    .name{ text-align:left; }

    .division-filter,
    .sort-control{
      width:100%;
    }

    .division-filter select,
    .sort-control select{
      width:100%;
    }

    .panel[data-collapsible="moves"] .panel-toggle{ display:inline-flex; }
    .panel[data-collapsible="moves"] .panel-body{ display:none; }
    .panel[data-collapsible="moves"].open .panel-body{ display:block; }
  }
</style>
</head>
<body>
<header>
  <div class="topbar">
    <a class="brand" href="https://www.firstandthirty.com" target="_blank" rel="noopener noreferrer">
      <img
        class="brand-logo"
        src="https://custom-images.strikinglycdn.com/res/hrscywv4p/image/upload/c_limit,fl_lossy,h_300,w_300,f_auto,q_auto/69222/98371_714484.png"
        alt="First and Thirty logo"
      />
      <div class="brand-text">
        <div class="title">NFL Offseason Dashboard</div>
        <div class="hint">Last update: __LAST_UPDATED__</div>
      </div>
    </a>

    <div class="search">
      <span class="hint">Search</span>
      <input id="q" type="text" placeholder="Search team..." />
    </div>

    <div class="division-filter">
      <label class="hint" for="divisionSelect">Division</label>
      <select id="divisionSelect">
        <option value="all">All divisions</option>
        <option value="afc-east">AFC East</option>
        <option value="afc-north">AFC North</option>
        <option value="afc-south">AFC South</option>
        <option value="afc-west">AFC West</option>
        <option value="nfc-east">NFC East</option>
        <option value="nfc-north">NFC North</option>
        <option value="nfc-south">NFC South</option>
        <option value="nfc-west">NFC West</option>
      </select>
    </div>

    <div class="sort-control">
      <label class="hint" for="sortSelect">Sort</label>
      <select id="sortSelect">
        <option value="alpha">Alphabetical</option>
        <option value="cap">Cap Space</option>
        <option value="draft">Draft Capital</option>
      </select>
    </div>
  </div>
</header>

<div class="wrap" id="wrap">
__TEAM_SECTIONS__
</div>

<script>
  const q = document.getElementById('q');
  const wrap = document.getElementById('wrap');
  const divisionSelect = document.getElementById('divisionSelect');
  const sortSelect = document.getElementById('sortSelect');

  function getCards() {
    return Array.from(document.querySelectorAll('.team'));
  }

  function passesDivisionFilter(card, divisionValue) {
    if (!divisionValue || divisionValue === 'all') return true;
    const cardDivision = card.getAttribute('data-division') || '';
    return cardDivision === divisionValue;
  }

  function applyFilters() {
    const needle = (q?.value || '').trim().toLowerCase();
    const activeDivision = divisionSelect ? divisionSelect.value : 'all';

    for (const card of getCards()) {
      const teamName = (card.getAttribute('data-team') || '').toLowerCase();
      const matchesSearch = !needle || teamName.includes(needle);
      const matchesDivision = passesDivisionFilter(card, activeDivision);

      card.style.display = (matchesSearch && matchesDivision) ? '' : 'none';
    }
  }

  function sortCards() {
    const sortMode = sortSelect ? sortSelect.value : 'alpha';
    const cards = getCards();

    cards.sort((a, b) => {
      const teamA = (a.getAttribute('data-team-display') || a.getAttribute('data-team') || '').toLowerCase();
      const teamB = (b.getAttribute('data-team-display') || b.getAttribute('data-team') || '').toLowerCase();

      if (sortMode === 'cap') {
        const aVal = parseFloat(a.getAttribute('data-cap-value') || 'NaN');
        const bVal = parseFloat(b.getAttribute('data-cap-value') || 'NaN');

        if (Number.isNaN(aVal) && Number.isNaN(bVal)) return teamA.localeCompare(teamB);
        if (Number.isNaN(aVal)) return 1;
        if (Number.isNaN(bVal)) return -1;
        if (bVal !== aVal) return bVal - aVal;
        return teamA.localeCompare(teamB);
      }

      if (sortMode === 'draft') {
        const aVal = parseFloat(a.getAttribute('data-draft-value') || 'NaN');
        const bVal = parseFloat(b.getAttribute('data-draft-value') || 'NaN');

        if (Number.isNaN(aVal) && Number.isNaN(bVal)) return teamA.localeCompare(teamB);
        if (Number.isNaN(aVal)) return 1;
        if (Number.isNaN(bVal)) return -1;
        if (bVal !== aVal) return bVal - aVal;
        return teamA.localeCompare(teamB);
      }

      return teamA.localeCompare(teamB);
    });

    for (const card of cards) {
      wrap.appendChild(card);
    }
  }

  function refreshView() {
    sortCards();
    applyFilters();
  }

  q?.addEventListener('input', applyFilters);
  divisionSelect?.addEventListener('change', applyFilters);
  sortSelect?.addEventListener('change', refreshView);

  refreshView();

  document.querySelectorAll('.panel[data-collapsible] .panel-toggle').forEach(btn => {
    const panel = btn.closest('.panel');
    const toggle = () => panel.classList.toggle('open');

    btn.addEventListener('click', toggle);
    btn.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        toggle();
      }
    });
  });
</script>
</body>
</html>
"""
    return (
        template
        .replace("__TEAM_SECTIONS__", team_sections_html)
        .replace("__LAST_UPDATED__", html_lib.escape(last_updated))
    )


# ---------------- MAIN ---------------- #

def main():
    cap = load_cap_csv("data/cap.csv")
    fa = load_free_agents_csv("data/free_agents.csv")
    draft = load_tankathon_draft()
    coaches = load_coaches_csv("data/coaches.csv")

    cap = {k: v for k, v in cap.items() if k}
    fa = {k: v for k, v in fa.items() if k}
    draft = {k: v for k, v in draft.items() if k}
    moves = load_nfl_offseason_moves()
    if moves is None:
        print("[ERROR] load_nfl_offseason_moves() returned None (indent/return issue).")
        moves = {}
    moves = {k: v for k, v in moves.items() if k}

    # Cap rank + pct
    cap_num = {t: money_to_float(v) for t, v in cap.items()}
    cap_rank = rank_desc(cap_num)
    cap_pct = {t: percentile_from_rank(r, 32) for t, r in cap_rank.items()}

    # Draft points + rank + pct
    chart = load_trade_value_csv("data/trade_value.csv")
    draft_points = {}
    
    for team, picks in draft.items():
        total = 0.0
        
        for p in picks:
            p = str(p).replace("：", ":").replace("⁠", "")
            m = re.search(r"Pick\s+(\d+)", p)
            if not m:
                continue
            pick_num = int(m.group(1))
            total += chart.get(pick_num, 0.0)
       
        draft_points[team] = round(total, 1)

    draft_rank = rank_desc(draft_points)
    draft_pct = {t: percentile_from_rank(r, 32) for t, r in draft_rank.items()}

    teams = sorted(set(cap) | set(fa) | set(draft) | set(coaches) | set(moves))
    teams = [t for t in teams if t and t.lower() != "nan"]

    # Markdown output
    md = ["# NFL Offseason Tracker\n\n"]
    for t in teams:
        md.append(render_team_md(
            team=t,
            cap_display=cap.get(t, "N/A"),
            cap_rank=cap_rank.get(t),
            cap_pct=cap_pct.get(t),
            fa_df=fa.get(t),
            moves_df=moves.get(t),
            coaches=coaches,
            picks=draft.get(t),
            draft_points=draft_points.get(t),
            draft_rank=draft_rank.get(t),
            draft_pct=draft_pct.get(t),
        ))

    # HTML output
    team_html = []
    for t in teams:
        team_html.append(render_team_html(
            team=t,
            cap_display=cap.get(t, "N/A"),
            cap_rank=cap_rank.get(t),
            cap_pct=cap_pct.get(t),
            moves_df=moves.get(t),
            fa_df=fa.get(t),
            coaches=coaches,
            picks=draft.get(t),
            draft_points=draft_points.get(t),
            draft_rank=draft_rank.get(t),
            draft_pct=draft_pct.get(t),
            chart=chart,
        ))

    last_updated = datetime.now().strftime("%b %d, %I:%M %p")
    html_page = build_html_page("\n".join(team_html), last_updated)

    with open("offseason/index.html", "w", encoding="utf-8") as f:
        f.write(html_page)

    print("Wrote offseason/index.html")

if __name__ == "__main__":
    main()
