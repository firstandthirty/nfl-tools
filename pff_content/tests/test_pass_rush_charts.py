from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd
from matplotlib import pyplot as plt
from matplotlib.ticker import PercentFormatter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pff_content.charts.pass_rush import (
    add_pass_rush_ranks,
    format_rate_axes,
    pass_rush_win_rate_vs_pressure_rate_dataframe,
    select_pass_rush_labels,
)


class PassRushChartTests(unittest.TestCase):
    def fixture(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "player_name": "Alpha",
                    "team": "AAA",
                    "position": "ED",
                    "season": 2026,
                    "draft_season": 2026,
                    "pass_rush_snaps": 20,
                    "pass_rush_opp": 20,
                    "total_pressures": 5,
                    "sacks": 1,
                    "hits": 1,
                    "hurries": 3,
                    "pass_rush_wins": 8,
                    "pass_rush_win_rate": 40.0,
                    "pass_rush_productivity": 15.0,
                    "pressure_rate": 0.25,
                },
                {
                    "player_name": "Beta",
                    "team": "BBB",
                    "position": "DI",
                    "season": 2026,
                    "draft_season": 2025,
                    "pass_rush_snaps": 15,
                    "pass_rush_opp": 15,
                    "total_pressures": 6,
                    "sacks": 0,
                    "hits": 2,
                    "hurries": 4,
                    "pass_rush_wins": 3,
                    "pass_rush_win_rate": 20.0,
                    "pass_rush_productivity": 18.0,
                    "pressure_rate": 0.4,
                },
                {
                    "player_name": "Few",
                    "team": "CCC",
                    "position": "LB",
                    "season": 2026,
                    "draft_season": 2026,
                    "pass_rush_snaps": 14,
                    "pass_rush_opp": 14,
                    "total_pressures": 7,
                    "sacks": 2,
                    "hits": 1,
                    "hurries": 4,
                    "pass_rush_wins": 7,
                    "pass_rush_win_rate": 50.0,
                    "pass_rush_productivity": 20.0,
                    "pressure_rate": 0.5,
                },
            ]
        )

    def test_pressure_rate_calculation_and_native_win_rate_ratio(self) -> None:
        out = pass_rush_win_rate_vs_pressure_rate_dataframe(self.fixture(), min_pass_rush_snaps=15)
        alpha = out[out["player_name"].eq("Alpha")].iloc[0]
        self.assertAlmostEqual(alpha["pressure_rate"], 0.25)
        self.assertAlmostEqual(alpha["pass_rush_win_rate"], 0.40)
        self.assertAlmostEqual(alpha["pass_rush_win_rate_derived"], 0.40)
        self.assertAlmostEqual(alpha["pass_rush_win_rate_discrepancy"], 0.0)

    def test_15_pass_rush_snap_qualifier(self) -> None:
        out = pass_rush_win_rate_vs_pressure_rate_dataframe(self.fixture(), min_pass_rush_snaps=15)
        self.assertEqual(set(out["player_name"]), {"Alpha", "Beta"})

    def test_rookie_handling_from_draft_season(self) -> None:
        out = pass_rush_win_rate_vs_pressure_rate_dataframe(self.fixture(), min_pass_rush_snaps=15)
        alpha = out[out["player_name"].eq("Alpha")].iloc[0]
        beta = out[out["player_name"].eq("Beta")].iloc[0]
        self.assertTrue(bool(alpha["rookie"]))
        self.assertFalse(bool(beta["rookie"]))

    def test_percentage_formatting(self) -> None:
        _, ax = plt.subplots()
        format_rate_axes(ax)
        self.assertIsInstance(ax.xaxis.get_major_formatter(), PercentFormatter)
        self.assertIsInstance(ax.yaxis.get_major_formatter(), PercentFormatter)
        plt.close(ax.figure)

    def test_rank_direction_and_rank_discrepancy(self) -> None:
        out = pass_rush_win_rate_vs_pressure_rate_dataframe(self.fixture(), min_pass_rush_snaps=15)
        ranked = add_pass_rush_ranks(out)
        alpha = ranked[ranked["player_name"].eq("Alpha")].iloc[0]
        beta = ranked[ranked["player_name"].eq("Beta")].iloc[0]
        self.assertEqual(int(alpha["win_rate_rank"]), 1)
        self.assertEqual(int(alpha["pressure_rate_rank"]), 2)
        self.assertEqual(int(alpha["rank_difference"]), -1)
        self.assertEqual(int(beta["win_rate_rank"]), 2)
        self.assertEqual(int(beta["pressure_rate_rank"]), 1)
        self.assertEqual(int(beta["rank_difference"]), 1)

    def test_label_selection_is_capped_and_deduplicated(self) -> None:
        rows = []
        for i in range(12):
            snaps = 20 + i
            wins = 12 - i if i < 10 else 1
            pressures = i + 1
            rows.append(
                {
                    "player_name": f"Rusher {i}",
                    "team": "T",
                    "position": "ED" if i % 2 else "DI",
                    "pass_rush_snaps": snaps,
                    "pass_rush_opp": snaps,
                    "total_pressures": pressures,
                    "sacks": min(pressures, 2),
                    "hits": 1,
                    "hurries": max(pressures - 3, 0),
                    "pass_rush_wins": wins,
                    "pass_rush_win_rate": wins / snaps * 100,
                    "pass_rush_productivity": 10.0,
                    "pressure_rate": pressures / snaps,
                    "rookie": False,
                }
            )
        out = pass_rush_win_rate_vs_pressure_rate_dataframe(pd.DataFrame(rows), min_pass_rush_snaps=15)
        selection = select_pass_rush_labels(out, max_labels=8)
        self.assertLessEqual(len(selection.labels), 8)
        self.assertEqual(len({label.label for label in selection.labels}), len(selection.labels))
        self.assertTrue(selection.reasons)


if __name__ == "__main__":
    unittest.main()
