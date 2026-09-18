from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from matplotlib import pyplot as plt


@dataclass(frozen=True)
class ChartStyle:
    background: str = "#111820"
    panel: str = "#111820"
    text: str = "#F3F7FA"
    muted_text: str = "#A8B3BD"
    grid: str = "#33414D"
    reference: str = "#E8EEF2"
    accent: str = "#32D2C9"
    accent_secondary: str = "#FFB84D"
    point_edge: str = "#DCE6EC"


DEFAULT_STYLE = ChartStyle()


def apply_theme(style: ChartStyle = DEFAULT_STYLE) -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": style.background,
            "axes.facecolor": style.panel,
            "axes.edgecolor": style.grid,
            "axes.labelcolor": style.text,
            "axes.titlecolor": style.text,
            "xtick.color": style.muted_text,
            "ytick.color": style.muted_text,
            "text.color": style.text,
            "font.family": "DejaVu Sans",
            "font.size": 13,
            "axes.labelsize": 14,
            "xtick.labelsize": 12,
            "ytick.labelsize": 12,
            "savefig.facecolor": style.background,
            "savefig.edgecolor": style.background,
        }
    )


def social_figure(*, width: float = 12.0, height: float = 6.75, style: ChartStyle = DEFAULT_STYLE):
    apply_theme(style)
    fig, ax = plt.subplots(figsize=(width, height), constrained_layout=False)
    fig.patch.set_facecolor(style.background)
    ax.set_facecolor(style.panel)
    return fig, ax


def format_axes(ax, *, style: ChartStyle = DEFAULT_STYLE) -> None:
    ax.grid(True, color=style.grid, alpha=0.35, linewidth=0.8)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(length=0, pad=8)


def add_title_block(fig, *, title: str, subtitle: str, style: ChartStyle = DEFAULT_STYLE) -> None:
    fig.text(0.075, 0.93, title, fontsize=24, fontweight="bold", color=style.text, ha="left", va="top")
    fig.text(0.075, 0.885, subtitle, fontsize=13.5, color=style.muted_text, ha="left", va="top")


def add_footer(fig, *, text: str, style: ChartStyle = DEFAULT_STYLE) -> None:
    fig.text(0.075, 0.035, text, fontsize=10.5, color=style.muted_text, ha="left", va="bottom")


def save_png(fig, path: Path, *, dpi: int = 240) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.stem}.{uuid.uuid4().hex}.tmp.png")
    try:
        fig.savefig(temp_path, dpi=dpi, bbox_inches="tight", pad_inches=0.25)
        fig.canvas.flush_events()
        plt.close(fig)
        os.replace(temp_path, path)
    finally:
        plt.close(fig)
        if temp_path.exists():
            temp_path.unlink()
