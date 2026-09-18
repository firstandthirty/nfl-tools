from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from .style import DEFAULT_STYLE, ChartStyle


@dataclass(frozen=True)
class LabelPoint:
    label: str
    x: float
    y: float


def add_average_lines(ax, *, x_avg: float, y_avg: float, style: ChartStyle = DEFAULT_STYLE) -> None:
    ax.axvline(x_avg, color=style.reference, linewidth=1.1, alpha=0.55, linestyle=(0, (4, 5)))
    ax.axhline(y_avg, color=style.reference, linewidth=1.1, alpha=0.55, linestyle=(0, (4, 5)))


def add_point_labels(ax, points: Iterable[LabelPoint], *, style: ChartStyle = DEFAULT_STYLE) -> None:
    offsets = [(7, 7), (7, -12), (-7, 7), (-7, -12), (10, 0), (-10, 0)]
    for index, point in enumerate(points):
        dx, dy = offsets[index % len(offsets)]
        ax.annotate(
            point.label,
            xy=(point.x, point.y),
            xytext=(dx, dy),
            textcoords="offset points",
            ha="left" if dx >= 0 else "right",
            va="bottom" if dy >= 0 else "top",
            fontsize=9.5,
            fontweight="bold",
            color=style.text,
            arrowprops={
                "arrowstyle": "-",
                "color": style.grid,
                "alpha": 0.75,
                "linewidth": 0.8,
                "shrinkA": 0,
                "shrinkB": 4,
            },
        )


def add_subtle_quadrants(ax, *, x_avg: float, y_avg: float, style: ChartStyle = DEFAULT_STYLE) -> None:
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()
    labels = [
        ("More YAC, more efficient", (x_avg + x_max) / 2, y_avg + (y_max - y_avg) * 0.88),
        ("More YAC, less efficient", (x_avg + x_max) / 2, y_min + (y_avg - y_min) * 0.10),
        ("Less YAC, more efficient", x_min + (x_avg - x_min) * 0.08, y_avg + (y_max - y_avg) * 0.88),
        ("Less YAC, less efficient", x_min + (x_avg - x_min) * 0.08, y_min + (y_avg - y_min) * 0.10),
    ]
    for text, x, y in labels:
        ax.text(x, y, text, color=style.muted_text, fontsize=9.5, alpha=0.58, ha="center" if x > x_avg else "left")


def padded_limits(values: pd.Series, *, min_pad: float = 0.25) -> tuple[float, float]:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return 0.0, 1.0
    low = float(numeric.min())
    high = float(numeric.max())
    spread = max(high - low, min_pad)
    pad = max(spread * 0.10, min_pad)
    return low - pad, high + pad
