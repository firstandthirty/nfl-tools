from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BucketSpec:
    name: str
    source_column: str
    output_column: str
    unit: str
    bins: list[float]
    labels: list[str]
    right: bool = False

    @property
    def boundary_text(self) -> str:
        return ", ".join(str(x) for x in self.bins)


RECEPTIONS_EDGE_SPEC = BucketSpec(
    name="absolute_projection_edge",
    source_column="edge_receptions",
    output_column="verified_edge_bucket",
    unit="receptions, absolute projection-minus-line",
    bins=[0, 0.5, 1, 1.5, 2, 3, 4, math.inf],
    labels=["0-0.5", "0.5-1", "1-1.5", "1.5-2", "2-3", "3-4", "4+"],
)
SIGNED_RECEPTIONS_EDGE_SPEC = BucketSpec(
    name="projection_edge",
    source_column="projection_minus_line",
    output_column="projection_minus_line_bucket",
    unit="receptions, signed projection-minus-line",
    bins=[-math.inf, -1, -0.5, -0.25, 0, 0.25, 0.5, 1, math.inf],
    labels=["<-1", "-1--0.5", "-0.5--0.25", "-0.25-0", "0-0.25", "0.25-0.5", "0.5-1", "1+"],
)
PROBABILITY_SPEC = BucketSpec(
    name="recommended_probability",
    source_column="recommended_prob",
    output_column="probability_bucket",
    unit="decimal probability",
    bins=[-math.inf, 0.45, 0.50, 0.525, 0.55, 0.575, 0.60, 0.625, 0.65, 0.70, math.inf],
    labels=["<45%", "45-50%", "50-52.5%", "52.5-55%", "55-57.5%", "57.5-60%", "60-62.5%", "62.5-65%", "65-70%", "70%+"],
)
EV_SPEC = BucketSpec(
    name="recommended_ev_percent",
    source_column="recommended_ev_percent",
    output_column="ev_bucket",
    unit="percentage points",
    bins=[-math.inf, 0, 2, 5, 10, 15, 20, math.inf],
    labels=["<0", "0-2", "2-5", "5-10", "10-15", "15-20", "20+"],
)
LINE_SPEC = BucketSpec(
    name="line",
    source_column="line",
    output_column="line_bucket",
    unit="receptions line",
    bins=[-math.inf, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, math.inf],
    labels=["<1.5", "1.5", "2.5", "3.5", "4.5", "5.5", "6.5+"],
)


def apply_bucket(df: pd.DataFrame, source: str, spec: BucketSpec) -> None:
    if source in df:
        df[spec.output_column] = pd.cut(
            df[source], bins=spec.bins, labels=spec.labels, right=spec.right
        )


def add_buckets(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    apply_bucket(out, "line_value", LINE_SPEC)
    apply_bucket(out, "projection_edge", SIGNED_RECEPTIONS_EDGE_SPEC)
    apply_bucket(out, "predicted_probability", PROBABILITY_SPEC)
    apply_bucket(out, "recommended_ev_percent_value", EV_SPEC)
    apply_bucket(out, "absolute_projection_edge", RECEPTIONS_EDGE_SPEC)
    if "edge_bucket" in out and "source_edge_bucket" not in out:
        out["source_edge_bucket"] = out["edge_bucket"]
    if "ev_bucket" in df:
        out["source_ev_bucket"] = df["ev_bucket"]
    return out


def bucket_metadata_rows() -> list[dict[str, object]]:
    return [
        {
            "field": spec.name,
            "source_column": spec.source_column,
            "output_column": spec.output_column,
            "interpreted_unit": spec.unit,
            "bucket_boundaries": spec.boundary_text,
            "bucket_labels": ", ".join(spec.labels),
        }
        for spec in [LINE_SPEC, SIGNED_RECEPTIONS_EDGE_SPEC, PROBABILITY_SPEC, EV_SPEC, RECEPTIONS_EDGE_SPEC]
    ]

