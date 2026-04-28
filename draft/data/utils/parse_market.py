from pathlib import Path
import pandas as pd
import re


# --------------------------------------------------
# Paths
# --------------------------------------------------
SCRIPT_PATH = Path(__file__).resolve()
DATA_DIR = SCRIPT_PATH.parent.parent          # .../draft/data
RAW_DIR = DATA_DIR / "raw"
CLEAN_DIR = DATA_DIR / "clean"
HISTORICAL_DIR = DATA_DIR / "historical"

RAW_PATH = RAW_DIR / "market_dk_raw.csv"
CLEAN_PATH = CLEAN_DIR / "market_dk_clean.csv"


# --------------------------------------------------
# Helpers
# --------------------------------------------------
def is_odds(val) -> bool:
    val = str(val).strip().replace(",", "")
    return re.fullmatch(r"-?\d+", val) is not None


def extract_pick(val: str):
    match = re.search(r"Number\s+(\d+)\s+Pick", str(val), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def odds_to_prob(odds: int) -> float:
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    return 100 / (odds + 100)


def load_flat_cells(file_path: Path) -> list[str]:
    """
    Read a CSV saved from Excel/Sheets, flatten all non-empty cells into one ordered list.
    This is much more robust than assuming a single raw column.
    """
    df = pd.read_csv(file_path, header=None, dtype=str, keep_default_na=False)

    values: list[str] = []
    for row in df.itertuples(index=False, name=None):
        for cell in row:
            cell = str(cell).strip()
            if cell and cell.lower() != "nan":
                values.append(cell)

    return values


def parse_dk_raw(file_path: Path) -> pd.DataFrame:
    rows = load_flat_cells(file_path)

    print(f"Flattened non-empty cells: {len(rows)}")
    print("First 30 cells:")
    for x in rows[:30]:
        print(f"  {x}")

    data = []
    current_pick = None
    i = 0

    while i < len(rows):
        val = rows[i].strip()

        if not val:
            i += 1
            continue

        # Pick header
        pick_num = extract_pick(val)
        if pick_num is not None:
            current_pick = pick_num
            i += 1
            continue

        # Skip obvious junk
        lower_val = val.lower()
        if (
            lower_val == "2026 nfl draft"
            or "[all bets action]" in lower_val
            or re.search(r"\b(?:mon|tue|wed|thu|fri|sat|sun)\b", lower_val)
            or re.search(r"\b(?:am|pm)\b", lower_val)
            or lower_val == "all bets action"
        ):
            i += 1
            continue

        # Player + odds pairing
        if i + 1 < len(rows):
            next_val = rows[i + 1].strip().replace(",", "")
            if is_odds(next_val):
                if current_pick is None:
                    i += 1
                    continue

                data.append({
                    "pick": current_pick,
                    "player": val,
                    "odds": int(next_val),
                })
                i += 2
                continue

        i += 1

    out = pd.DataFrame(data)

    if out.empty:
        raise ValueError(
            "No market rows were parsed. Check the debug print of the first 30 flattened cells."
        )

    return out


def add_probabilities(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["raw_prob"] = out["odds"].apply(odds_to_prob)
    out["market_prob"] = out.groupby("pick")["raw_prob"].transform(lambda x: x / x.sum())
    return out


def main() -> None:
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    HISTORICAL_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Reading raw market file: {RAW_PATH}")

    if not RAW_PATH.exists():
        raise FileNotFoundError(
            f"Raw market file not found: {RAW_PATH}\n"
            f"Save your DraftKings paste as: {RAW_PATH.name}\n"
            f"in folder: {RAW_DIR}"
        )

    df = parse_dk_raw(RAW_PATH)
    df = add_probabilities(df)

    df["source"] = "DraftKings"
    ts = pd.Timestamp(RAW_PATH.stat().st_mtime, unit="s").strftime("%Y-%m-%d %H:%M:%S")
    df["timestamp"] = ts

    df = df[["pick", "player", "odds", "raw_prob", "market_prob", "source", "timestamp"]]

    print("\nParsed market rows:")
    print(df.head(30).to_string(index=False))

    df.to_csv(CLEAN_PATH, index=False)
    print(f"\nWrote clean market file: {CLEAN_PATH}")

    snapshot_name = f"market_dk_{pd.Timestamp.now().strftime('%Y-%m-%d_%H%M%S')}.csv"
    historical_path = HISTORICAL_DIR / snapshot_name
    df.to_csv(historical_path, index=False)
    print(f"Wrote historical snapshot: {historical_path}")


if __name__ == "__main__":
    main()