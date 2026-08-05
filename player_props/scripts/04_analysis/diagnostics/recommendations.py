from __future__ import annotations

from dataclasses import dataclass
import itertools
import math

import pandas as pd

from .metrics import summarize


@dataclass(frozen=True)
class Rule:
    label: str
    mask: pd.Series
    dimensions: int
    comparisons: int


def category_rules(df: pd.DataFrame, dimensions: list[str], min_removed: int, max_categories: int) -> list[Rule]:
    rules: list[Rule] = []
    usable = [d for d in dimensions if d in df and 1 < df[d].nunique(dropna=True) <= max_categories]
    comparisons = 0
    for dim in usable:
        for value in df[dim].dropna().unique():
            comparisons += 1
            mask = df[dim].eq(value).fillna(False)
            if int(mask.sum()) >= min_removed:
                rules.append(Rule(f"{dim} = {value}", mask, 1, comparisons))
    for dim_a, dim_b in itertools.combinations(usable, 2):
        combos = df[[dim_a, dim_b]].dropna().drop_duplicates()
        for _, combo in combos.iterrows():
            comparisons += 1
            mask = df[dim_a].eq(combo[dim_a]).fillna(False) & df[dim_b].eq(combo[dim_b]).fillna(False)
            if int(mask.sum()) >= min_removed:
                rules.append(Rule(f"{dim_a} = {combo[dim_a]} AND {dim_b} = {combo[dim_b]}", mask, 2, comparisons))
    return rules


def threshold_rules(df: pd.DataFrame, columns: list[str], min_removed: int) -> list[Rule]:
    rules: list[Rule] = []
    comparisons = 0
    for col in columns:
        if col not in df:
            continue
        values = pd.to_numeric(df[col], errors="coerce").dropna()
        if values.nunique() < 3:
            continue
        for q in [0.1, 0.2, 0.25, 0.5, 0.75, 0.8, 0.9]:
            threshold = float(values.quantile(q))
            for op in ["<", ">="]:
                comparisons += 1
                mask = df[col].lt(threshold) if op == "<" else df[col].ge(threshold)
                if int(mask.sum()) >= min_removed:
                    rules.append(Rule(f"{col} {op} {threshold:.4g}", mask.fillna(False), 1, comparisons))
    return rules


def evidence_label(row: dict[str, object]) -> str:
    removed = int(row["removed_bets"])
    remaining = int(row["remaining_bets"])
    retained = float(row["pct_bets_retained"])
    lift = float(row["roi_lift"])
    if removed < 30 or remaining < 100 or retained < 0.5:
        return "insufficient sample"
    if lift > 0.02 and float(row["removed_roi"]) < 0 and removed >= 50:
        return "hypothesis worth holdout testing"
    return "weak exploratory signal"


def candidate_kill_table(df: pd.DataFrame, rules: list[Rule], min_remaining: int) -> pd.DataFrame:
    baseline = summarize(df)
    rows: list[dict[str, object]] = []
    for rule in rules:
        removed = df[rule.mask].copy()
        remaining = df[~rule.mask].copy()
        removed_stats = summarize(removed)
        remaining_stats = summarize(remaining)
        if remaining_stats["bets"] < min_remaining or removed_stats["bets"] == 0:
            continue
        row = {
            "rule_removed": rule.label,
            "rule_dimensions": rule.dimensions,
            "removed_bets": removed_stats["bets"],
            "removed_roi": removed_stats["roi"],
            "removed_profit_units": removed_stats["profit_units"],
            "remaining_bets": remaining_stats["bets"],
            "remaining_roi": remaining_stats["roi"],
            "remaining_profit_units": remaining_stats["profit_units"],
            "roi_lift": remaining_stats["roi"] - baseline["roi"],
            "profit_change_units": remaining_stats["profit_units"] - baseline["profit_units"],
            "pct_bets_retained": remaining_stats["bets"] / baseline["bets"] if baseline["bets"] else math.nan,
            "baseline_roi": baseline["roi"],
            "baseline_bets": baseline["bets"],
            "multiple_testing_note": f"exploratory; rule family comparison index {rule.comparisons}",
        }
        row["evidence_class"] = evidence_label(row)
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["evidence_class", "roi_lift", "removed_bets"], ascending=[True, False, False])


def generate_candidate_rules(df: pd.DataFrame, dimensions: list[str], numeric_columns: list[str], min_removed: int, max_categories: int) -> list[Rule]:
    return category_rules(df, dimensions, min_removed, max_categories) + threshold_rules(df, numeric_columns, min_removed)

