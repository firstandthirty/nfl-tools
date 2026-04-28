from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
from typing import Any

import pandas as pd
import requests


SCRIPT_PATH = Path(__file__).resolve()
DATA_DIR = SCRIPT_PATH.parent.parent
CLEAN_DIR = DATA_DIR / "clean"
HISTORICAL_DIR = DATA_DIR / "historical"

CLEAN_PATH = CLEAN_DIR / "nfl_iq_rankings.csv"
CONFIG_URL = "https://iq.nextgenstats.nfl.com/config.json"
NFL_IQ_URL = "https://www.nfl.com/iq"

POSITION_COLUMNS = ["QB", "RB", "WR", "TE", "T", "IOL", "DT", "ED", "LB", "CB", "S"]
POSITION_MAP = {
    "T": "OT",
    "ED": "EDGE",
}

RD_PICK_ESTIMATES = {
    "Top 5": 3,
    "Top 10": 8,
    "Top 15": 13,
    "1st": 24,
    "1st-2nd": 38,
    "2nd": 50,
    "2nd-3rd": 68,
    "3rd": 84,
    "3rd-4th": 100,
    "4th": 120,
    "4th-5th": 140,
    "5th": 155,
    "5th-6th": 175,
    "6th": 190,
    "6th-7th": 210,
    "7th": 235,
}

JUNK_TEXT = {
    "",
    "RD",
    *POSITION_COLUMNS,
    "Powered by Amazon Quick",
    "Swap",
}


def normalize_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text.replace("\u00a0", " ")


def normalize_position(position: str) -> str:
    position = normalize_text(position).upper()
    return POSITION_MAP.get(position, position)


def load_config() -> dict:
    response = requests.get(CONFIG_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    response.raise_for_status()
    return response.json()


def find_navigation_item(config: dict, item_id: str) -> dict:
    for section in config.get("navigation", {}).values():
        for item in section.get("subItems", []):
            if item.get("id") == item_id:
                return item
    raise ValueError(f"Could not find NFL IQ navigation item: {item_id}")


def get_embed_url(config: dict, item_id: str, *, session_id: str = "nfl-iq-scraper") -> str:
    item = find_navigation_item(config, item_id)
    available_dashboards = sorted({
        sub_item["dashboardId"]
        for section in config.get("navigation", {}).values()
        for sub_item in section.get("subItems", [])
        if sub_item.get("dashboardId")
    })
    body = {
        "dashboardId": item["dashboardId"],
        "sheetId": item["sheetId"],
        "module": item_id,
        "deviceType": "desktop",
        "sessionId": session_id,
        "sessionLifetimeInMinutes": config.get("session", {}).get("expirationMinutes", 60),
        "availableDashboards": available_dashboards,
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json",
        "Origin": "https://www.nfl.com",
        "Referer": NFL_IQ_URL,
    }
    endpoint = config["apiEndpoint"].rstrip("/") + "/dashboard-embed"
    response = requests.post(endpoint, headers=headers, data=json.dumps(body), timeout=30)
    response.raise_for_status()
    payload = response.json()
    if "embedUrl" not in payload:
        raise ValueError(f"NFL IQ embed response did not include embedUrl: {payload}")
    embed_url = payload["embedUrl"]
    dashboard_path = f"/dashboards/{item['dashboardId']}"
    sheet_path = f"{dashboard_path}/sheets/{item['sheetId']}"
    if dashboard_path in embed_url and sheet_path not in embed_url:
        embed_url = embed_url.replace(dashboard_path, sheet_path, 1)
    return embed_url


def estimate_pick(rd: str, row_index: int) -> float:
    base = RD_PICK_ESTIMATES.get(rd, 260)
    return float(base) + row_index * 0.75


def playwright_missing_message() -> str:
    return (
        "Playwright is required for NFL IQ because the table is rendered inside an "
        "Amazon QuickSight iframe. Install it with:\n"
        "  offseason_env\\Scripts\\python.exe -m pip install playwright\n"
        "  offseason_env\\Scripts\\python.exe -m playwright install chromium"
    )


def import_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(playwright_missing_message()) from exc

    return sync_playwright


def text_nodes_script() -> str:
    return r"""
() => {
  const walker = document.createTreeWalker(
    document.body,
    NodeFilter.SHOW_TEXT,
    {
      acceptNode(node) {
        const text = (node.nodeValue || '').replace(/\s+/g, ' ').trim();
        if (!text) return NodeFilter.FILTER_REJECT;
        const parent = node.parentElement;
        if (!parent) return NodeFilter.FILTER_REJECT;
        const style = window.getComputedStyle(parent);
        if (style.visibility === 'hidden' || style.display === 'none') return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    }
  );

  const nodes = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const range = document.createRange();
    range.selectNodeContents(node);
    const rect = range.getBoundingClientRect();
    const text = (node.nodeValue || '').replace(/\s+/g, ' ').trim();
    if (rect.width <= 0 || rect.height <= 0) continue;
    nodes.push({
      text,
      x: rect.x,
      y: rect.y,
      width: rect.width,
      height: rect.height,
      centerX: rect.x + rect.width / 2,
      centerY: rect.y + rect.height / 2
    });
  }
  return nodes;
}
"""


def collect_rendered_text_nodes(
    url: str,
    *,
    headed: bool,
    timeout_ms: int,
    click_board: bool = False,
) -> list[dict]:
    sync_playwright = import_playwright()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

        # The QuickSight iframe often finishes after the NFL shell is loaded.
        page.wait_for_timeout(5000)
        if click_board:
            for frame in page.frames:
                try:
                    frame.get_by_text("VIEW THE BOARD").click(timeout=5000)
                    page.wait_for_timeout(6000)
                    break
                except Exception:
                    continue
        try:
            page.get_by_text("RD", exact=True).wait_for(timeout=timeout_ms // 2)
        except Exception:
            pass
        page.wait_for_timeout(2500)

        all_nodes: list[dict] = []
        for frame in page.frames:
            try:
                nodes = frame.evaluate(text_nodes_script())
            except Exception:
                continue
            for node in nodes:
                node["frame_url"] = frame.url
            all_nodes.extend(nodes)

        browser.close()

    return all_nodes


def row_key(y: float) -> int:
    return int(round(y / 6.0) * 6)


def find_header(nodes: list[dict]) -> tuple[float, dict[str, float]]:
    rows: dict[int, list[dict]] = {}
    for node in nodes:
        text = normalize_text(node["text"])
        if text == "RD" or text in POSITION_COLUMNS:
            rows.setdefault(row_key(float(node["centerY"])), []).append(node)

    best_row = None
    best_count = 0
    for y_key, row_nodes in rows.items():
        texts = {normalize_text(node["text"]) for node in row_nodes}
        count = len(texts & {"RD", *POSITION_COLUMNS})
        if "RD" in texts and count > best_count:
            best_row = row_nodes
            best_count = count

    if best_row is None or best_count < 6:
        raise ValueError("Could not find the NFL IQ table header in rendered text.")

    header_y = sum(float(node["centerY"]) for node in best_row) / len(best_row)
    columns = {}
    for label in ["RD", *POSITION_COLUMNS]:
        matches = [node for node in best_row if normalize_text(node["text"]) == label]
        if matches:
            columns[label] = sum(float(node["centerX"]) for node in matches) / len(matches)

    return header_y, columns


def nearest_column(x: float, columns: dict[str, float]) -> str | None:
    position_columns = {key: value for key, value in columns.items() if key != "RD"}
    if not position_columns:
        return None
    label, distance = min(
        ((label, abs(x - center_x)) for label, center_x in position_columns.items()),
        key=lambda item: item[1],
    )
    sorted_centers = sorted(position_columns.values())
    if len(sorted_centers) > 1:
        median_gap = sorted(
            b - a for a, b in zip(sorted_centers, sorted_centers[1:])
        )[len(sorted_centers) // 2]
    else:
        median_gap = 110
    return label if distance <= max(45, median_gap * 0.45) else None


def is_player_text(text: str) -> bool:
    if text in JUNK_TEXT or text in RD_PICK_ESTIMATES:
        return False
    if len(text) < 3 or len(text) > 40:
        return False
    if re.fullmatch(r"[\u25c6\u25c7\u25a0\u25cf]+", text):
        return False
    if re.search(r"\d", text):
        return False
    if text.lower() in {"sign in", "watch", "games", "news", "teams", "stats"}:
        return False
    return bool(re.search(r"[A-Za-z]", text))


def parse_table_nodes(nodes: list[dict], source_url: str) -> pd.DataFrame:
    header_y, columns = find_header(nodes)
    rd_x = columns.get("RD")
    if rd_x is None:
        raise ValueError("Could not locate the RD column in the NFL IQ table.")

    rd_nodes = []
    for node in nodes:
        text = normalize_text(node["text"])
        if text not in RD_PICK_ESTIMATES:
            continue
        if float(node["centerY"]) <= header_y:
            continue
        if abs(float(node["centerX"]) - rd_x) > 60:
            continue
        rd_nodes.append(node)

    rd_nodes = sorted(rd_nodes, key=lambda node: float(node["centerY"]))
    if not rd_nodes:
        raise ValueError("Could not find NFL IQ round/tier rows.")

    row_centers = [float(node["centerY"]) for node in rd_nodes]
    row_bounds = []
    for index, center in enumerate(row_centers):
        top = header_y if index == 0 else (row_centers[index - 1] + center) / 2.0
        bottom = math.inf if index == len(row_centers) - 1 else (center + row_centers[index + 1]) / 2.0
        row_bounds.append((top, bottom))

    rows = []
    seen = set()
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for row_index, (rd_node, (top, bottom)) in enumerate(zip(rd_nodes, row_bounds), start=1):
        rd = normalize_text(rd_node["text"])
        row_players = []
        for node in nodes:
            text = normalize_text(node["text"])
            center_y = float(node["centerY"])
            if not (top < center_y <= bottom):
                continue
            if not is_player_text(text):
                continue
            position = nearest_column(float(node["centerX"]), columns)
            if position is None:
                continue

            key = (row_index, position, text)
            if key in seen:
                continue
            seen.add(key)
            row_players.append((position, text))

        for position, player in sorted(row_players, key=lambda item: (POSITION_COLUMNS.index(item[0]), item[1])):
            rows.append({
                "nfl_iq_rank": len(rows) + 1,
                "row_index": row_index,
                "rd": rd,
                "position": normalize_position(position),
                "raw_position": position,
                "player": player,
                "estimated_pick": estimate_pick(rd, row_index),
                "source": "NFL IQ",
                "source_url": source_url,
                "scraped_at": scraped_at,
            })

    if not rows:
        raise ValueError("Found the NFL IQ table structure, but no player cells were parsed.")

    return pd.DataFrame(rows)


def write_outputs(df: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HISTORICAL_DIR.mkdir(parents=True, exist_ok=True)

    df.to_csv(output_path, index=False)
    snapshot_path = HISTORICAL_DIR / f"nfl_iq_rankings_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.csv"
    df.to_csv(snapshot_path, index=False)

    print(f"Wrote {len(df)} NFL IQ rows to {output_path}")
    print(f"Wrote historical snapshot to {snapshot_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape the rendered NFL IQ prospect table.")
    parser.add_argument("--url", default=NFL_IQ_URL)
    parser.add_argument("--output", type=Path, default=CLEAN_PATH)
    parser.add_argument("--headed", action="store_true", help="Show Chromium while scraping.")
    parser.add_argument("--timeout-ms", type=int, default=60000)
    parser.add_argument("--item-id", default="nd-bigboard", help="NFL IQ navigation sub-item to scrape.")
    parser.add_argument("--config-only", action="store_true", help="Print NFL IQ config metadata and exit.")
    args = parser.parse_args()

    config = load_config()
    sheet = config["sheets"][0]
    print("NFL IQ config:")
    print(f"  apiEndpoint: {config['apiEndpoint']}")
    print(f"  dashboardId: {sheet['dashboardId']}")
    print(f"  sheetId: {sheet['sheetId']}")
    print(f"  teams: {len(config.get('teams', []))}")

    if args.config_only:
        return

    embed_url = get_embed_url(config, args.item_id)
    nodes = collect_rendered_text_nodes(
        embed_url,
        headed=args.headed,
        timeout_ms=args.timeout_ms,
        click_board=False,
    )
    df = parse_table_nodes(nodes, args.url)
    write_outputs(df, args.output)


if __name__ == "__main__":
    main()
