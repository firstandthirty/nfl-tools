from __future__ import annotations

from pathlib import Path

import pandas as pd


def save_charts(output_dir: Path, slices: dict[str, pd.DataFrame], calibration: pd.DataFrame) -> list[str]:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return ["matplotlib is not installed; charts were skipped."]
    chart_dir = output_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    for dimension in ["side", "line_bucket", "verified_edge_bucket", "probability_bucket"]:
        table = slices.get(dimension)
        if table is None or table.empty:
            continue
        plot = table.sort_values("roi")
        fig, ax = plt.subplots(figsize=(9, max(4, len(plot) * 0.42)))
        ax.barh(plot[dimension].astype(str), plot["roi"] * 100)
        ax.axvline(0, linewidth=1)
        ax.set_xlabel("ROI (%)")
        ax.set_ylabel(dimension.replace("_", " ").title())
        ax.set_title(f"ROI by {dimension.replace('_', ' ').title()}")
        fig.tight_layout()
        fig.savefig(chart_dir / f"roi_by_{dimension}.png", dpi=150)
        plt.close(fig)
    if not calibration.empty:
        fig, ax = plt.subplots(figsize=(7, 6))
        ax.plot(calibration["avg_predicted_probability"], calibration["actual_win_rate"], marker="o")
        ax.plot([0, 1], [0, 1], linestyle="--")
        ax.set_xlabel("Average predicted probability")
        ax.set_ylabel("Actual win rate")
        ax.set_title("Probability Calibration")
        fig.tight_layout()
        fig.savefig(chart_dir / "calibration_probability.png", dpi=150)
        plt.close(fig)
    return []

