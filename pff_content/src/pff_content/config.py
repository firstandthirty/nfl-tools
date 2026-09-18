from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .paths import NFL_TOOLS_ROOT


API_BASE = "https://api.pff.com"
ENV_KEY = "PFF_API_KEY"
ENV_CANDIDATES = (
    NFL_TOOLS_ROOT / "player_props.env",
    NFL_TOOLS_ROOT / "player_props" / ".env",
)


@dataclass(frozen=True)
class PFFConfig:
    api_base: str
    api_key: str


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_pff_api_key() -> str:
    key = os.environ.get(ENV_KEY, "").strip()
    if key:
        return key
    for path in ENV_CANDIDATES:
        load_env_file(path)
        key = os.environ.get(ENV_KEY, "").strip()
        if key:
            return key
    checked = ", ".join(str(path) for path in ENV_CANDIDATES)
    raise RuntimeError(f"{ENV_KEY} is not set; checked process environment and {checked}")


def load_config() -> PFFConfig:
    return PFFConfig(api_base=API_BASE, api_key=get_pff_api_key())
