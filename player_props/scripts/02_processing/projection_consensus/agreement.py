from __future__ import annotations

from typing import Any

import pandas as pd


def evaluate_directional_agreement(source_projections: list[float] | tuple[float, ...] | pd.Series | dict[str, float], reference_line: float | int) -> dict[str, Any]:
    if isinstance(source_projections, pd.Series):
        labels = list(source_projections.index)
        values = list(source_projections.tolist())
    elif isinstance(source_projections, dict):
        labels = list(source_projections.keys())
        values = list(source_projections.values())
    else:
        labels = list(range(len(source_projections)))
        values = list(source_projections)

    if not values:
        return {
            "sources_above_line": [],
            "sources_below_line": [],
            "sources_equal_line": [],
            "above_count": 0,
            "below_count": 0,
            "equal_count": 0,
            "unanimous_over": False,
            "unanimous_under": False,
            "over_agreement_fraction": None,
            "under_agreement_fraction": None,
            "majority_side": "",
            "agreement_count": 0,
            "agreement_fraction": None,
        }

    above = [label for label, value in zip(labels, values) if value > reference_line]
    below = [label for label, value in zip(labels, values) if value < reference_line]
    equal = [label for label, value in zip(labels, values) if value == reference_line]

    above_count = len(above)
    below_count = len(below)
    equal_count = len(equal)
    if above_count and above_count == len(values):
        unanimous_over = True
        unanimous_under = False
    elif below_count and below_count == len(values):
        unanimous_over = False
        unanimous_under = True
    else:
        unanimous_over = False
        unanimous_under = False

    if above_count > below_count and above_count > equal_count:
        majority_side = "over"
    elif below_count > above_count and below_count > equal_count:
        majority_side = "under"
    elif equal_count > above_count and equal_count > below_count:
        majority_side = "equal"
    else:
        majority_side = "split"

    agreement_count = max(above_count, below_count, equal_count)
    agreement_fraction = agreement_count / len(values) if values else None
    return {
        "sources_above_line": above,
        "sources_below_line": below,
        "sources_equal_line": equal,
        "above_count": above_count,
        "below_count": below_count,
        "equal_count": equal_count,
        "unanimous_over": unanimous_over,
        "unanimous_under": unanimous_under,
        "over_agreement_fraction": above_count / len(values) if values else None,
        "under_agreement_fraction": below_count / len(values) if values else None,
        "majority_side": majority_side,
        "agreement_count": agreement_count,
        "agreement_fraction": agreement_fraction,
    }
