from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .injury_schema import PROJECT_ROOT


DEFAULT_CURRENT_WEEK_PATH = PROJECT_ROOT / "config" / "current_week.json"


def load_week_config(path: Path | None = None) -> tuple[int, int]:
    config_path = path or DEFAULT_CURRENT_WEEK_PATH
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return int(data["season"]), int(data["week"])


def resolve_season_week(args: Any) -> tuple[int, int]:
    if getattr(args, "config", None):
        return load_week_config(args.config)
    if getattr(args, "season", None) is not None and getattr(args, "week", None) is not None:
        return int(args.season), int(args.week)
    return load_week_config()
