from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pff_content.cache import RawCache, request_hash


class CacheTests(unittest.TestCase):
    def test_parameter_ordering_does_not_change_cache_identity(self) -> None:
        left = request_hash("/v1/games", {"season": 2026, "week": 1, "league": "nfl"})
        right = request_hash("/v1/games", {"week": 1, "league": "nfl", "season": 2026})
        self.assertEqual(left, right)

    def test_cache_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = RawCache(root=Path(temp_dir))
            params = {"league": "nfl", "season": 2026, "week": 1}
            cache.write(season=2026, week=1, dataset="games", path="/v1/games", params=params, status=200, headers={}, body={"games": [{"id": 1}]}, table="games")
            cached = cache.read(season=2026, week=1, dataset="games", path="/v1/games", params=dict(reversed(list(params.items()))))
        self.assertEqual(cached, {"games": [{"id": 1}]})
