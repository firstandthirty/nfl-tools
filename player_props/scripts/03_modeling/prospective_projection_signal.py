from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SUPPORTED_MARKETS = [
    "player_pass_yds",
    "player_rush_yds",
    "player_reception_yds",
    "player_receptions",
]

DEFAULT_POLICY = {
    "season": 2026,
    "required_source_count": 5,
    "minimum_agreement_count": 4,
    "active_sources": ["pff", "fantasypros"],
    "market_policy": {market: {"green_light_enabled": True} for market in SUPPORTED_MARKETS},
    "sportsbook_policy": {
        "actionable_sportsbooks": [
            "draftkings",
            "fanduel",
            "betmgm",
            "williamhill_us",
            "fanatics",
            "espnbet",
        ],
        "sportsbook_display_names": {
            "draftkings": "DraftKings",
            "fanduel": "FanDuel",
            "betmgm": "BetMGM",
            "williamhill_us": "Caesars",
            "fanatics": "Fanatics",
            "espnbet": "theScore",
        },
    },
    "staleness_policy": {
        "enabled": True,
        "maximum_projection_age_hours": 72,
        "stale_sources_invalidate_green_light": True,
    },
    "public_candidate_policy": {
        "allow_alternate_public_candidates": True,
        "price_policy_enabled": True,
        "min_american_odds": -150,
        "max_american_odds": 200,
    },
    "edge_policy": {
        "minimum_consensus_edge_abs": None,
        "minimum_consensus_edge_pct": None,
    },
    "dispersion_policy": {
        "maximum_projection_stddev": None,
        "maximum_projection_range": None,
    },
}


RESEARCH_COLUMNS = [
    "signal_id",
    "season",
    "week",
    "as_of",
    "event_id",
    "commence_time",
    "home_team",
    "away_team",
    "player",
    "player_normalized",
    "team",
    "opponent",
    "market",
    "sportsbook",
    "line",
    "side",
    "price",
    "is_alternate",
    "market_source_key",
    "captured_at",
    "sportsbook_display_name",
    "configured_source_count",
    "required_source_count",
    "source_count_available",
    "over_votes",
    "under_votes",
    "neutral_votes",
    "agreement_side",
    "agreement_count",
    "agreement_fraction",
    "mean_projection",
    "median_projection",
    "consensus_projection",
    "min_projection",
    "max_projection",
    "projection_range",
    "projection_stddev",
    "consensus_edge",
    "consensus_edge_abs",
    "consensus_edge_pct",
    "all_required_sources_available",
    "missing_sources",
    "stale_source_count",
    "stale_sources",
    "maximum_projection_age_hours_policy",
    "max_projection_age_hours_actual",
    "contradictory_projection_signal",
    "market_green_light_enabled",
    "actionable_ma_book",
    "minimum_agreement_count",
    "agreement_rule_pass",
    "consensus_side_rule_pass",
    "source_count_rule_pass",
    "staleness_rule_pass",
    "market_rule_pass",
    "price_rule_pass",
    "public_candidate_price_rule_pass",
    "public_min_american_odds",
    "public_max_american_odds",
    "alternate_publication_rule_pass",
    "allow_alternate_public_candidates",
    "dispersion_rule_pass",
    "edge_rule_pass",
    "public_candidate_eligible",
    "green_light_reason_codes",
    "green_light",
    "green_light_reason",
    "research_tier",
    "participating_sources",
    "source_projection_values",
    "source_votes",
    "source_captured_at",
    "source_projection_age_hours",
    "source_raw_files",
]

CANDIDATE_COLUMNS = [
    "candidate_id",
    "signal_id",
    "player",
    "player_normalized",
    "market",
    "side",
    "line",
    "best_price",
    "best_sportsbook",
    "is_alternate",
    "agreement_display",
    "consensus_projection",
    "consensus_edge",
    "projection_range",
    "source_count",
    "green_light",
    "green_light_reason",
    "as_of",
    "source_details",
]

SOURCE_DETAIL_COLUMNS = [
    "signal_id",
    "source",
    "projection",
    "vote",
    "captured_at",
    "raw_file",
    "projection_age_hours",
    "stale_source",
]


@dataclass(frozen=True)
class SignalPolicy:
    season: int
    required_source_count: int
    minimum_agreement_count: int
    active_sources: tuple[str, ...]
    market_policy: dict[str, dict[str, Any]]
    sportsbook_policy: dict[str, Any]
    staleness_policy: dict[str, Any]
    public_candidate_policy: dict[str, Any]
    edge_policy: dict[str, Any]
    dispersion_policy: dict[str, Any]


def load_policy(path: Path | str | None = None) -> SignalPolicy:
    payload = json.loads(Path(path).read_text(encoding="utf-8")) if path is not None else DEFAULT_POLICY
    merged = json.loads(json.dumps(DEFAULT_POLICY))
    _deep_update(merged, payload)
    active_sources = tuple(_dedupe([str(source).strip() for source in merged.get("active_sources", []) if str(source).strip()]))
    if not active_sources:
        raise ValueError("projection signal policy requires at least one active source")
    return SignalPolicy(
        season=int(merged["season"]),
        required_source_count=int(merged["required_source_count"]),
        minimum_agreement_count=int(merged["minimum_agreement_count"]),
        active_sources=active_sources,
        market_policy=dict(merged.get("market_policy", {})),
        sportsbook_policy=dict(merged.get("sportsbook_policy", {})),
        staleness_policy=dict(merged.get("staleness_policy", {})),
        public_candidate_policy=dict(merged.get("public_candidate_policy", {})),
        edge_policy=dict(merged.get("edge_policy", {})),
        dispersion_policy=dict(merged.get("dispersion_policy", {})),
    )


def _deep_update(base: dict[str, Any], override: dict[str, Any]) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _clean_source_list(values: Any) -> list[str]:
    if isinstance(values, str):
        return [part for part in values.split("|") if part]
    return [str(value) for value in values if str(value).strip()]


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _safe_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _make_id(parts: list[Any]) -> str:
    text = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def american_price_sort_value(price: Any) -> float:
    value = _safe_float(price)
    return value if value is not None else float("-inf")


def source_vote(projection: float, line: float) -> str:
    if projection > line:
        return "over"
    if projection < line:
        return "under"
    return "neutral"


def agreement_tier(source_count: int, required_count: int, agreement_count: int, over_votes: int, under_votes: int) -> str:
    if source_count < required_count:
        return "insufficient_sources"
    if over_votes == under_votes:
        return "split"
    if agreement_count == source_count:
        return "unanimous"
    if agreement_count > source_count / 2:
        return "strong_majority" if agreement_count >= max(required_count - 1, 1) else "simple_majority"
    return "neutral/tied"


def normalize_policy_dict(policy: SignalPolicy) -> dict[str, Any]:
    return {
        "season": policy.season,
        "required_source_count": policy.required_source_count,
        "minimum_agreement_count": policy.minimum_agreement_count,
        "active_sources": list(policy.active_sources),
        "market_policy": policy.market_policy,
        "sportsbook_policy": policy.sportsbook_policy,
        "staleness_policy": policy.staleness_policy,
        "public_candidate_policy": policy.public_candidate_policy,
        "edge_policy": policy.edge_policy,
        "dispersion_policy": policy.dispersion_policy,
    }


def sportsbook_display_mapping(policy: SignalPolicy) -> dict[str, str]:
    display = dict(policy.sportsbook_policy.get("sportsbook_display_names", {}))
    for key in _clean_source_list(policy.sportsbook_policy.get("actionable_sportsbooks", [])):
        display.setdefault(key, key)
    return display


def public_price_rule_pass(price: Any, policy: SignalPolicy) -> bool:
    candidate_policy = policy.public_candidate_policy
    if not bool(candidate_policy.get("price_policy_enabled", True)):
        return True
    value = _safe_float(price)
    if value is None:
        return False
    min_odds = _safe_float(candidate_policy.get("min_american_odds"))
    max_odds = _safe_float(candidate_policy.get("max_american_odds"))
    if min_odds is not None and value < min_odds:
        return False
    if max_odds is not None and value > max_odds:
        return False
    return True


def summarize_source_state(
    *,
    registry: pd.DataFrame,
    selected_snapshots: pd.DataFrame,
    policy: SignalPolicy,
    season: int,
    week: int,
) -> dict[str, Any]:
    configured = list(policy.active_sources)
    selected = selected_snapshots.loc[selected_snapshots["selection_status"].astype(str) == "selected"].copy() if not selected_snapshots.empty else pd.DataFrame()
    available = sorted(selected["source"].dropna().astype(str).unique().tolist()) if not selected.empty else []
    if registry.empty:
        registry_sources: list[str] = []
    else:
        filtered = registry.loc[(registry["season"].astype(int) == int(season)) & (registry["week"].astype(int) == int(week))]
        registry_sources = sorted(filtered["source"].dropna().astype(str).unique().tolist())
    missing = [source for source in configured if source not in available]
    unexpected = [source for source in registry_sources if source not in configured]
    snapshots = []
    if not selected_snapshots.empty:
        for _, row in selected_snapshots.iterrows():
            snapshots.append({
                "source": row.get("source", ""),
                "selection_status": row.get("selection_status", ""),
                "captured_at": row.get("selected_captured_at", ""),
                "raw_file": row.get("selected_raw_file", ""),
                "processed_file": row.get("selected_processed_file", ""),
                "snapshot_age_hours": row.get("snapshot_age_hours", None),
            })
    return {
        "configured_source_count": len(configured),
        "required_source_count": policy.required_source_count,
        "available_source_count": len(available),
        "configured_sources": configured,
        "available_sources": available,
        "missing_configured_sources": missing,
        "unexpected_available_sources": unexpected,
        "selected_snapshots": snapshots,
    }


def build_projection_signal_rows(
    *,
    projections: pd.DataFrame,
    selected_snapshots: pd.DataFrame,
    odds: pd.DataFrame,
    policy: SignalPolicy,
    season: int,
    week: int,
    as_of: str,
) -> dict[str, pd.DataFrame]:
    configured_sources = list(policy.active_sources)
    markets = [market for market in SUPPORTED_MARKETS if market in policy.market_policy]
    ma_books = set(_clean_source_list(policy.sportsbook_policy.get("actionable_sportsbooks", [])))

    projections = projections.copy()
    odds = odds.copy()
    if not projections.empty:
        projections = projections.loc[projections["source"].astype(str).isin(configured_sources)]
        projections = projections.loc[projections["market"].astype(str).isin(markets)]
        projections["projection"] = pd.to_numeric(projections["projection"], errors="coerce")
        projections = projections.dropna(subset=["projection", "player_normalized", "market", "source"])
        projections = projections.sort_values(["source", "player_normalized", "market", "captured_at", "raw_file"], kind="mergesort")
        projections = projections.drop_duplicates(subset=["source", "player_normalized", "market"], keep="first")
    if not odds.empty:
        odds = odds.loc[odds["market"].astype(str).isin(markets)].copy()
        odds["line"] = pd.to_numeric(odds["line"], errors="coerce")
        odds["price"] = pd.to_numeric(odds["price"], errors="coerce")
        odds = odds.dropna(subset=["line", "player_normalized", "market", "side", "sportsbook"])

    source_status = _source_status(selected_snapshots, configured_sources, as_of, policy.staleness_policy)
    projection_groups = {
        key: group.copy()
        for key, group in projections.groupby(["player_normalized", "market"], sort=True)
    } if not projections.empty else {}

    rows: list[dict[str, Any]] = []
    for _, odds_row in odds.sort_values(["player_normalized", "market", "side", "sportsbook", "line"], kind="mergesort").iterrows():
        key = (str(odds_row["player_normalized"]), str(odds_row["market"]))
        group = projection_groups.get(key, pd.DataFrame())
        row = _build_research_row(
            odds_row=odds_row,
            projections=group,
            source_status=source_status,
            configured_sources=configured_sources,
            ma_books=ma_books,
            policy=policy,
            season=season,
            week=week,
            as_of=as_of,
        )
        rows.append(row)

    research = pd.DataFrame(rows, columns=RESEARCH_COLUMNS)
    if not research.empty:
        research = _mark_contradictions(research, policy)
    source_details = _build_source_details(research)
    candidates = select_public_candidates(research)
    diagnostics = build_distribution_report(research)
    diagnostics_by_line_type = build_distribution_by_line_type(research)
    gate_counts = build_candidate_gate_counts(research, candidates)
    extreme_alternates = build_extreme_alternate_examples(research, candidates)
    return {
        "research_rows": research,
        "candidate_rows": candidates,
        "source_details": source_details,
        "diagnostics": diagnostics,
        "diagnostics_by_line_type": diagnostics_by_line_type,
        "candidate_gate_counts": gate_counts,
        "extreme_alternate_examples": extreme_alternates,
    }


def _source_status(selected_snapshots: pd.DataFrame, configured_sources: list[str], as_of: str, staleness_policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    enabled = bool(staleness_policy.get("enabled", True))
    max_age = _safe_float(staleness_policy.get("maximum_projection_age_hours")) if enabled else None
    by_source: dict[str, dict[str, Any]] = {}
    selected = selected_snapshots.copy() if selected_snapshots is not None else pd.DataFrame()
    for source in configured_sources:
        row = selected.loc[selected["source"].astype(str) == source].iloc[0].to_dict() if not selected.empty and source in set(selected["source"].astype(str)) else {}
        status = str(row.get("selection_status", "source_not_available"))
        age = _safe_float(row.get("snapshot_age_hours"))
        stale = bool(status == "selected" and max_age is not None and age is not None and age > max_age)
        by_source[source] = {
            "available": status == "selected",
            "stale": stale,
            "captured_at": row.get("selected_captured_at", ""),
            "raw_file": row.get("selected_raw_file", ""),
            "processed_file": row.get("selected_processed_file", ""),
            "snapshot_age_hours": age,
        }
    return by_source


def _build_research_row(
    *,
    odds_row: pd.Series,
    projections: pd.DataFrame,
    source_status: dict[str, dict[str, Any]],
    configured_sources: list[str],
    ma_books: set[str],
    policy: SignalPolicy,
    season: int,
    week: int,
    as_of: str,
) -> dict[str, Any]:
    line = float(odds_row["line"])
    projection_by_source = {str(row["source"]): float(row["projection"]) for _, row in projections.iterrows()}
    votes_by_source = {source: source_vote(value, line) for source, value in projection_by_source.items()}
    values = list(projection_by_source.values())
    source_count = len(values)
    over_votes = sum(1 for vote in votes_by_source.values() if vote == "over")
    under_votes = sum(1 for vote in votes_by_source.values() if vote == "under")
    neutral_votes = sum(1 for vote in votes_by_source.values() if vote == "neutral")
    if over_votes > under_votes:
        agreement_side = "over"
        agreement_count = over_votes
    elif under_votes > over_votes:
        agreement_side = "under"
        agreement_count = under_votes
    else:
        agreement_side = "neutral"
        agreement_count = neutral_votes if neutral_votes else max(over_votes, under_votes)
    agreement_fraction = agreement_count / source_count if source_count else 0.0

    mean_projection = float(np.mean(values)) if values else np.nan
    median_projection = float(np.median(values)) if values else np.nan
    projection_min = float(np.min(values)) if values else np.nan
    projection_max = float(np.max(values)) if values else np.nan
    projection_range = projection_max - projection_min if values else np.nan
    projection_stddev = float(np.std(values, ddof=1)) if len(values) > 1 else np.nan
    consensus_projection = median_projection
    consensus_edge = consensus_projection - line if not pd.isna(consensus_projection) else np.nan
    consensus_edge_abs = abs(consensus_edge) if not pd.isna(consensus_edge) else np.nan
    consensus_edge_pct = consensus_edge / line if line and not pd.isna(consensus_edge) else np.nan

    missing_sources = [source for source in configured_sources if source not in projection_by_source]
    stale_sources = sorted(source for source, info in source_status.items() if info["available"] and info["stale"] and source in projection_by_source)
    age_values = [info.get("snapshot_age_hours") for source, info in source_status.items() if source in projection_by_source and info.get("snapshot_age_hours") is not None]
    max_age_actual = max(age_values) if age_values else np.nan
    all_required_sources_available = source_count >= policy.required_source_count and not missing_sources

    market = str(odds_row["market"])
    market_enabled = bool(policy.market_policy.get(market, {}).get("green_light_enabled", False))
    sportsbook = str(odds_row["sportsbook"])
    staleness_policy = policy.staleness_policy
    candidate_policy = policy.public_candidate_policy
    edge_policy = policy.edge_policy
    dispersion_policy = policy.dispersion_policy
    min_edge_abs = _safe_float(edge_policy.get("minimum_consensus_edge_abs"))
    min_edge_pct = _safe_float(edge_policy.get("minimum_consensus_edge_pct"))
    max_std = _safe_float(dispersion_policy.get("maximum_projection_stddev"))
    max_range = _safe_float(dispersion_policy.get("maximum_projection_range"))
    max_age_policy = _safe_float(staleness_policy.get("maximum_projection_age_hours")) if bool(staleness_policy.get("enabled", True)) else None

    agreement_rule_pass = agreement_count >= policy.minimum_agreement_count and agreement_side in {"over", "under"}
    consensus_side = "over" if consensus_edge > 0 else "under" if consensus_edge < 0 else "neutral"
    consensus_side_rule_pass = consensus_side == agreement_side and str(odds_row["side"]).lower() == agreement_side
    source_count_rule_pass = source_count >= policy.required_source_count
    staleness_rule_pass = len(stale_sources) == 0 or not bool(staleness_policy.get("stale_sources_invalidate_green_light", True))
    market_rule_pass = market_enabled
    price_value = american_price_sort_value(odds_row.get("price"))
    min_public_odds = _safe_float(candidate_policy.get("min_american_odds"))
    max_public_odds = _safe_float(candidate_policy.get("max_american_odds"))
    price_rule_pass = public_price_rule_pass(price_value, policy)
    alternate_publication_rule_pass = bool(candidate_policy.get("allow_alternate_public_candidates", True)) or not _to_bool(odds_row.get("is_alternate", False))
    dispersion_rule_pass = (max_std is None or pd.isna(projection_stddev) or projection_stddev <= max_std) and (max_range is None or pd.isna(projection_range) or projection_range <= max_range)
    edge_rule_pass = (min_edge_abs is None or (not pd.isna(consensus_edge_abs) and consensus_edge_abs >= min_edge_abs)) and (min_edge_pct is None or (not pd.isna(consensus_edge_pct) and abs(consensus_edge_pct) >= min_edge_pct))
    actionable_ma_book = sportsbook in ma_books
    display_names = sportsbook_display_mapping(policy)
    public_candidate_eligible = actionable_ma_book and price_rule_pass and alternate_publication_rule_pass and market_rule_pass

    rule_failures: list[str] = []
    if not source_count_rule_pass:
        rule_failures.append("insufficient_projection_sources")
    if not agreement_rule_pass:
        rule_failures.append("insufficient_agreement")
    if not consensus_side_rule_pass:
        rule_failures.append("consensus_side_mismatch")
    if not staleness_rule_pass:
        rule_failures.append("stale_projection_source")
    if not market_rule_pass:
        rule_failures.append("market_disabled")
    if not price_rule_pass:
        rule_failures.append("price_out_of_range")
    if not dispersion_rule_pass:
        rule_failures.append("dispersion_threshold_failed")
    if not edge_rule_pass:
        rule_failures.append("edge_threshold_failed")
    if not actionable_ma_book:
        rule_failures.append("non_actionable_sportsbook")
    if not alternate_publication_rule_pass:
        rule_failures.append("alternate_publication_disabled")

    green_light = all([
        agreement_rule_pass,
        consensus_side_rule_pass,
        source_count_rule_pass,
        staleness_rule_pass,
        market_rule_pass,
        price_rule_pass,
        dispersion_rule_pass,
        edge_rule_pass,
        actionable_ma_book,
        alternate_publication_rule_pass,
    ])
    readable_failures = list(rule_failures)
    if not source_count_rule_pass:
        readable_failures.append(f"source_count:{source_count}/{policy.required_source_count}")
    if not agreement_rule_pass:
        readable_failures.append(f"agreement:{agreement_count}/{policy.minimum_agreement_count}")

    raw_files = {source: info.get("raw_file", "") for source, info in source_status.items() if source in projection_by_source}
    captured = {source: info.get("captured_at", "") for source, info in source_status.items() if source in projection_by_source}
    ages = {source: info.get("snapshot_age_hours", None) for source, info in source_status.items() if source in projection_by_source}
    signal_id = _make_id([
        season,
        week,
        odds_row.get("event_id", ""),
        odds_row.get("player_normalized", ""),
        market,
        line,
        odds_row.get("side", ""),
        sportsbook,
        odds_row.get("market_source_key", ""),
        _to_bool(odds_row.get("is_alternate", False)),
        as_of,
    ])
    return {
        "signal_id": signal_id,
        "season": int(season),
        "week": int(week),
        "as_of": as_of,
        "event_id": odds_row.get("event_id", ""),
        "commence_time": odds_row.get("commence_time", ""),
        "home_team": odds_row.get("home_team", ""),
        "away_team": odds_row.get("away_team", ""),
        "player": odds_row.get("player", ""),
        "player_normalized": odds_row.get("player_normalized", ""),
        "team": _coalesce_projection(projections, "team"),
        "opponent": odds_row.get("opponent", ""),
        "market": market,
        "sportsbook": sportsbook,
        "line": line,
        "side": str(odds_row.get("side", "")).lower(),
        "price": int(price_value) if price_value != float("-inf") and float(price_value).is_integer() else price_value,
        "is_alternate": _to_bool(odds_row.get("is_alternate", False)),
        "market_source_key": odds_row.get("market_source_key", ""),
        "captured_at": odds_row.get("captured_at", ""),
        "sportsbook_display_name": display_names.get(sportsbook, sportsbook),
        "configured_source_count": len(configured_sources),
        "required_source_count": policy.required_source_count,
        "source_count_available": source_count,
        "over_votes": over_votes,
        "under_votes": under_votes,
        "neutral_votes": neutral_votes,
        "agreement_side": agreement_side,
        "agreement_count": int(agreement_count),
        "agreement_fraction": float(agreement_fraction),
        "mean_projection": mean_projection,
        "median_projection": median_projection,
        "consensus_projection": consensus_projection,
        "min_projection": projection_min,
        "max_projection": projection_max,
        "projection_range": projection_range,
        "projection_stddev": projection_stddev,
        "consensus_edge": consensus_edge,
        "consensus_edge_abs": consensus_edge_abs,
        "consensus_edge_pct": consensus_edge_pct,
        "all_required_sources_available": bool(all_required_sources_available),
        "missing_sources": "|".join(missing_sources),
        "stale_source_count": len(stale_sources),
        "stale_sources": "|".join(stale_sources),
        "maximum_projection_age_hours_policy": max_age_policy,
        "max_projection_age_hours_actual": max_age_actual,
        "contradictory_projection_signal": False,
        "market_green_light_enabled": bool(market_enabled),
        "actionable_ma_book": bool(actionable_ma_book),
        "minimum_agreement_count": policy.minimum_agreement_count,
        "agreement_rule_pass": bool(agreement_rule_pass),
        "consensus_side_rule_pass": bool(consensus_side_rule_pass),
        "source_count_rule_pass": bool(source_count_rule_pass),
        "staleness_rule_pass": bool(staleness_rule_pass),
        "market_rule_pass": bool(market_rule_pass),
        "price_rule_pass": bool(price_rule_pass),
        "public_candidate_price_rule_pass": bool(price_rule_pass),
        "public_min_american_odds": min_public_odds,
        "public_max_american_odds": max_public_odds,
        "alternate_publication_rule_pass": bool(alternate_publication_rule_pass),
        "allow_alternate_public_candidates": bool(candidate_policy.get("allow_alternate_public_candidates", True)),
        "dispersion_rule_pass": bool(dispersion_rule_pass),
        "edge_rule_pass": bool(edge_rule_pass),
        "public_candidate_eligible": bool(public_candidate_eligible),
        "green_light_reason_codes": "" if green_light else "|".join(rule_failures),
        "green_light": bool(green_light),
        "green_light_reason": "passes_policy" if green_light else "|".join(readable_failures),
        "research_tier": agreement_tier(source_count, policy.required_source_count, agreement_count, over_votes, under_votes),
        "participating_sources": "|".join(sorted(projection_by_source)),
        "source_projection_values": _json(projection_by_source),
        "source_votes": _json(votes_by_source),
        "source_captured_at": _json(captured),
        "source_projection_age_hours": _json(ages),
        "source_raw_files": _json(raw_files),
    }


def _coalesce_projection(projections: pd.DataFrame, column: str) -> str:
    if projections.empty or column not in projections.columns:
        return ""
    values = [str(value) for value in projections[column].dropna().astype(str).tolist() if str(value).strip()]
    return values[0] if values else ""


def _mark_contradictions(research: pd.DataFrame, policy: SignalPolicy) -> pd.DataFrame:
    research = research.copy()
    contradictory_keys: set[tuple[str, str]] = set()
    for key, group in research.groupby(["player_normalized", "market"], sort=True):
        sides = set(group.loc[group["agreement_side"].isin(["over", "under"]), "agreement_side"].astype(str))
        if len(sides) > 1:
            contradictory_keys.add(key)
    if not contradictory_keys:
        return research
    mask = research[["player_normalized", "market"]].apply(tuple, axis=1).isin(contradictory_keys)
    research.loc[mask, "contradictory_projection_signal"] = True
    research.loc[mask, "green_light"] = False
    suffix = "contradictory_projection_signal"
    research.loc[mask, "green_light_reason_codes"] = research.loc[mask, "green_light_reason_codes"].astype(str).apply(lambda value: value if suffix in value else (value + "|" + suffix if value else suffix))
    research.loc[mask, "green_light_reason"] = research.loc[mask, "green_light_reason"].astype(str).apply(lambda value: value if suffix in value else (value + "|" + suffix if value else suffix))
    return research


def _build_source_details(research: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, row in research.iterrows():
        projections = json.loads(row["source_projection_values"]) if row.get("source_projection_values") else {}
        votes = json.loads(row["source_votes"]) if row.get("source_votes") else {}
        captured = json.loads(row["source_captured_at"]) if row.get("source_captured_at") else {}
        ages = json.loads(row["source_projection_age_hours"]) if row.get("source_projection_age_hours") else {}
        raw_files = json.loads(row["source_raw_files"]) if row.get("source_raw_files") else {}
        stale_sources = set(str(row.get("stale_sources", "")).split("|")) if str(row.get("stale_sources", "")).strip() else set()
        for source in sorted(projections):
            rows.append({
                "signal_id": row["signal_id"],
                "source": source,
                "projection": projections[source],
                "vote": votes.get(source, ""),
                "captured_at": captured.get(source, ""),
                "raw_file": raw_files.get(source, ""),
                "projection_age_hours": ages.get(source, np.nan),
                "stale_source": source in stale_sources,
            })
    return pd.DataFrame(rows, columns=SOURCE_DETAIL_COLUMNS)


def select_public_candidates(research: pd.DataFrame) -> pd.DataFrame:
    if research.empty:
        return pd.DataFrame(columns=CANDIDATE_COLUMNS)
    sortable = research.loc[research["public_candidate_eligible"].apply(_to_bool)].copy()
    if sortable.empty:
        return pd.DataFrame(columns=CANDIDATE_COLUMNS)
    sortable["price_sort"] = sortable["price"].apply(american_price_sort_value)
    sortable["main_line_sort"] = sortable["is_alternate"].apply(lambda value: 0 if _to_bool(value) else 1)
    sortable["green_sort"] = sortable["green_light"].apply(lambda value: 1 if _to_bool(value) else 0)
    sortable = sortable.sort_values(
        ["player_normalized", "market", "side", "green_sort", "agreement_count", "main_line_sort", "consensus_edge_abs", "price_sort", "sportsbook", "signal_id"],
        ascending=[True, True, True, False, False, False, False, False, True, True],
        kind="mergesort",
    )
    selected = sortable.groupby(["player_normalized", "market", "side"], sort=True, as_index=False).head(1).copy()
    rows = []
    for _, row in selected.iterrows():
        candidate_id = _make_id([row["season"], row["week"], row["event_id"], row["player_normalized"], row["market"], row["side"], row["as_of"]])
        rows.append({
            "candidate_id": candidate_id,
            "signal_id": row["signal_id"],
            "player": row["player"],
            "player_normalized": row["player_normalized"],
            "market": row["market"],
            "side": row["side"],
            "line": row["line"],
            "best_price": row["price"],
            "best_sportsbook": row["sportsbook"],
            "is_alternate": bool(row["is_alternate"]),
            "agreement_display": f"{int(row['agreement_count'])}/{int(row['required_source_count'])}",
            "consensus_projection": row["consensus_projection"],
            "consensus_edge": row["consensus_edge"],
            "projection_range": row["projection_range"],
            "source_count": row["source_count_available"],
            "green_light": bool(row["green_light"]),
            "green_light_reason": row["green_light_reason"],
            "as_of": row["as_of"],
            "source_details": row["source_projection_values"],
        })
    return pd.DataFrame(rows, columns=CANDIDATE_COLUMNS)


def build_distribution_report(research: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if research.empty:
        return pd.DataFrame(columns=["market", "metric", "value", "count"])
    percentiles = [0.1, 0.25, 0.5, 0.75, 0.9]
    for market, group in research.groupby("market", sort=True):
        rows.append({"market": market, "metric": "opportunities", "value": "all", "count": int(len(group))})
        for agreement_count, count in group["agreement_count"].value_counts().sort_index().items():
            rows.append({"market": market, "metric": "agreement_count", "value": int(agreement_count), "count": int(count)})
        for is_alt, count in group["is_alternate"].value_counts().sort_index().items():
            rows.append({"market": market, "metric": "line_type", "value": "alternate" if _to_bool(is_alt) else "main", "count": int(count)})
        for side, count in group["side"].value_counts().sort_index().items():
            rows.append({"market": market, "metric": "side", "value": side, "count": int(count)})
        for column in ["consensus_edge_abs", "consensus_edge_pct", "projection_range", "projection_stddev", "price"]:
            series = pd.to_numeric(group[column], errors="coerce").dropna()
            if series.empty:
                continue
            for q in percentiles:
                rows.append({"market": market, "metric": f"{column}_p{int(q * 100)}", "value": float(series.quantile(q)), "count": int(len(series))})
    return pd.DataFrame(rows, columns=["market", "metric", "value", "count"])


def _line_type(value: Any) -> str:
    return "alternate" if _to_bool(value) else "main"


def build_distribution_by_line_type(research: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "market",
        "line_type",
        "row_count",
        "unique_player_market_side_count",
        "consensus_edge_abs_p25",
        "consensus_edge_abs_p50",
        "consensus_edge_abs_p75",
        "consensus_edge_abs_p90",
        "consensus_edge_abs_p95",
        "consensus_edge_pct_p25",
        "consensus_edge_pct_p50",
        "consensus_edge_pct_p75",
        "consensus_edge_pct_p90",
        "consensus_edge_pct_p95",
        "projection_range_p50",
        "projection_range_p75",
        "projection_range_p90",
        "projection_stddev_p50",
        "projection_stddev_p75",
        "projection_stddev_p90",
        "price_p10",
        "price_p50",
        "price_p90",
    ]
    if research.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, Any]] = []
    working = research.copy()
    working["line_type"] = working["is_alternate"].apply(_line_type)
    for (market, line_type), group in working.groupby(["market", "line_type"], sort=True):
        row: dict[str, Any] = {
            "market": market,
            "line_type": line_type,
            "row_count": int(len(group)),
            "unique_player_market_side_count": int(group[["player_normalized", "market", "side"]].drop_duplicates().shape[0]),
        }
        for column, qs in {
            "consensus_edge_abs": [0.25, 0.5, 0.75, 0.9, 0.95],
            "consensus_edge_pct": [0.25, 0.5, 0.75, 0.9, 0.95],
            "projection_range": [0.5, 0.75, 0.9],
            "projection_stddev": [0.5, 0.75, 0.9],
            "price": [0.1, 0.5, 0.9],
        }.items():
            series = pd.to_numeric(group[column], errors="coerce").dropna()
            for q in qs:
                row[f"{column}_p{int(q * 100)}"] = float(series.quantile(q)) if not series.empty else np.nan
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def build_candidate_gate_counts(research: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "market",
        "total_research_rows",
        "ma_actionable_rows",
        "price_eligible_rows",
        "non_stale_rows",
        "source_count_eligible_rows",
        "agreement_eligible_rows",
        "final_green_light_rows",
        "selected_public_candidates",
        "excluded_too_much_negative_juice",
        "excluded_too_large_positive_price",
    ]
    if research.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, Any]] = []
    candidate_counts = candidates.groupby("market").size().to_dict() if not candidates.empty else {}
    for market, group in research.groupby("market", sort=True):
        prices = pd.to_numeric(group["price"], errors="coerce")
        min_value = _first_numeric(group.get("public_min_american_odds", pd.Series(dtype=float)))
        max_value = _first_numeric(group.get("public_max_american_odds", pd.Series(dtype=float)))
        rows.append({
            "market": market,
            "total_research_rows": int(len(group)),
            "ma_actionable_rows": int(group["actionable_ma_book"].apply(_to_bool).sum()),
            "price_eligible_rows": int(group["public_candidate_price_rule_pass"].apply(_to_bool).sum()),
            "non_stale_rows": int(group["staleness_rule_pass"].apply(_to_bool).sum()),
            "source_count_eligible_rows": int(group["source_count_rule_pass"].apply(_to_bool).sum()),
            "agreement_eligible_rows": int(group["agreement_rule_pass"].apply(_to_bool).sum()),
            "final_green_light_rows": int(group["green_light"].apply(_to_bool).sum()),
            "selected_public_candidates": int(candidate_counts.get(market, 0)),
            "excluded_too_much_negative_juice": int((prices < min_value).sum()) if min_value is not None else 0,
            "excluded_too_large_positive_price": int((prices > max_value).sum()) if max_value is not None else 0,
        })
    return pd.DataFrame(rows, columns=columns)


def _first_numeric(series: pd.Series) -> float | None:
    if series is None or series.empty:
        return None
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.iloc[0])


def build_extreme_alternate_examples(research: pd.DataFrame, candidates: pd.DataFrame, limit: int = 50) -> pd.DataFrame:
    columns = [
        "player",
        "player_normalized",
        "market",
        "side",
        "line",
        "price",
        "is_alternate",
        "consensus_projection",
        "consensus_edge",
        "consensus_edge_abs",
        "agreement_count",
        "exclusion_reason",
        "selected_competing_line",
        "selected_competing_price",
        "selected_competing_sportsbook",
        "selected_competing_is_alternate",
    ]
    if research.empty:
        return pd.DataFrame(columns=columns)
    alternate = research.loc[research["is_alternate"].apply(_to_bool)].copy()
    if alternate.empty:
        return pd.DataFrame(columns=columns)
    selected_by_key = {}
    if not candidates.empty:
        for _, row in candidates.iterrows():
            selected_by_key[(row["player_normalized"], row["market"], row["side"])] = row
    rows: list[dict[str, Any]] = []
    ranked = alternate.sort_values(["consensus_edge_abs", "agreement_count", "price"], ascending=[False, False, False], kind="mergesort")
    for _, row in ranked.head(limit).iterrows():
        key = (row["player_normalized"], row["market"], row["side"])
        selected = selected_by_key.get(key)
        reasons = []
        if not _to_bool(row["public_candidate_price_rule_pass"]):
            reasons.append("price_out_of_range")
        if not _to_bool(row["alternate_publication_rule_pass"]):
            reasons.append("alternate_publication_disabled")
        if not _to_bool(row["actionable_ma_book"]):
            reasons.append("non_actionable_sportsbook")
        if selected is not None and selected.get("signal_id") != row["signal_id"]:
            reasons.append("lost_to_selected_candidate")
        rows.append({
            "player": row["player"],
            "player_normalized": row["player_normalized"],
            "market": row["market"],
            "side": row["side"],
            "line": row["line"],
            "price": row["price"],
            "is_alternate": row["is_alternate"],
            "consensus_projection": row["consensus_projection"],
            "consensus_edge": row["consensus_edge"],
            "consensus_edge_abs": row["consensus_edge_abs"],
            "agreement_count": row["agreement_count"],
            "exclusion_reason": "|".join(reasons),
            "selected_competing_line": selected.get("line", np.nan) if selected is not None else np.nan,
            "selected_competing_price": selected.get("best_price", np.nan) if selected is not None else np.nan,
            "selected_competing_sportsbook": selected.get("best_sportsbook", "") if selected is not None else "",
            "selected_competing_is_alternate": selected.get("is_alternate", "") if selected is not None else "",
        })
    return pd.DataFrame(rows, columns=columns)


def build_manifest(
    *,
    policy: SignalPolicy,
    source_state: dict[str, Any],
    odds_snapshots: pd.DataFrame,
    outputs: dict[str, str],
    season: int,
    week: int,
    as_of: str,
    run_timestamp: str,
    research_rows: pd.DataFrame,
    candidate_rows: pd.DataFrame,
) -> dict[str, Any]:
    selected_odds = []
    if odds_snapshots is not None and not odds_snapshots.empty:
        for _, row in odds_snapshots.iterrows():
            selected_odds.append({
                "sportsbook": row.get("sportsbook", ""),
                "selection_status": row.get("selection_status", ""),
                "captured_at": row.get("selected_captured_at", ""),
                "raw_file": row.get("selected_raw_file", ""),
                "processed_file": row.get("selected_processed_file", ""),
                "snapshot_age_hours": row.get("snapshot_age_hours", None),
            })
    return {
        "run_timestamp": run_timestamp,
        "season": int(season),
        "week": int(week),
        "as_of": as_of,
        "policy": normalize_policy_dict(policy),
        "source_state": source_state,
        "selected_odds_snapshots": selected_odds,
        "research_rows": int(len(research_rows)),
        "candidate_rows": int(len(candidate_rows)),
        "green_light_rows": int(research_rows["green_light"].sum()) if not research_rows.empty else 0,
        "green_light_candidates": int(candidate_rows["green_light"].sum()) if not candidate_rows.empty else 0,
        "outputs": outputs,
        "candidate_ranking_policy": [
            "green_light_true_first",
            "highest_agreement_count",
            "main_line_before_alternate",
            "highest_consensus_edge_abs",
            "best_bettor_american_price",
            "sportsbook_key",
            "stable_signal_id",
        ],
        "schema_version": "prospective_projection_signal_v1",
    }
