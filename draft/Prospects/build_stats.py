from pathlib import Path
import pandas as pd
import numpy as np
import re

DATA_DIR = Path(r"C:\Users\brady\OneDrive\Desktop\nfl-tools\draft\Prospects")

PROSPECT_FILE = DATA_DIR / "2026_prospects.csv"
RECEIVING_FILES = sorted(DATA_DIR.glob("receiving_summary_*.csv"))

VALID_POSITIONS = {"WR", "TE", "RB"}

def normalize_school(s):
    s = str(s).strip().lower()
    s = re.sub(r"&", "and", s)
    s = re.sub(r"[.\']", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


CONFERENCE_BY_SCHOOL = {
    # ACC
    "boston college": "ACC",
    "cal": "ACC",
    "california": "ACC",
    "clemson": "ACC",
    "duke": "ACC",
    "florida state": "ACC",
    "fsu": "ACC",
    "georgia tech": "ACC",
    "louisville": "ACC",
    "miami": "ACC",
    "miami fl": "ACC",
    "nc state": "ACC",
    "north carolina": "ACC",
    "pittsburgh": "ACC",
    "pitt": "ACC",
    "smu": "ACC",
    "stanford": "ACC",
    "syracuse": "ACC",
    "virginia": "ACC",
    "virginia tech": "ACC",
    "wake forest": "ACC",

    # Big Ten
    "illinois": "BIGTEN",
    "indiana": "BIGTEN",
    "iowa": "BIGTEN",
    "maryland": "BIGTEN",
    "michigan": "BIGTEN",
    "michigan state": "BIGTEN",
    "minnesota": "BIGTEN",
    "nebraska": "BIGTEN",
    "northwestern": "BIGTEN",
    "ohio state": "BIGTEN",
    "oregon": "BIGTEN",
    "penn state": "BIGTEN",
    "purdue": "BIGTEN",
    "rutgers": "BIGTEN",
    "ucla": "BIGTEN",
    "usc": "BIGTEN",
    "washington": "BIGTEN",
    "wisconsin": "BIGTEN",

    # Big 12
    "arizona": "BIG12",
    "arizona state": "BIG12",
    "asu": "BIG12",
    "baylor": "BIG12",
    "byu": "BIG12",
    "cincinnati": "BIG12",
    "colorado": "BIG12",
    "houston": "BIG12",
    "iowa state": "BIG12",
    "kansas": "BIG12",
    "kansas state": "BIG12",
    "oklahoma state": "BIG12",
    "tcu": "BIG12",
    "texas tech": "BIG12",
    "ucf": "BIG12",
    "utah": "BIG12",
    "west virginia": "BIG12",

    # SEC
    "alabama": "SEC",
    "arkansas": "SEC",
    "auburn": "SEC",
    "florida": "SEC",
    "georgia": "SEC",
    "kentucky": "SEC",
    "lsu": "SEC",
    "mississippi state": "SEC",
    "ole miss": "SEC",
    "oklahoma": "SEC",
    "missouri": "SEC",
    "south carolina": "SEC",
    "tennessee": "SEC",
    "texas": "SEC",
    "texas a&m": "SEC",
    "texas am": "SEC",
    "vanderbilt": "SEC",
    "texas a&m": "SEC",
    "texas am": "SEC",
    "texas aandm": "SEC",

    # American
    "army": "AAC",
    "charlotte": "AAC",
    "east carolina": "AAC",
    "ecu": "AAC",
    "fau": "AAC",
    "florida atlantic": "AAC",
    "memphis": "AAC",
    "navy": "AAC",
    "north texas": "AAC",
    "rice": "AAC",
    "south florida": "AAC",
    "usf": "AAC",
    "temple": "AAC",
    "tulane": "AAC",
    "tulsa": "AAC",
    "uab": "AAC",
    "utsa": "AAC",

    # Conference USA
    "delaware": "CUSA",
    "fiu": "CUSA",
    "florida international": "CUSA",
    "jacksonville state": "CUSA",
    "kennesaw state": "CUSA",
    "liberty": "CUSA",
    "louisiana tech": "CUSA",
    "middle tennessee": "CUSA",
    "missouri state": "CUSA",
    "new mexico state": "CUSA",
    "sam houston": "CUSA",
    "utep": "CUSA",
    "western kentucky": "CUSA",
    "wku": "CUSA",

    # MAC
    "akron": "MAC",
    "ball state": "MAC",
    "bowling green": "MAC",
    "buffalo": "MAC",
    "central michigan": "MAC",
    "eastern michigan": "MAC",
    "kent state": "MAC",
    "massachusetts": "MAC",
    "umass": "MAC",
    "miami oh": "MAC",
    "miami (oh)": "MAC",
    "northern illinois": "MAC",
    "ohio": "MAC",
    "toledo": "MAC",
    "western michigan": "MAC",

    # Mountain West
    "air force": "MWC",
    "boise state": "MWC",
    "colorado state": "MWC",
    "fresno state": "MWC",
    "hawaii": "MWC",
    "hawai'i": "MWC",
    "nevada": "MWC",
    "new mexico": "MWC",
    "san diego state": "MWC",
    "san jose state": "MWC",
    "s jose st": "MWC",
    "utah state": "MWC",
    "unlv": "MWC",
    "wyoming": "MWC",

    # Sun Belt
    "app state": "SUN",
    "appalachian state": "SUN",
    "arkansas state": "SUN",
    "coastal carolina": "SUN",
    "georgia southern": "SUN",
    "georgia state": "SUN",
    "james madison": "SUN",
    "louisiana": "SUN",
    "ulm": "SUN",
    "louisiana monroe": "SUN",
    "marshall": "SUN",
    "old dominion": "SUN",
    "south alabama": "SUN",
    "southern miss": "SUN",
    "southern mississippi": "SUN",
    "texas state": "SUN",
    "troy": "SUN",

    # Pac-12 in 2025
    "oregon state": "PAC12",
    "washington state": "PAC12",

    # FBS independents in 2025
    "notre dame": "IND",
    "uconn": "IND",
    "connecticut": "IND",

    # aliases / common variants
    "jmu": "SUN",
    "louisiana state": "SEC",
    "mississippi": "SEC",
    "texas a&m": "SEC",
    "texas am": "SEC",

    # FCS
    "incarnate word": "FCS",
    "montana": "FCS",
    "north dakota state": "FCS",

    # non-fbs / small school
    "john carroll": "OTHER",
}

# crude conference-strength multipliers
CONF_TIER = {
    "SEC": 1.00,
    "BIGTEN": 0.99,
    "ACC": 0.95,
    "BIG12": 0.95,
    "PAC12": 0.90,   # only Oregon State / Washington State in 2025
    "AAC": 0.87,
    "MWC": 0.85,
    "SUN": 0.84,
    "MAC": 0.82,
    "CUSA": 0.80,
    "IND": 0.96,     # ND/UConn is a weird combo; this is mostly a placeholder
    "FCS": 0.74,
    "OTHER": 0.78,
}


def add_conference_context(out):
    out = out.copy()

    out["school_norm"] = out["School"].map(normalize_school)
    out["conference"] = out["school_norm"].map(CONFERENCE_BY_SCHOOL)

    # anything unmatched becomes OTHER for now
    out["conference"] = out["conference"].fillna("OTHER")
    out["conf_tier"] = out["conference"].map(CONF_TIER).fillna(CONF_TIER["OTHER"])

    # adjusted production metrics
    for raw_col, adj_col in [
        ("yprr_2025", "adj_yprr_2025"),
        ("yd_share_2025", "adj_yd_share_2025"),
        ("target_share_2025", "adj_target_share_2025"),
        ("yptt_2025", "adj_yptt_2025"),
        ("career_yprr", "adj_career_yprr"),
        ("peak_yd_share", "adj_peak_yd_share"),
    ]:
        if raw_col in out.columns:
            out[adj_col] = out[raw_col] * out["conf_tier"]

    # quick diagnostic so you can tighten the mapping
    unmatched = (
        out.loc[out["conference"] == "OTHER", "School"]
        .dropna()
        .sort_values()
        .unique()
        .tolist()
    )
    if unmatched:
        print("\n[unmatched schools]")
        for s in unmatched:
            print(" -", s)

    return out


# ---------------- UTIL ---------------- #

def normalize_name(name):
    name = str(name).lower().strip()
    name = re.sub(r"[.\-']", "", name)
    name = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", name)
    name = re.sub(r"\s+", " ", name)
    return name


def safe_div(a, b):
    return np.where((b != 0) & (~pd.isna(b)), a / b, np.nan)

def add_percentiles(df):
    pct_cols = [
        "career_yprr",
        "career_catch_rate",
        "career_drop_rate",
        "career_contested_catch_rate",
        "yprr_2025",
        "yd_share_2025",
        "td_share_2025",
        "target_share_2025",
        "yptt_2025",
        "peak_yd_share",
        "adj_career_yprr",
        "adj_yprr_2025",
        "adj_yd_share_2025",
        "adj_target_share_2025",
        "adj_yptt_2025",
        "adj_peak_yd_share",
    ]

    for col in pct_cols:
        if col in df.columns:
            df[col + "_pct"] = df.groupby("Position")[col].rank(pct=True)

    return df

    for col in pct_cols:
        if col not in df.columns:
            continue

        df[col + "_pct"] = (
            df.groupby("Position")[col]
              .rank(pct=True)
        )

    return df


# ---------------- LOAD ---------------- #

def load_receiving():
    dfs = []

    for f in RECEIVING_FILES:
        year = int(re.search(r"(\d{4})", f.name).group(1))
        df = pd.read_csv(f)
        df["season"] = year
        dfs.append(df)

    df = pd.concat(dfs, ignore_index=True)

    df["player_norm"] = df["player"].map(normalize_name)
    df["team_norm"] = df["team_name"].str.lower().str.strip()
    df["position"] = df["position"].str.upper()

    return df


def load_prospects():
    p = pd.read_csv(PROSPECT_FILE)

    p["player_norm"] = p["Player"].map(normalize_name)
    p["Position"] = p["Position"].str.upper()

    p["Birthdate"] = pd.to_datetime(p["Birthdate"])

    return p[p["Position"].isin(VALID_POSITIONS)].copy()


# ---------------- TEAM TOTALS ---------------- #

def build_team_totals(df):
    return (
        df.groupby(["season", "team_norm"], as_index=False)
        .agg(
            team_yards=("yards", "sum"),
            team_tds=("touchdowns", "sum"),
            team_targets=("targets", "sum"),
            team_routes=("routes", "sum"),
        )
    )


# ---------------- AGE ---------------- #

def add_age(df, prospects):
    df = df.merge(
        prospects[["player_norm", "Birthdate"]],
        on="player_norm",
        how="left"
    )

    # assume season mid-point = Sept 1
    df["season_date"] = pd.to_datetime(df["season"].astype(str) + "-09-01")

    df["age"] = (df["season_date"] - df["Birthdate"]).dt.days / 365.25

    return df


# ---------------- PLAYER-SEASON ---------------- #

def build_player_season(df, team_totals):
    ps = df.merge(team_totals, on=["season", "team_norm"], how="left")

    ps["yd_share"] = safe_div(ps["yards"], ps["team_yards"])
    ps["td_share"] = safe_div(ps["touchdowns"], ps["team_tds"])
    ps["target_share"] = safe_div(ps["targets"], ps["team_targets"])

    ps["yards_per_team_target"] = safe_div(ps["yards"], ps["team_targets"])

    return ps


# ---------------- CAREER ---------------- #

def build_career(ps):
    c = ps.groupby("player_norm").agg(
        career_yards=("yards", "sum"),
        career_targets=("targets", "sum"),
        career_receptions=("receptions", "sum"),
        career_tds=("touchdowns", "sum"),
        career_routes=("routes", "sum"),
        career_drops=("drops", "sum"),
        career_contested_receptions=("contested_receptions", "sum"),
        career_contested_targets=("contested_targets", "sum"),
    ).reset_index()

    # core rates
    c["career_yprr"] = safe_div(c["career_yards"], c["career_routes"])
    c["career_catch_rate"] = safe_div(c["career_receptions"], c["career_targets"])

    # drop rate
    c["career_drop_rate"] = safe_div(c["career_drops"], c["career_targets"])
    c["career_drops_per_100_targets"] = c["career_drop_rate"] * 100

    # ADD THIS RIGHT AFTER drop rate
    c["career_drops_per_100_targets"] = c["career_drop_rate"] * 100

    # contested catch rate
    c["career_contested_catch_rate"] = safe_div(
        c["career_contested_receptions"],
        c["career_contested_targets"]
    )

    return c


# ---------------- FINAL YEAR ---------------- #

def build_2025(ps):
    df = ps[ps["season"] == 2025].copy()

    return df[[
        "player_norm",
        "yprr",
        "yd_share",
        "td_share",
        "target_share",
        "yards_per_team_target",
        "age"
    ]].rename(columns={
        "yprr": "yprr_2025",
        "yd_share": "yd_share_2025",
        "td_share": "td_share_2025",
        "target_share": "target_share_2025",
        "yards_per_team_target": "yptt_2025",
        "age": "age_2025"
    })


# ---------------- PEAK ---------------- #

def build_peak(ps):
    idx = ps.groupby("player_norm")["yd_share"].idxmax()

    peak = ps.loc[idx, [
        "player_norm", "season", "yprr", "yd_share", "age"
    ]].copy()

    peak = peak.rename(columns={
        "season": "best_season",
        "yprr": "best_yprr",
        "yd_share": "best_yd_share",
        "age": "best_age"
    })

    return peak


# ---------------- BREAKOUT AGE/SCORE ---------------- #

def build_breakout(ps):
    breakout = ps[ps["yd_share"] >= 0.20].copy()

    if breakout.empty:
        return pd.DataFrame(columns=["player_norm", "breakout_age"])

    breakout = breakout.sort_values(["player_norm", "age"])

    breakout = breakout.groupby("player_norm").first().reset_index()

    return breakout[["player_norm", "age"]].rename(columns={
        "age": "breakout_age"
    })

def add_breakout_score(df):
    # invert age so younger = higher score
    df["breakout_score"] = (
        df.groupby("Position")["breakout_age_20pct_yd_share"]
          .rank(pct=True, ascending=False)
    )
    return df

# ---------------- COMPOSITE WR SCORE ---------------- #

def add_wr_score(df):
    df["WR_score"] = (
        0.30 * df["adj_yprr_2025_pct"] +
        0.25 * df["adj_yd_share_2025_pct"] +
        0.15 * df["adj_target_share_2025_pct"] +
        0.10 * df["adj_career_yprr_pct"] +
        0.10 * df["adj_peak_yd_share_pct"] +
        0.10 * df["breakout_score"]
    )
    return df

# ---------------- MAIN ---------------- #

def main():
    rec = load_receiving()
    prospects = load_prospects()

    # keep only relevant positions in raw data
    rec = rec[rec["position"].isin({"WR", "TE", "RB"})].copy()

    # build core tables
    team_totals = build_team_totals(rec)
    ps = build_player_season(rec, team_totals)
    ps = add_age(ps, prospects)

    # filter to only prospects we care about
    ps = ps.merge(prospects[["player_norm"]], on="player_norm", how="inner")

    # ---------------- BUILD COMPONENTS ---------------- #
    career = build_career(ps)
    y2025 = build_2025(ps)
    peak = build_peak(ps)
    breakout = build_breakout(ps)

    # ---------------- CLEAN / RENAME ---------------- #

    peak = peak.rename(columns={
        "best_season": "peak_yd_share_season",
        "best_yprr": "peak_yprr",
        "best_yd_share": "peak_yd_share",
        "best_age": "peak_yd_share_age"
    })

    breakout = breakout.rename(columns={
        "breakout_age": "breakout_age_20pct_yd_share"
    })

    # ---------------- MERGE EVERYTHING ---------------- #

    out = (
        prospects
        .merge(career, on="player_norm", how="left")
        .merge(y2025, on="player_norm", how="left")
        .merge(peak, on="player_norm", how="left")
        .merge(breakout, on="player_norm", how="left")
    )

    # IMPORTANT: conference-adjusted fields must exist before percentiles,
    # and percentiles must exist before WR_score
    out = add_conference_context(out)
    out = add_percentiles(out)
    out = add_breakout_score(out)
    out = add_wr_score(out)

    # ---------------- FINAL COLUMN SELECTION ---------------- #

    final_cols = [
        "Position",
        "Player",
        "School",
        "Years",
        "Final Age",

        # career
        "career_yards",
        "career_targets",
        "career_receptions",
        "career_tds",
        "career_routes",
        "career_yprr",
        "career_catch_rate",
        "career_drop_rate",
        "career_drops_per_100_targets",
        "career_contested_catch_rate",

        # 2025
        "yprr_2025",
        "yd_share_2025",
        "td_share_2025",
        "target_share_2025",
        "yptt_2025",
        "age_2025",

        # peak
        "peak_yd_share_season",
        "peak_yd_share",
        "peak_yd_share_age",

        # breakout
        "breakout_age_20pct_yd_share",

        # scores / percentiles
        "yprr_2025_pct",
        "yd_share_2025_pct",
        "target_share_2025_pct",
        "career_yprr_pct",
        "peak_yd_share_pct",
        "breakout_score",
        "WR_score",

        # conference adjustments
        "conference",
        "conf_tier",
        "adj_career_yprr",
        "adj_yprr_2025",
        "adj_yd_share_2025",
        "adj_target_share_2025",
        "adj_yptt_2025",
        "adj_peak_yd_share",
        "adj_yprr_2025_pct",
        "adj_yd_share_2025_pct",
        "adj_target_share_2025_pct",
        "adj_career_yprr_pct",
        "adj_peak_yd_share_pct",
    ]

    out = out[[c for c in final_cols if c in out.columns]]

    # optional: sort nicely
    out = out.sort_values(["Position", "yprr_2025"], ascending=[True, False])

    # ---------------- SAVE ---------------- #

    output_path = DATA_DIR / "receiving_advanced_2026.csv"
    out.to_csv(output_path, index=False)

    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()