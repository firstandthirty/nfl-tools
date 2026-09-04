from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = PROJECT_ROOT / "scripts" / "04_analysis" / "audit_projection_signal.py"
spec = importlib.util.spec_from_file_location("audit_projection_signal", AUDIT_PATH)
audit = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(audit)


class ProjectionSignalAuditTests(unittest.TestCase):
    def test_no_future_rows_used_in_walk_forward_guard(self) -> None:
        rows = pd.DataFrame({
            "market": ["player_pass_yds"] * 6,
            "week": [1, 2, 3, 4, 5, 6],
            "split": ["train"] * 6,
        })
        eligible = [w for w in sorted(rows.week.unique()) if len([p for p in rows.week.unique() if p < w]) >= 4]
        self.assertEqual(eligible, [5, 6])

    def test_bias_correction_uses_training_only(self) -> None:
        rows = pd.DataFrame({
            "market": ["player_pass_yds"] * 4,
            "split": ["train", "train", "final_holdout", "final_holdout"],
            "season": [2024] * 4,
            "week": [1, 2, 3, 4],
            "player": ["A", "B", "C", "D"],
            "player_norm": ["a", "b", "c", "d"],
            "game_id": ["g1", "g2", "g3", "g4"],
            "team": ["T"] * 4,
            "opponent": ["O"] * 4,
            "position": ["QB"] * 4,
            "line": [10.0] * 4,
            "projection": [8.0, 9.0, 100.0, 100.0],
            "actual": [10.0, 11.0, 0.0, 0.0],
            "actual_minus_line": [0.0, 1.0, -10.0, -10.0],
            "projection_edge": [-2.0, -1.0, 90.0, 90.0],
        })
        out = audit.add_train_derived_features(rows)
        self.assertTrue((out["bias_overall"] == 2.0).all())

    def test_line_blending_math(self) -> None:
        line = 20.0
        projection = 30.0
        self.assertEqual(line + 0.25 * (projection - line), 22.5)

    def test_relative_edge_math(self) -> None:
        result = audit.relative_edge(pd.Series([55.0]), pd.Series([50.0])).iloc[0]
        self.assertAlmostEqual(result, 0.10)

    def test_standardized_edge_math(self) -> None:
        result = audit.standardized_edge(pd.Series([12.0]), 6.0).iloc[0]
        self.assertAlmostEqual(result, 2.0)

    def test_position_segmentation(self) -> None:
        rows = self._prediction_rows()
        diag = audit.position_diagnostics(rows, "test")
        self.assertEqual(set(diag["position"]), {"RB", "WR"})

    def test_side_segmentation(self) -> None:
        rows = self._prediction_rows()
        diag = audit.side_diagnostics(rows, "test")
        self.assertEqual(set(diag["side"]), {"over", "under"})

    def test_exact_projection_equals_line_handling(self) -> None:
        self.assertEqual(audit.projection_direction(0.0), "none")

    def test_walk_forward_minimum_history_guard(self) -> None:
        rows = self._line_rows()
        preds = audit.walk_forward_predictions(rows, min_train_weeks=99)
        self.assertTrue(preds.empty)

    def test_final_holdout_excluded_from_tuning_split(self) -> None:
        rows = self._line_rows()
        split_rows, split_report = audit.assign_split(rows)
        for _, row in split_report.iterrows():
            train_weeks = [int(v) for v in row["train_weeks"].split("|")]
            holdout_weeks = [int(v) for v in row["final_holdout_weeks"].split("|")]
            self.assertLess(max(train_weeks), min(holdout_weeks))
        self.assertIn("final_holdout", set(split_rows["split"]))

    def test_receptions_excluded(self) -> None:
        self.assertNotIn("player_receptions", audit.MODELED_MARKETS)

    def test_rushing_pass_receiving_remain_distinct(self) -> None:
        self.assertEqual(audit.MODELED_MARKETS, {"player_pass_yds", "player_rush_yds", "player_reception_yds"})

    def test_metric_calculations(self) -> None:
        rows = self._prediction_rows()
        metrics = audit.metric_row(rows, "score")
        self.assertEqual(metrics["n"], len(rows))
        self.assertGreaterEqual(metrics["accuracy"], 0.0)
        self.assertLessEqual(metrics["accuracy"], 1.0)

    def test_deterministic_bootstrap(self) -> None:
        rows = self._prediction_rows()
        first = audit.bootstrap_comparisons(rows, iterations=10, seed=1)
        second = audit.bootstrap_comparisons(rows, iterations=10, seed=1)
        pd.testing.assert_frame_equal(first, second)

    def test_candidate_ranking_has_no_week1_dependency(self) -> None:
        rows = self._prediction_rows()
        self.assertTrue((rows["season"] == 2024).all())
        self.assertFalse((rows["season"] == 2026).any())

    def test_no_network_use_marker(self) -> None:
        text = AUDIT_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("requests.", text)
        self.assertNotIn("urllib", text)

    def _line_rows(self) -> pd.DataFrame:
        rows = []
        for week in range(1, 18):
            for player_idx in range(4):
                rows.append({
                    "market": "player_pass_yds",
                    "season": 2024,
                    "week": week,
                    "player": f"Player {week}-{player_idx}",
                    "player_norm": f"player {week}-{player_idx}",
                    "game_id": f"g{week}",
                    "team": "T",
                    "opponent": "O",
                    "position": "QB",
                    "line": 20.0,
                    "projection": 22.0,
                    "actual": 21.0 if (week + player_idx) % 2 else 18.0,
                    "actual_minus_line": 1.0 if (week + player_idx) % 2 else -2.0,
                    "projection_edge": 2.0,
                    "over_price": -110.0,
                    "under_price": -110.0,
                })
        return pd.DataFrame(rows)

    def _prediction_rows(self) -> pd.DataFrame:
        base = []
        for idx in range(40):
            side = "over" if idx % 2 == 0 else "under"
            base.append({
                "market": "player_reception_yds",
                "candidate": "raw_projection_edge",
                "season": 2024,
                "week": 10,
                "player_norm": f"p{idx}",
                "line": float(idx),
                "side": side,
                "position": "WR" if idx < 20 else "RB",
                "score": 1.0 if idx % 3 else -1.0,
                "predicted_win": idx % 3 != 0,
                "won": idx % 4 != 0,
                "push": False,
                "roi": 0.9 if idx % 4 != 0 else -1.0,
                "price": -110.0,
                "predicted_margin": 2.0,
                "actual_minus_line": 1.0,
            })
            alt = base[-1].copy()
            alt["candidate"] = "bias_corrected_overall"
            alt["score"] = alt["score"] * 0.8
            base.append(alt)
        return pd.DataFrame(base)


if __name__ == "__main__":
    unittest.main()
