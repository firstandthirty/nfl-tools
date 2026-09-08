from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCES = ["4for4", "fantasypros", "ftn", "pff"]
OPPORTUNITY_KEY = ["event_id", "player_normalized", "market", "line", "side"]
LINE_KEY = ["event_id", "player_normalized", "market", "line"]
PLAYER_MARKET_KEY = ["event_id", "player_normalized", "market"]
QUANTILES = [0.25, 0.5, 0.75, 0.9]
MA_SPORTSBOOKS = {"draftkings", "fanduel", "betmgm", "williamhill_us", "fanatics", "espnbet"}
PUBLIC_MIN_PRICE = -150
PUBLIC_MAX_PRICE = 200


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def _agreement_bucket(row: pd.Series) -> str:
    if int(row["source_count_available"]) != 4:
        return "not_all_four"
    over_votes = int(row["over_votes"])
    under_votes = int(row["under_votes"])
    agreement_count = int(row["agreement_count"])
    if agreement_count == 4:
        return "4/4"
    if agreement_count == 3:
        return "3/4"
    if over_votes == 2 and under_votes == 2:
        return "2/2_split"
    return "other"


def _quantile_fields(frame: pd.DataFrame, column: str, prefix: str) -> dict[str, float]:
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if values.empty:
        return {f"{prefix}_p{int(q * 100)}": float("nan") for q in QUANTILES}
    return {f"{prefix}_p{int(q * 100)}": float(values.quantile(q)) for q in QUANTILES}


def _summarize_agreement(frame: pd.DataFrame, *, grain: str) -> pd.DataFrame:
    rows = []
    for (market, is_alternate), group in frame.groupby(["market", "is_alternate"], dropna=False):
        total = len(group)
        counts = group["agreement_bucket"].value_counts()
        row = {
            "grain": grain,
            "line_type": "alternate" if bool(is_alternate) else "main",
            "market": market,
            "total_all_four": int(total),
            "agreement_4_of_4": int(counts.get("4/4", 0)),
            "agreement_3_of_4": int(counts.get("3/4", 0)),
            "split_2_2": int(counts.get("2/2_split", 0)),
            "other_agreement": int(total - counts.get("4/4", 0) - counts.get("3/4", 0) - counts.get("2/2_split", 0)),
        }
        for key in ["agreement_4_of_4", "agreement_3_of_4", "split_2_2", "other_agreement"]:
            row[f"{key}_pct"] = row[key] / total if total else 0.0
        row.update(_quantile_fields(group, "consensus_edge_abs", "consensus_edge_abs"))
        row.update(_quantile_fields(group, "projection_range", "projection_range"))
        row.update(_quantile_fields(group, "projection_stddev", "projection_stddev"))
        rows.append(row)
    return pd.DataFrame(rows)


def _line_availability(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    main = rows.loc[~rows["is_alternate"].astype(bool)].copy()
    coverage_rows = []
    disagreement_rows = []
    for market, group in main.groupby("market"):
        player_market = group.groupby(PLAYER_MARKET_KEY)
        books_per_player_market = player_market["sportsbook"].nunique()
        line_counts = player_market["line"].nunique()
        coverage_rows.append(
            {
                "market": market,
                "unique_player_main_lines": int(group.drop_duplicates(LINE_KEY).shape[0]),
                "sportsbook_offers": int(len(group)),
                "unique_player_markets": int(player_market.ngroups),
                "median_books_per_player_market": float(books_per_player_market.median()) if not books_per_player_market.empty else float("nan"),
                "distinct_lines_1": int((line_counts == 1).sum()),
                "distinct_lines_2": int((line_counts == 2).sum()),
                "distinct_lines_3_plus": int((line_counts >= 3).sum()),
                "player_markets_with_line_disagreement": int((line_counts > 1).sum()),
            }
        )
    for key, group in main.groupby(PLAYER_MARKET_KEY):
        if group["line"].nunique() <= 1:
            continue
        disagreement_rows.append(
            {
                "event_id": key[0],
                "player_normalized": key[1],
                "market": key[2],
                "distinct_lines": int(group["line"].nunique()),
                "lines": "|".join(str(value) for value in sorted(group["line"].dropna().unique())),
                "sportsbooks": "|".join(sorted(group["sportsbook"].dropna().astype(str).unique())),
                "offers": int(len(group)),
            }
        )
    return pd.DataFrame(coverage_rows), pd.DataFrame(disagreement_rows)


def _ma_actionable(rows: pd.DataFrame) -> pd.DataFrame:
    all_rows = rows.loc[~rows["is_alternate"].astype(bool)].copy()
    all_rows["agreement_bucket"] = all_rows.apply(_agreement_bucket, axis=1)
    dedup = all_rows.sort_values(["sportsbook", "signal_id"]).drop_duplicates(OPPORTUNITY_KEY, keep="first").copy()
    dedup["ma_actionable"] = dedup["sportsbook"].astype(str).isin(MA_SPORTSBOOKS)
    dedup["within_public_price_bounds"] = pd.to_numeric(dedup["price"], errors="coerce").between(PUBLIC_MIN_PRICE, PUBLIC_MAX_PRICE, inclusive="both")
    rows_out = []
    for market, group in dedup.groupby("market"):
        ma = group.loc[group["ma_actionable"]]
        priced = ma.loc[ma["within_public_price_bounds"]]
        rows_out.append(
            {
                "market": market,
                "total_dedup_main_opportunities": int(len(group)),
                "ma_actionable_opportunities": int(len(ma)),
                "ma_within_public_price_bounds": int(len(priced)),
                "ma_price_bounds_4_of_4": int((priced["agreement_bucket"] == "4/4").sum()),
                "ma_price_bounds_3_of_4": int((priced["agreement_bucket"] == "3/4").sum()),
                "ma_price_bounds_2_2_split": int((priced["agreement_bucket"] == "2/2_split").sum()),
                "ma_price_bounds_other_agreement": int((~priced["agreement_bucket"].isin(["4/4", "3/4", "2/2_split"])).sum()),
            }
        )
    return pd.DataFrame(rows_out)


def _quality_by_bucket(opportunities: pd.DataFrame) -> pd.DataFrame:
    main = opportunities.loc[~opportunities["is_alternate"].astype(bool)].copy()
    rows = []
    for (market, bucket), group in main.groupby(["market", "agreement_bucket"]):
        if bucket not in {"4/4", "3/4", "2/2_split"}:
            continue
        row = {
            "market": market,
            "agreement_bucket": bucket,
            "count": int(len(group)),
            "median_abs_consensus_edge": float(group["consensus_edge_abs"].median()),
            "p75_abs_consensus_edge": float(group["consensus_edge_abs"].quantile(0.75)),
            "p90_abs_consensus_edge": float(group["consensus_edge_abs"].quantile(0.9)),
            "median_projection_range": float(group["projection_range"].median()),
            "p75_projection_range": float(group["projection_range"].quantile(0.75)),
            "p90_projection_range": float(group["projection_range"].quantile(0.9)),
            "median_projection_stddev": float(group["projection_stddev"].median()),
            "p75_projection_stddev": float(group["projection_stddev"].quantile(0.75)),
            "p90_projection_stddev": float(group["projection_stddev"].quantile(0.9)),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def _parse_json_dict(value: object) -> dict:
    if value is None or pd.isna(value):
        return {}
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return {}


def _dissent_rows(opportunities: pd.DataFrame) -> pd.DataFrame:
    rows = []
    three = opportunities.loc[(~opportunities["is_alternate"].astype(bool)) & (opportunities["agreement_bucket"] == "3/4")].copy()
    for _, row in three.iterrows():
        votes = _parse_json_dict(row["source_votes"])
        projections = {k: float(v) for k, v in _parse_json_dict(row["source_projection_values"]).items() if k in SOURCES}
        side_counts = pd.Series(list(votes.values())).value_counts()
        majority_side = side_counts.index[0] if not side_counts.empty else ""
        dissent_sources = [source for source, side in votes.items() if side != majority_side]
        if len(dissent_sources) != 1:
            dissent_source = ""
            dissent_vs_other_median = float("nan")
        else:
            dissent_source = dissent_sources[0]
            others = [value for source, value in projections.items() if source != dissent_source]
            dissent_vs_other_median = projections.get(dissent_source, float("nan")) - float(pd.Series(others).median())
        agreeing = [projections[source] for source, side in votes.items() if side == majority_side and source in projections]
        rows.append(
            {
                "event_id": row["event_id"],
                "player_normalized": row["player_normalized"],
                "market": row["market"],
                "line": row["line"],
                "side": row["side"],
                "majority_side": majority_side,
                "dissent_source": dissent_source,
                "dissent_projection_vs_other_three_median": dissent_vs_other_median,
                "agreeing_projection_range": max(agreeing) - min(agreeing) if agreeing else float("nan"),
                "agreeing_projection_stddev": float(pd.Series(agreeing).std()) if len(agreeing) > 1 else float("nan"),
                "consensus_edge_abs": row["consensus_edge_abs"],
                "projection_range": row["projection_range"],
                "projection_stddev": row["projection_stddev"],
                "source_projection_values": row["source_projection_values"],
                "source_votes": row["source_votes"],
            }
        )
    return pd.DataFrame(rows)


def _pairwise(selected_projection_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    selected = _read_csv(selected_projection_path)
    duplicate_count = int(selected.duplicated(["player_normalized", "market", "source"]).sum())
    pivot = selected.pivot_table(index=["player_normalized", "market"], columns="source", values="projection", aggfunc="first")
    diff_rows = []
    corr_rows = []
    for source_a, source_b in combinations(SOURCES, 2):
        available = pivot[[source_a, source_b]].dropna() if source_a in pivot.columns and source_b in pivot.columns else pd.DataFrame()
        for market, group in available.groupby(level="market"):
            diff = group[source_a] - group[source_b]
            abs_diff = diff.abs()
            diff_rows.append(
                {
                    "source_pair": f"{source_a} vs {source_b}",
                    "source_a": source_a,
                    "source_b": source_b,
                    "market": market,
                    "n": int(len(group)),
                    "mean_signed_difference_a_minus_b": float(diff.mean()),
                    "median_signed_difference_a_minus_b": float(diff.median()),
                    "mae": float(abs_diff.mean()),
                    "p50_absolute_difference": float(abs_diff.quantile(0.5)),
                    "p75_absolute_difference": float(abs_diff.quantile(0.75)),
                    "p90_absolute_difference": float(abs_diff.quantile(0.9)),
                    "duplicate_player_market_source_rows": duplicate_count,
                }
            )
            corr_rows.append(
                {
                    "source_pair": f"{source_a} vs {source_b}",
                    "market": market,
                    "n": int(len(group)),
                    "pearson_correlation": float(group[source_a].corr(group[source_b])) if len(group) >= 3 else float("nan"),
                }
            )
    return pd.DataFrame(diff_rows), pd.DataFrame(corr_rows)


def run(args: argparse.Namespace) -> dict[str, Path]:
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = _read_csv(args.research_rows)
    all_four = rows.loc[rows["source_count_available"].astype(int) == 4].copy()
    all_four["agreement_bucket"] = all_four.apply(_agreement_bucket, axis=1)

    dedup = all_four.sort_values(["sportsbook", "signal_id"]).drop_duplicates(OPPORTUNITY_KEY, keep="first").copy()

    sportsbook_summary = _summarize_agreement(all_four, grain="sportsbook_row")
    opportunity_summary = _summarize_agreement(dedup, grain="dedup_opportunity")
    quality = _quality_by_bucket(dedup)
    dissent = _dissent_rows(dedup)
    dissent_summary = (
        dissent.groupby(["market", "dissent_source"])
        .size()
        .reset_index(name="opportunities")
        .sort_values(["market", "opportunities"], ascending=[True, False])
        if not dissent.empty
        else pd.DataFrame(columns=["market", "dissent_source", "opportunities"])
    )
    pairwise, correlations = _pairwise(args.selected_source_projections)
    line_coverage, line_disagreement = _line_availability(rows)
    ma_actionable = _ma_actionable(rows)

    outputs = {
        "sportsbook_row_agreement": output_dir / "sportsbook_row_agreement_summary.csv",
        "dedup_opportunity_agreement": output_dir / "dedup_opportunity_agreement_summary.csv",
        "dedup_opportunities": output_dir / "dedup_opportunities_all_four.csv",
        "main_line_quality": output_dir / "dedup_main_line_quality_by_bucket.csv",
        "dissent_rows": output_dir / "dedup_main_line_3of4_dissent_rows.csv",
        "dissent_summary": output_dir / "dedup_main_line_3of4_dissent_summary.csv",
        "pairwise_differences": output_dir / "fresh_source_pairwise_differences.csv",
        "pairwise_correlations": output_dir / "fresh_source_pairwise_correlations.csv",
        "line_coverage": output_dir / "main_line_price_availability.csv",
        "line_disagreement": output_dir / "main_line_sportsbook_line_disagreement.csv",
        "ma_actionable": output_dir / "ma_actionable_main_line_summary.csv",
    }
    sportsbook_summary.to_csv(outputs["sportsbook_row_agreement"], index=False)
    opportunity_summary.to_csv(outputs["dedup_opportunity_agreement"], index=False)
    dedup.to_csv(outputs["dedup_opportunities"], index=False)
    quality.to_csv(outputs["main_line_quality"], index=False)
    dissent.to_csv(outputs["dissent_rows"], index=False)
    dissent_summary.to_csv(outputs["dissent_summary"], index=False)
    pairwise.to_csv(outputs["pairwise_differences"], index=False)
    correlations.to_csv(outputs["pairwise_correlations"], index=False)
    line_coverage.to_csv(outputs["line_coverage"], index=False)
    line_disagreement.to_csv(outputs["line_disagreement"], index=False)
    ma_actionable.to_csv(outputs["ma_actionable"], index=False)

    print("[opportunity_key]", "|".join(OPPORTUNITY_KEY))
    print("[sportsbook_rows_all_four]", len(all_four))
    print("[dedup_opportunities_all_four]", len(dedup))
    print("[outputs]")
    for name, path in outputs.items():
        print(f"{name}={path}")
    print("[dedup_agreement_summary]")
    print(opportunity_summary.round(4).to_string(index=False))
    print("[main_line_quality]")
    print(quality.round(4).to_string(index=False))
    print("[dissent_summary]")
    print(dissent_summary.to_string(index=False))
    print("[line_coverage]")
    print(line_coverage.round(4).to_string(index=False))
    print("[ma_actionable]")
    print(ma_actionable.to_string(index=False))
    print("[pairwise_correlations_high]")
    print(correlations.loc[correlations["pearson_correlation"] >= 0.98].round(4).to_string(index=False))
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Fresh Week 1 four-source projection diagnostics")
    parser.add_argument("--research-rows", type=Path, required=True)
    parser.add_argument("--selected-source-projections", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data/analysis/projection_audits/four_source_week1_fresh")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
