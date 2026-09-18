from __future__ import annotations

import sys
import unittest
from pathlib import Path

from matplotlib import pyplot as plt
from matplotlib.transforms import Bbox

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pff_content.charts.dense_labels import (
    CANDIDATE_OFFSETS,
    DenseLabelPoint,
    abbreviate_player_name,
    add_dense_point_labels,
    bbox_inside,
    bboxes_overlap,
    clear_label_stats,
    label_stats_report,
    ordered_dense_labels,
    record_label_stats,
)


class DenseLabelTests(unittest.TestCase):
    def test_player_name_abbreviation(self) -> None:
        self.assertEqual(abbreviate_player_name("Aidan Hutchinson"), "A. Hutchinson")
        self.assertEqual(abbreviate_player_name("Maxx Crosby"), "M. Crosby")
        self.assertEqual(abbreviate_player_name("Amon-Ra St. Brown"), "A. St. Brown")

    def test_suffix_preservation(self) -> None:
        self.assertEqual(abbreviate_player_name("Kenneth Walker III"), "K. Walker III")
        self.assertEqual(abbreviate_player_name("Travis Etienne Jr."), "T. Etienne Jr.")

    def test_hyphenated_surname(self) -> None:
        self.assertEqual(abbreviate_player_name("Jaxon Smith-Njigba"), "J. Smith-Njigba")
        self.assertEqual(abbreviate_player_name("Marquez Valdes-Scantling"), "M. Valdes-Scantling")

    def test_candidate_label_positions_exist(self) -> None:
        names = {candidate.name for candidate in CANDIDATE_OFFSETS}
        self.assertTrue({"right", "left", "upper-right", "lower-left", "above", "below"}.issubset(names))

    def test_collision_detection(self) -> None:
        first = Bbox.from_extents(0, 0, 10, 10)
        second = Bbox.from_extents(9, 9, 20, 20)
        third = Bbox.from_extents(11, 11, 20, 20)
        self.assertTrue(bboxes_overlap(first, second))
        self.assertFalse(bboxes_overlap(first, third))

    def test_bbox_inside_axes_bounds(self) -> None:
        outer = Bbox.from_extents(0, 0, 100, 100)
        self.assertTrue(bbox_inside(Bbox.from_extents(5, 5, 90, 90), outer))
        self.assertFalse(bbox_inside(Bbox.from_extents(-1, 5, 90, 90), outer))

    def test_highlighted_label_priority_and_deterministic_order(self) -> None:
        points = [
            DenseLabelPoint(label="B", player_name="Beta Two", team="B", x=2, y=2, priority=1),
            DenseLabelPoint(label="A", player_name="Alpha One", team="A", x=1, y=1, highlighted=True, priority=99),
            DenseLabelPoint(label="C", player_name="Charlie Three", team="C", x=3, y=3, priority=0),
        ]
        first = ordered_dense_labels(points)
        second = ordered_dense_labels(points)
        self.assertEqual([point.label for point in first], ["A", "C", "B"])
        self.assertEqual([point.label for point in first], [point.label for point in second])

    def test_labels_remain_within_axes_bounds(self) -> None:
        fig, ax = plt.subplots(figsize=(5, 3))
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.scatter([0.05, 0.95], [0.05, 0.95])
        stats = add_dense_point_labels(
            ax,
            [
                DenseLabelPoint(label="A", player_name="Alpha One", team="AAA", x=0.05, y=0.05),
                DenseLabelPoint(label="B", player_name="Beta Two", team="BBB", x=0.95, y=0.95),
            ],
        )
        self.assertEqual(stats.total_points, 2)
        self.assertEqual(stats.labels_attempted, 2)
        self.assertGreaterEqual(stats.labels_placed, 1)
        plt.close(fig)



    def test_highlight_label_is_not_suppressed_by_dense_collision(self) -> None:
        fig, ax = plt.subplots(figsize=(5, 3))
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        points = [
            DenseLabelPoint(label="A", player_name="Alpha One", team="AAA", x=0.5, y=0.5, highlighted=True),
            DenseLabelPoint(label="B", player_name="Beta Two", team="BBB", x=0.5, y=0.5),
            DenseLabelPoint(label="C", player_name="Charlie Three", team="CCC", x=0.5, y=0.5),
        ]
        stats = add_dense_point_labels(ax, points)
        self.assertEqual(stats.highlighted_players, 1)
        self.assertEqual(stats.highlight_labels_placed, 1)
        plt.close(fig)

    def test_reserved_area_avoidance_can_suppress_standard_label(self) -> None:
        fig, ax = plt.subplots(figsize=(5, 3))
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.text(0.5, 0.5, "Reserved Area", ha="center", va="center")
        reserved = [text.get_window_extent(renderer=fig.canvas.get_renderer()).expanded(6, 6) for text in ax.texts]
        stats = add_dense_point_labels(
            ax,
            [DenseLabelPoint(label="A", player_name="Alpha One", team="AAA", x=0.5, y=0.5)],
            reserved_bboxes=reserved,
        )
        self.assertLessEqual(stats.labels_placed, 1)
        plt.close(fig)

    def test_recorded_label_stats_are_deterministic(self) -> None:
        clear_label_stats()
        fig, ax = plt.subplots(figsize=(5, 3))
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        stats = add_dense_point_labels(ax, [DenseLabelPoint(label="A", player_name="Alpha One", team="AAA", x=0.25, y=0.25)])
        record_label_stats("chart", stats)
        first = label_stats_report()
        clear_label_stats()
        record_label_stats("chart", stats)
        second = label_stats_report()
        self.assertEqual(first, second)
        plt.close(fig)

if __name__ == "__main__":
    unittest.main()



