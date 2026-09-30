from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .build_public_site import build_public_site, default_output_root
from .injury_schema import PROJECT_ROOT
from .review import load_review_bundle
from .week_config import resolve_season_week


REPO_ROOT = PROJECT_ROOT.parent


def pages_output_root() -> Path:
    return REPO_ROOT / "injuries"


def prepare_publish(season: int, week: int, *, pages_root: Path | None = None) -> dict[str, Any]:
    review = load_review_bundle(season, week)
    stale_games = int(review["summary"].get("games_stale") or 0)
    if stale_games:
        raise SystemExit(f"Refusing to prepare publish: {stale_games} reviewed game(s) need re-review.")

    build_summary = build_public_site(season, week, print_summary=False)
    local_root = default_output_root()
    target_root = pages_root or pages_output_root()
    changed = copy_public_outputs(local_root, target_root, season, week)

    summary = {
        "season": season,
        "week": week,
        "local_build": build_summary,
        "pages_root": str(target_root),
        "changed_files": changed,
        "deployed_public_json": False,
        "expected_urls": expected_urls(season, week),
        "next_git_commands": recommended_git_commands(changed, season=season, week=week),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def copy_public_outputs(local_root: Path, target_root: Path, season: int, week: int) -> list[str]:
    target_archive = target_root / str(season) / f"week_{week:02d}"
    target_root.mkdir(parents=True, exist_ok=True)
    target_archive.mkdir(parents=True, exist_ok=True)
    copies = [
        (local_root / "index.html", target_root / "index.html"),
        (local_root / str(season) / f"week_{week:02d}" / "index.html", target_archive / "index.html"),
    ]
    changed = []
    for src, dst in copies:
        if not src.exists():
            raise FileNotFoundError(src)
        was_changed = not dst.exists() or not filecmp.cmp(src, dst, shallow=False)
        shutil.copyfile(src, dst)
        if was_changed:
            try:
                changed.append(str(dst.relative_to(REPO_ROOT)))
            except ValueError:
                changed.append(str(dst))
    return changed


def expected_urls(season: int, week: int) -> dict[str, str | None]:
    owner_repo = github_owner_repo()
    if not owner_repo:
        return {"base": None, "stable_injuries": None, "archive": None}
    owner, repo = owner_repo
    base = f"https://{owner}.github.io/{repo}/"
    return {
        "base": base,
        "stable_injuries": f"{base}injuries/",
        "archive": f"{base}injuries/{season}/week_{week:02d}/",
    }


def github_owner_repo() -> tuple[str, str] | None:
    try:
        result = subprocess.run(["git", "remote", "get-url", "origin"], cwd=REPO_ROOT, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError:
        return None
    url = result.stdout.strip()
    if url.startswith("https://github.com/"):
        slug = url.removeprefix("https://github.com/").removesuffix(".git")
    elif url.startswith("git@github.com:"):
        slug = url.removeprefix("git@github.com:").removesuffix(".git")
    else:
        return None
    parts = slug.split("/")
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def recommended_git_commands(changed: list[str], *, season: int, week: int) -> list[str]:
    files = [
        "index.html",
        "injuries/index.html",
        f"injuries/{season}/week_{week:02d}/index.html",
        "injury_tracker/.gitignore",
        "injury_tracker/README.md",
        "injury_tracker/__init__.py",
        "injury_tracker/00_SET_CURRENT_WEEK.bat",
        "injury_tracker/01_UPDATE_WEEK.bat",
        "injury_tracker/02_REVIEW_WEEK.bat",
        "injury_tracker/03_BUILD_PUBLIC_SITE.bat",
        "injury_tracker/04_PREPARE_PUBLISH.bat",
        "injury_tracker/config",
        "injury_tracker/scripts",
        "injury_tracker/tests",
    ]
    for path in changed:
        normalized = path.replace("\\", "/")
        if normalized not in files:
            files.append(normalized)
    quoted = " ".join(f'"{path}"' for path in files)
    return [
        "git status --short",
        f"git add {quoted}",
        'git commit -m "Add First & Thirty injury tracker public workflow"',
        "git push origin main",
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare reviewed injury tracker HTML for the repository Pages subtree.")
    parser.add_argument("--season", type=int)
    parser.add_argument("--week", type=int)
    parser.add_argument("--config", type=Path, help="JSON file with season/week. Defaults to injury_tracker/config/current_week.json.")
    parser.add_argument("--pages-root", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    season, week = resolve_season_week(args)
    prepare_publish(season, week, pages_root=args.pages_root)


if __name__ == "__main__":
    main()
