from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from matplotlib import pyplot as plt
from matplotlib.ticker import PercentFormatter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pff_content.charts.coverage import coverage_targets_rating_stats, coverage_targets_vs_passer_rating_dataframe, select_coverage_highlights
from pff_content.charts.qbs import (
    qb_pressure_rate_vs_time_to_throw_dataframe,
    qb_pressure_ttt_stats,
    qb_twp_vs_interceptions_dataframe,
    select_qb_pressure_ttt_highlights,
)
from pff_content.charts.receiving import (
    add_receiving_ranks,
    format_tprr_axis,
    receiving_tprr_vs_yprr_dataframe,
    select_receiving_labels,
)
from pff_content.charts.rushing import (
    add_before_after_contrasts,
    before_after_quadrant_counts,
    before_after_reference_stats,
    rb_before_vs_after_contact_dataframe,
    rb_ypa_vs_yaco_dataframe,
    select_before_after_labels,
    select_rb_labels,
)
from pff_content.charts.style import save_png


class ChartTests(unittest.TestCase):
    def test_save_png_can_overwrite_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chart.png"
            fig1, ax1 = plt.subplots()
            ax1.plot([1, 2], [1, 2])
            save_png(fig1, path)
            first_size = path.stat().st_size

            fig2, ax2 = plt.subplots()
            ax2.plot([1, 2], [2, 1])
            save_png(fig2, path)
            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, 0)
            self.assertGreater(first_size, 0)

    def test_rb_chart_dataframe_filters_to_attempt_qualifiers(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": "A", "team": "AAA", "position": "HB", "attempts": 8, "yards": 40, "yards_after_contact_per_attempt": 3.0, "yards_per_carry": 5.0},
                {"player_name": "B", "team": "BBB", "position": "HB", "attempts": 7, "yards": 70, "yards_after_contact_per_attempt": 5.0, "yards_per_carry": 10.0},
                {"player_name": "C", "team": "CCC", "position": "QB", "attempts": 10, "yards": 90, "yards_after_contact_per_attempt": 6.0, "yards_per_carry": 9.0},
            ]
        )
        out = rb_ypa_vs_yaco_dataframe(df, min_attempts=8)
        self.assertEqual(out["player_name"].tolist(), ["A"])
        self.assertIn("attempts", out.columns)

    def test_label_selection_is_capped_and_unique(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": f"RB {i}", "team": "T", "attempts": 8 + i, "yards": 40 + i, "yards_after_contact_per_attempt": 1.0 + i, "yards_per_carry": 2.0 + i / 2}
                for i in range(12)
            ]
        )
        labels = select_rb_labels(df, x_col="yards_after_contact_per_attempt", y_col="yards_per_carry", max_labels=5)
        self.assertEqual(len(labels), 5)
        self.assertEqual(len({label.label for label in labels}), 5)

    def test_before_after_dataframe_calculates_per_attempt_values(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": "A", "team": "AAA", "position": "HB", "attempts": 10, "yards": 50, "yards_per_carry": 5.0, "yards_after_contact": 32, "rookie": False},
            ]
        )
        out = rb_before_vs_after_contact_dataframe(df, min_attempts=8)
        self.assertEqual(out.loc[0, "rushing_yards"], 50)
        self.assertEqual(out.loc[0, "yards_before_contact"], 18)
        self.assertAlmostEqual(out.loc[0, "yards_before_contact_per_attempt"], 1.8)
        self.assertAlmostEqual(out.loc[0, "yards_after_contact_per_attempt"], 3.2)

    def test_before_after_dataframe_preserves_negative_before_contact(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": "A", "team": "AAA", "position": "RB", "attempts": 10, "yards": 20, "yards_per_carry": 2.0, "yards_after_contact": 25, "rookie": True},
            ]
        )
        out = rb_before_vs_after_contact_dataframe(df, min_attempts=8)
        self.assertEqual(out.loc[0, "yards_before_contact"], -5)
        self.assertAlmostEqual(out.loc[0, "yards_before_contact_per_attempt"], -0.5)

    def test_before_after_dataframe_filters_to_actual_rb_positions(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": "HB", "team": "AAA", "position": "HB", "attempts": 8, "yards": 40, "yards_per_carry": 5.0, "yards_after_contact": 30},
                {"player_name": "QB", "team": "BBB", "position": "QB", "attempts": 12, "yards": 84, "yards_per_carry": 7.0, "yards_after_contact": 40},
                {"player_name": "Few", "team": "CCC", "position": "FB", "attempts": 7, "yards": 21, "yards_per_carry": 3.0, "yards_after_contact": 14},
            ]
        )
        out = rb_before_vs_after_contact_dataframe(df, min_attempts=8)
        self.assertEqual(out["player_name"].tolist(), ["HB"])

    def test_before_after_dataframe_fails_when_ypc_does_not_reconcile(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": "A", "team": "AAA", "position": "HB", "attempts": 10, "yards": 50, "yards_per_carry": 4.9, "yards_after_contact": 32},
            ]
        )
        with self.assertRaises(ValueError):
            rb_before_vs_after_contact_dataframe(df, min_attempts=8)

    def test_before_after_reference_stats_and_quadrants(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": "A", "team": "AAA", "position": "HB", "attempts": 10, "yards": 50, "yards_per_carry": 5.0, "yards_after_contact": 30},
                {"player_name": "B", "team": "BBB", "position": "HB", "attempts": 10, "yards": 20, "yards_per_carry": 2.0, "yards_after_contact": 10},
                {"player_name": "C", "team": "CCC", "position": "HB", "attempts": 10, "yards": 40, "yards_per_carry": 4.0, "yards_after_contact": 10},
            ]
        )
        out = rb_before_vs_after_contact_dataframe(df, min_attempts=8)
        stats = before_after_reference_stats(out)
        self.assertAlmostEqual(stats["mean_before"], 2.0)
        self.assertAlmostEqual(stats["median_before"], 2.0)
        self.assertAlmostEqual(stats["mean_after"], 5 / 3)
        self.assertAlmostEqual(stats["median_after"], 1.0)
        counts = before_after_quadrant_counts(out, x_ref=stats["mean_before"], y_ref=stats["mean_after"])
        self.assertEqual(counts, {"upper_right": 0, "upper_left": 1, "lower_right": 1, "lower_left": 1})

    def test_contrasts_and_label_selection_are_deduplicated_with_reasons(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": "High Before", "team": "AAA", "position": "HB", "attempts": 10, "yards": 70, "yards_per_carry": 7.0, "yards_after_contact": 10},
                {"player_name": "High After", "team": "BBB", "position": "HB", "attempts": 10, "yards": 70, "yards_per_carry": 7.0, "yards_after_contact": 65},
                {"player_name": "Low Before", "team": "CCC", "position": "HB", "attempts": 10, "yards": 20, "yards_per_carry": 2.0, "yards_after_contact": 25},
                {"player_name": "Low After", "team": "DDD", "position": "HB", "attempts": 10, "yards": 20, "yards_per_carry": 2.0, "yards_after_contact": 0},
                {"player_name": "Middle", "team": "EEE", "position": "HB", "attempts": 10, "yards": 40, "yards_per_carry": 4.0, "yards_after_contact": 20},
            ]
        )
        out = rb_before_vs_after_contact_dataframe(df, min_attempts=8)
        contrasts = add_before_after_contrasts(out)
        self.assertAlmostEqual(contrasts.loc[contrasts["player_name"].eq("High After"), "after_minus_before"].iloc[0], 6.0)
        selection = select_before_after_labels(out, max_labels=4)
        self.assertEqual(len(selection.labels), 4)
        self.assertEqual(len({label.label for label in selection.labels}), 4)
        self.assertIn("highest before-contact yards/attempt", selection.reasons["High Before"])
        self.assertIn("highest after-contact yards/attempt", selection.reasons["High After"])

    def receiving_fixture(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"player_name": "Alpha", "team": "AAA", "position": "WR", "routes": 20, "targets": 10, "receptions": 6, "yards": 100, "yprr": 5.0, "avg_depth_of_target": 12, "draft_season": 2026, "season": 2026},
                {"player_name": "Beta", "team": "BBB", "position": "TE", "routes": 15, "targets": 3, "receptions": 2, "yards": 60, "yprr": 4.0, "avg_depth_of_target": 9, "draft_season": 2025, "season": 2026},
                {"player_name": "Gamma", "team": "CCC", "position": "WR", "routes": 14, "targets": 7, "receptions": 4, "yards": 70, "yprr": 5.0, "avg_depth_of_target": 10, "draft_season": 2026, "season": 2026},
                {"player_name": "Back", "team": "DDD", "position": "HB", "routes": 30, "targets": 15, "receptions": 10, "yards": 120, "yprr": 4.0, "avg_depth_of_target": 1, "draft_season": 2026, "season": 2026},
            ]
        )

    def test_receiving_dataframe_calculates_tprr_and_preserves_native_yprr(self) -> None:
        out = receiving_tprr_vs_yprr_dataframe(self.receiving_fixture(), min_routes=15)
        alpha = out[out["player_name"].eq("Alpha")].iloc[0]
        self.assertAlmostEqual(alpha["targets_per_route_run"], 0.5)
        self.assertAlmostEqual(alpha["yards_per_route_run"], 5.0)
        self.assertAlmostEqual(alpha["yards_per_route_run_derived"], 5.0)
        self.assertAlmostEqual(alpha["yards_per_route_run_discrepancy"], 0.0)

    def test_receiving_dataframe_applies_15_route_wr_te_qualifier(self) -> None:
        out = receiving_tprr_vs_yprr_dataframe(self.receiving_fixture(), min_routes=15)
        self.assertEqual(set(out["player_name"]), {"Alpha", "Beta"})

    def test_receiving_yprr_reconciliation_failure(self) -> None:
        df = self.receiving_fixture()
        df.loc[0, "yprr"] = 4.5
        with self.assertRaises(ValueError):
            receiving_tprr_vs_yprr_dataframe(df, min_routes=15)

    def test_receiving_rookie_handling_from_draft_season(self) -> None:
        out = receiving_tprr_vs_yprr_dataframe(self.receiving_fixture().drop(columns=["rookie"], errors="ignore"), min_routes=15)
        alpha = out[out["player_name"].eq("Alpha")].iloc[0]
        beta = out[out["player_name"].eq("Beta")].iloc[0]
        self.assertTrue(bool(alpha["rookie"]))
        self.assertFalse(bool(beta["rookie"]))

    def test_percentage_formatting(self) -> None:
        _, ax = plt.subplots()
        format_tprr_axis(ax)
        self.assertIsInstance(ax.xaxis.get_major_formatter(), PercentFormatter)
        plt.close(ax.figure)

    def test_receiving_rank_direction_and_discrepancy(self) -> None:
        out = receiving_tprr_vs_yprr_dataframe(self.receiving_fixture(), min_routes=15)
        ranked = add_receiving_ranks(out)
        alpha = ranked[ranked["player_name"].eq("Alpha")].iloc[0]
        beta = ranked[ranked["player_name"].eq("Beta")].iloc[0]
        self.assertEqual(int(alpha["tprr_rank"]), 1)
        self.assertEqual(int(alpha["yprr_rank"]), 1)
        self.assertEqual(int(beta["tprr_rank"]), 2)
        self.assertEqual(int(beta["yprr_rank"]), 2)
        self.assertEqual(int(alpha["rank_difference"]), 0)

    def test_receiving_label_selection_is_capped_and_deduplicated(self) -> None:
        rows = []
        for i in range(12):
            routes = 20
            targets = 12 - i
            yards = 20 + i * 20
            rows.append(
                {
                    "player_name": f"Receiver {i}",
                    "team": "T",
                    "position": "WR" if i % 2 else "TE",
                    "routes": routes,
                    "targets": targets,
                    "receptions": min(targets, 5),
                    "yards": yards,
                    "yprr": yards / routes,
                    "avg_depth_of_target": 8,
                    "rookie": False,
                }
            )
        out = receiving_tprr_vs_yprr_dataframe(pd.DataFrame(rows), min_routes=15)
        selection = select_receiving_labels(out, max_labels=8)
        self.assertLessEqual(len(selection.labels), 8)
        self.assertEqual(len({label.label for label in selection.labels}), len(selection.labels))
        self.assertTrue(selection.reasons)

    def test_qb_pressure_ttt_dataframe_uses_20_dropback_qualifier(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": "QB One", "team": "A", "opponent": "B", "dropbacks": 20, "attempts": 18, "def_gen_pressures": 10, "pressure_rate_faced": 0.5, "avg_time_to_throw": 2.5, "sacks": 1, "turnover_worthy_plays": 2, "interceptions": 0},
                {"player_name": "QB Two", "team": "C", "opponent": "D", "dropbacks": 19, "attempts": 16, "def_gen_pressures": 12, "pressure_rate_faced": 0.63, "avg_time_to_throw": 3.1, "sacks": 2, "turnover_worthy_plays": 0, "interceptions": 1},
            ]
        )
        out = qb_pressure_rate_vs_time_to_throw_dataframe(df)
        self.assertEqual(out["player_name"].tolist(), ["QB One"])
        self.assertAlmostEqual(out.loc[0, "pressure_rate_faced"], 0.5)

    def test_qb_pressure_ttt_stats_and_highlights(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": f"QB {i}", "team": "T", "dropbacks": 25 + i, "pressure_rate_faced": 0.1 + i / 100, "avg_time_to_throw": 2.2 + i / 20}
                for i in range(8)
            ]
        )
        out = qb_pressure_rate_vs_time_to_throw_dataframe(df)
        stats = qb_pressure_ttt_stats(out)
        self.assertEqual(stats.qualified_count, 8)
        self.assertEqual(sum(stats.quadrant_counts.values()), 8)
        self.assertTrue(select_qb_pressure_ttt_highlights(out))

    def test_coverage_dataframe_uses_snap_and_target_qualifier_and_fields(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": "CB One", "team": "A", "opponent": "B", "position": "CB", "coverage_snaps": 20, "targets": 4, "receptions": 1, "yards": 9, "passer_rating_when_targeted": 39.6, "forced_incompletes": 1, "forced_incompletion_rate": 0.25},
                {"player_name": "CB Two", "team": "C", "opponent": "D", "position": "CB", "coverage_snaps": 20, "targets": 3, "receptions": 1, "yards": 9, "passer_rating_when_targeted": 39.6, "forced_incompletes": 1, "forced_incompletion_rate": 0.33},
            ]
        )
        out = coverage_targets_vs_passer_rating_dataframe(df)
        self.assertEqual(out["player_name"].tolist(), ["CB One"])
        self.assertIn("receptions_allowed", out.columns)
        self.assertIn("yards_allowed", out.columns)

    def test_coverage_stats_use_median_target_reference(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": f"CB {i}", "team": "T", "position": "CB", "coverage_snaps": 20 + i, "targets": targets, "receptions": 1, "yards": 10, "passer_rating_when_targeted": 50 + i, "forced_incompletes": i % 2}
                for i, targets in enumerate([4, 4, 5, 12])
            ]
        )
        out = coverage_targets_vs_passer_rating_dataframe(df)
        stats = coverage_targets_rating_stats(out)
        self.assertEqual(stats.target_reference_type, "median")
        self.assertAlmostEqual(stats.target_reference, 4.5)
        self.assertTrue(select_coverage_highlights(out))

    def test_twp_minus_int_and_deterministic_sorting(self) -> None:
        df = pd.DataFrame(
            [
                {"player_name": "Beta", "team": "B", "opponent": "X", "dropbacks": 30, "attempts": 25, "turnover_worthy_plays": 3, "interceptions": 0},
                {"player_name": "Alpha", "team": "A", "opponent": "X", "dropbacks": 30, "attempts": 25, "turnover_worthy_plays": 0, "interceptions": 3},
                {"player_name": "Gamma", "team": "G", "opponent": "X", "dropbacks": 19, "attempts": 18, "turnover_worthy_plays": 5, "interceptions": 0},
            ]
        )
        out = qb_twp_vs_interceptions_dataframe(df)
        self.assertEqual(out["player_name"].tolist(), ["Alpha", "Beta"])
        self.assertEqual(out.loc[out["player_name"].eq("Beta"), "twp_minus_int"].iloc[0], 3)


if __name__ == "__main__":
    unittest.main()
