from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Sequence

from matplotlib.font_manager import FontProperties
from matplotlib.transforms import Bbox

from .scatter import LabelPoint
from .style import DEFAULT_STYLE, ChartStyle

SUFFIXES = {"Jr.", "Sr.", "II", "III", "IV", "V"}
STANDARD_LABEL_FONT_SIZE = 6.1
HIGHLIGHT_LABEL_FONT_SIZE = 7.5
LAST_LABEL_PLACEMENT_STATS: dict[str, "LabelPlacementStats"] = {}


@dataclass(frozen=True)
class DenseLabelPoint(LabelPoint):
    player_name: str = ""
    team: str = ""
    highlighted: bool = False
    priority: int = 100


@dataclass(frozen=True)
class LabelPlacementStats:
    total_points: int
    labels_attempted: int
    labels_placed: int
    labels_suppressed: int
    highlighted_players: int
    highlight_labels_placed: int
    standard_labels_placed: int


@dataclass(frozen=True)
class CandidateOffset:
    name: str
    dx: float
    dy: float
    ha: str
    va: str


CANDIDATE_OFFSETS: tuple[CandidateOffset, ...] = (
    CandidateOffset("right", 3, 0, "left", "center"),
    CandidateOffset("left", -3, 0, "right", "center"),
    CandidateOffset("upper-right", 3, 3, "left", "bottom"),
    CandidateOffset("upper-left", -3, 3, "right", "bottom"),
    CandidateOffset("lower-right", 3, -3, "left", "top"),
    CandidateOffset("lower-left", -3, -3, "right", "top"),
    CandidateOffset("above", 0, 4, "center", "bottom"),
    CandidateOffset("below", 0, -4, "center", "top"),
    CandidateOffset("far-right", 8, 0, "left", "center"),
    CandidateOffset("far-left", -8, 0, "right", "center"),
    CandidateOffset("far-upper-right", 8, 8, "left", "bottom"),
    CandidateOffset("far-upper-left", -8, 8, "right", "bottom"),
    CandidateOffset("far-lower-right", 8, -8, "left", "top"),
    CandidateOffset("far-lower-left", -8, -8, "right", "top"),
)


def clear_label_stats() -> None:
    LAST_LABEL_PLACEMENT_STATS.clear()


def record_label_stats(chart_name: str, stats: LabelPlacementStats) -> None:
    LAST_LABEL_PLACEMENT_STATS[chart_name] = stats


def label_stats_report() -> dict[str, dict[str, int]]:
    return {name: asdict(stats) for name, stats in LAST_LABEL_PLACEMENT_STATS.items()}


def abbreviate_player_name(name: str) -> str:
    parts = [part for part in str(name).strip().split() if part]
    if len(parts) <= 1:
        return str(name).strip()
    suffix = ""
    if parts[-1] in SUFFIXES:
        suffix = parts.pop()
    first = parts[0]
    surname = " ".join(parts[1:])
    abbreviated = f"{first[0]}. {surname}"
    if suffix:
        abbreviated = f"{abbreviated} {suffix}"
    return abbreviated


def label_text_for_point(point: DenseLabelPoint, *, include_standard_team: bool = False) -> str:
    base = abbreviate_player_name(point.player_name or point.label)
    if point.highlighted or include_standard_team:
        return f"{base} ({point.team})" if point.team else base
    return base


def ordered_dense_labels(points: Sequence[DenseLabelPoint], *, max_standard_labels: int | None = None) -> list[DenseLabelPoint]:
    ordered = sorted(points, key=lambda point: (not point.highlighted, point.priority, point.label))
    if max_standard_labels is None:
        return ordered
    highlights = [point for point in ordered if point.highlighted]
    standards = [point for point in ordered if not point.highlighted][:max_standard_labels]
    return highlights + standards


def dense_label_points_from_dataframe(
    df,
    *,
    x_col: str,
    y_col: str,
    highlight_names: set[str],
    volume_col: str,
) -> list[DenseLabelPoint]:
    volume_rank = df[volume_col].rank(method="first", ascending=False).astype(int).to_dict()
    points: list[DenseLabelPoint] = []
    for index, row in df.iterrows():
        name = str(row["player_name"])
        highlighted = name in highlight_names
        points.append(
            DenseLabelPoint(
                label=name,
                player_name=name,
                team=str(row["team"]),
                x=float(row[x_col]),
                y=float(row[y_col]),
                highlighted=highlighted,
                priority=0 if highlighted else int(volume_rank[index]),
            )
        )
    return points


def existing_text_bboxes(ax, *, pad_px: float = 2.0) -> list[Bbox]:
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    bboxes: list[Bbox] = []
    for text in ax.texts:
        if not text.get_visible():
            continue
        bbox = text.get_window_extent(renderer=renderer)
        bboxes.append(Bbox.from_extents(bbox.x0 - pad_px, bbox.y0 - pad_px, bbox.x1 + pad_px, bbox.y1 + pad_px))
    return bboxes


def _bbox_for_text(
    ax,
    *,
    x_px: float,
    y_px: float,
    text: str,
    font_size: float,
    weight: str,
    offset: CandidateOffset,
    pad_px: float,
) -> Bbox:
    fig = ax.figure
    renderer = fig.canvas.get_renderer()
    props = FontProperties(family="DejaVu Sans", size=font_size, weight=weight)
    width, height, _ = renderer.get_text_width_height_descent(text, props, ismath=False)
    dx = offset.dx * fig.dpi / 72.0
    dy = offset.dy * fig.dpi / 72.0
    anchor_x = x_px + dx
    anchor_y = y_px + dy

    if offset.ha == "left":
        x0, x1 = anchor_x, anchor_x + width
    elif offset.ha == "right":
        x0, x1 = anchor_x - width, anchor_x
    else:
        x0, x1 = anchor_x - width / 2, anchor_x + width / 2

    if offset.va == "bottom":
        y0, y1 = anchor_y, anchor_y + height
    elif offset.va == "top":
        y0, y1 = anchor_y - height, anchor_y
    else:
        y0, y1 = anchor_y - height / 2, anchor_y + height / 2

    return Bbox.from_extents(x0 - pad_px, y0 - pad_px, x1 + pad_px, y1 + pad_px)


def bboxes_overlap(first: Bbox, second: Bbox, *, padding: float = 0.0) -> bool:
    expanded = Bbox.from_extents(first.x0 - padding, first.y0 - padding, first.x1 + padding, first.y1 + padding)
    return expanded.overlaps(second)


def bbox_inside(inner: Bbox, outer: Bbox) -> bool:
    return inner.x0 >= outer.x0 and inner.x1 <= outer.x1 and inner.y0 >= outer.y0 and inner.y1 <= outer.y1


def _bbox_covers_other_point(bbox: Bbox, point_pixels: Sequence[tuple[float, float]], own_index: int, *, padding: float = 2.0) -> bool:
    expanded = Bbox.from_extents(bbox.x0 - padding, bbox.y0 - padding, bbox.x1 + padding, bbox.y1 + padding)
    for index, (x_px, y_px) in enumerate(point_pixels):
        if index == own_index:
            continue
        if expanded.contains(x_px, y_px):
            return True
    return False


def _choose_fallback_for_highlight(
    ax,
    *,
    x_px: float,
    y_px: float,
    text: str,
    font_size: float,
    weight: str,
    axes_bbox: Bbox,
) -> tuple[CandidateOffset, Bbox] | None:
    for offset in CANDIDATE_OFFSETS:
        bbox = _bbox_for_text(ax, x_px=x_px, y_px=y_px, text=text, font_size=font_size, weight=weight, offset=offset, pad_px=0.8)
        if bbox_inside(bbox, axes_bbox):
            return offset, bbox
    return None


def add_dense_point_labels(
    ax,
    points: Sequence[DenseLabelPoint],
    *,
    style: ChartStyle = DEFAULT_STYLE,
    include_standard_team: bool = False,
    standard_font_size: float = STANDARD_LABEL_FONT_SIZE,
    highlight_font_size: float = HIGHLIGHT_LABEL_FONT_SIZE,
    max_standard_labels: int | None = None,
    reserved_bboxes: Sequence[Bbox] = (),
) -> LabelPlacementStats:
    fig = ax.figure
    fig.canvas.draw()
    attempted = ordered_dense_labels(points, max_standard_labels=max_standard_labels)
    point_pixels = [tuple(ax.transData.transform((point.x, point.y))) for point in attempted]
    axes_bbox = ax.get_window_extent().expanded(0.995, 0.985)
    placed_bboxes: list[Bbox] = list(reserved_bboxes)
    player_bboxes: list[Bbox] = []
    placed = 0
    highlight_placed = 0
    standard_placed = 0
    highlighted_players = sum(1 for point in attempted if point.highlighted)

    for index, point in enumerate(attempted):
        text = label_text_for_point(point, include_standard_team=include_standard_team)
        font_size = highlight_font_size if point.highlighted else standard_font_size
        weight = "bold" if point.highlighted else "normal"
        color = style.text if point.highlighted else style.muted_text
        alpha = 0.98 if point.highlighted else 0.82
        x_px, y_px = point_pixels[index]
        chosen: tuple[CandidateOffset, Bbox] | None = None
        for offset in CANDIDATE_OFFSETS:
            bbox = _bbox_for_text(
                ax,
                x_px=x_px,
                y_px=y_px,
                text=text,
                font_size=font_size,
                weight=weight,
                offset=offset,
                pad_px=0.8 if point.highlighted else 0.45,
            )
            if not bbox_inside(bbox, axes_bbox):
                continue
            if any(bboxes_overlap(bbox, existing, padding=0.8) for existing in placed_bboxes):
                continue
            if not point.highlighted and _bbox_covers_other_point(bbox, point_pixels, index, padding=1.5):
                continue
            chosen = (offset, bbox)
            break
        if chosen is None and point.highlighted:
            chosen = _choose_fallback_for_highlight(
                ax,
                x_px=x_px,
                y_px=y_px,
                text=text,
                font_size=font_size,
                weight=weight,
                axes_bbox=axes_bbox,
            )
        if chosen is None:
            continue

        offset, bbox = chosen
        use_arrow = point.highlighted or abs(offset.dx) >= 8 or abs(offset.dy) >= 8
        arrowprops = None
        if use_arrow:
            arrowprops = {
                "arrowstyle": "-",
                "color": style.grid,
                "alpha": 0.58 if point.highlighted else 0.38,
                "linewidth": 0.65 if point.highlighted else 0.45,
                "shrinkA": 0,
                "shrinkB": 3,
            }
        ax.annotate(
            text,
            xy=(point.x, point.y),
            xytext=(offset.dx, offset.dy),
            textcoords="offset points",
            ha=offset.ha,
            va=offset.va,
            fontsize=font_size,
            fontweight=weight,
            color=color,
            alpha=alpha,
            arrowprops=arrowprops,
            zorder=6 if point.highlighted else 5,
        )
        placed_bboxes.append(bbox)
        player_bboxes.append(bbox)
        placed += 1
        if point.highlighted:
            highlight_placed += 1
        else:
            standard_placed += 1

    return LabelPlacementStats(
        total_points=len(points),
        labels_attempted=len(attempted),
        labels_placed=placed,
        labels_suppressed=len(attempted) - placed,
        highlighted_players=highlighted_players,
        highlight_labels_placed=highlight_placed,
        standard_labels_placed=standard_placed,
    )

