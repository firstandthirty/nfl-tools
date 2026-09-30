from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .injury_schema import PROJECT_ROOT
from .week_config import resolve_season_week


REPO_ROOT = PROJECT_ROOT.parent
EXPECTED_BRANCH = "main"
EXPECTED_REMOTE_SLUG = "firstandthirty/nfl-tools"

MANUAL_STATE_FILES = [
    "injury_tracker/data/manual/manual_players.csv",
    "injury_tracker/data/manual/overrides.csv",
    "injury_tracker/data/manual/pff_player_mappings.csv",
    "injury_tracker/data/manual/review_decisions.csv",
    "injury_tracker/data/manual/review_status.csv",
]


class PublishError(RuntimeError):
    pass


def normalize_git_path(path: str | Path) -> str:
    return str(path).replace("\\", "/").strip("/")


def weekly_publish_allowlist(season: int, week: int) -> list[str]:
    return [
        "injuries/index.html",
        f"injuries/{season}/week_{week:02d}/index.html",
        "injury_tracker/config/current_week.json",
        *MANUAL_STATE_FILES,
    ]


def unexpected_staged_paths(paths: list[str], *, season: int, week: int) -> list[str]:
    allowed = set(weekly_publish_allowlist(season, week))
    return [path for path in paths if normalize_git_path(path) not in allowed]


def commit_message(season: int, week: int) -> str:
    return f"Update Week {week} injury tracker"


def classify_divergence(head: str, remote: str, merge_base: str) -> str:
    if head == remote:
        return "synced"
    if merge_base == head:
        return "remote_ahead"
    if merge_base == remote:
        return "local_ahead"
    return "diverged"


def remote_matches_expected(url: str) -> bool:
    clean = url.strip().removesuffix(".git")
    return clean.endswith(EXPECTED_REMOTE_SLUG)


def run_git(args: list[str], *, repo_root: Path = REPO_ROOT, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["git", *args], cwd=repo_root, text=True, capture_output=True)
    if check and result.returncode:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or f"git {' '.join(args)} failed"
        raise PublishError(detail)
    return result


def git_lines(args: list[str], *, repo_root: Path = REPO_ROOT) -> list[str]:
    result = run_git(args, repo_root=repo_root)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def verify_repo(repo_root: Path = REPO_ROOT) -> None:
    actual_root = Path(run_git(["rev-parse", "--show-toplevel"], repo_root=repo_root).stdout.strip()).resolve()
    if actual_root != repo_root.resolve():
        raise PublishError(f"Expected repository root {repo_root}, got {actual_root}.")

    branch = run_git(["branch", "--show-current"], repo_root=repo_root).stdout.strip()
    if branch != EXPECTED_BRANCH:
        raise PublishError(f"Refusing to publish from branch {branch!r}; expected {EXPECTED_BRANCH!r}.")

    remote = run_git(["remote", "get-url", "origin"], repo_root=repo_root).stdout.strip()
    if not remote_matches_expected(remote):
        raise PublishError(f"Refusing to publish to unexpected origin remote: {remote}")


def ensure_no_preexisting_staged_changes(repo_root: Path = REPO_ROOT) -> None:
    staged = git_lines(["diff", "--cached", "--name-only"], repo_root=repo_root)
    if staged:
        joined = "\n".join(f"  {path}" for path in staged)
        raise PublishError(f"Refusing to publish with pre-existing staged changes:\n{joined}")


def fetch_origin(repo_root: Path = REPO_ROOT) -> None:
    run_git(["fetch", "origin"], repo_root=repo_root)


def current_sync_state(repo_root: Path = REPO_ROOT) -> tuple[str, str, str]:
    head = run_git(["rev-parse", "HEAD"], repo_root=repo_root).stdout.strip()
    remote = run_git(["rev-parse", "origin/main"], repo_root=repo_root).stdout.strip()
    merge_base = run_git(["merge-base", "HEAD", "origin/main"], repo_root=repo_root).stdout.strip()
    return classify_divergence(head, remote, merge_base), head, remote


def ensure_synced_before_start(repo_root: Path = REPO_ROOT) -> str:
    state, head, remote = current_sync_state(repo_root)
    if state != "synced":
        raise PublishError(f"Refusing to publish because local main is {state} relative to origin/main.")
    if head != remote:
        raise PublishError("Refusing to publish because HEAD and origin/main do not match.")
    return head


def stage_allowlisted_outputs(season: int, week: int, *, repo_root: Path = REPO_ROOT) -> list[str]:
    paths = weekly_publish_allowlist(season, week)
    run_git(["add", "--", *paths], repo_root=repo_root)
    staged = git_lines(["diff", "--cached", "--name-only"], repo_root=repo_root)
    unexpected = unexpected_staged_paths(staged, season=season, week=week)
    if unexpected:
        joined = "\n".join(f"  {path}" for path in unexpected)
        raise PublishError(f"Refusing to commit unexpected staged paths:\n{joined}")
    return staged


def publish(season: int, week: int, *, repo_root: Path = REPO_ROOT) -> int:
    verify_repo(repo_root)
    ensure_no_preexisting_staged_changes(repo_root)
    fetch_origin(repo_root)
    base_head = ensure_synced_before_start(repo_root)

    staged = stage_allowlisted_outputs(season, week, repo_root=repo_root)
    if not staged:
        print("No injury tracker publication changes to commit.")
        return 0

    print("Will commit these files:")
    for path in staged:
        print(f"  {path}")

    message = commit_message(season, week)
    run_git(["commit", "-m", message], repo_root=repo_root)

    fetch_origin(repo_root)
    remote_after = run_git(["rev-parse", "origin/main"], repo_root=repo_root).stdout.strip()
    if remote_after != base_head:
        raise PublishError("Remote changed after commit; local commit was created but was not pushed.")

    run_git(["push", "origin", "main"], repo_root=repo_root)
    print("Pushed injury tracker update to origin/main.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely commit and push weekly injury tracker Pages output.")
    parser.add_argument("--season", type=int)
    parser.add_argument("--week", type=int)
    parser.add_argument("--config", type=Path, help="JSON file with season/week. Defaults to injury_tracker/config/current_week.json.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    season, week = resolve_season_week(args)
    try:
        raise SystemExit(publish(season, week))
    except PublishError as exc:
        print(f"Publish failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
