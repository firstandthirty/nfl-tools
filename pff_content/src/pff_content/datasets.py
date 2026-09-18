from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    endpoint: str
    table: str


DATASETS: tuple[DatasetSpec, ...] = (
    DatasetSpec("games", "/v1/games", "games"),
    DatasetSpec("passing", "/v1/facet/passing/summary", "passing_summary"),
    DatasetSpec("receiving", "/v1/facet/receiving/summary", "receiving_summary"),
    DatasetSpec("rushing", "/v1/facet/rushing/summary", "rushing_summary"),
    DatasetSpec("pass_blocking", "/v1/facet/offense/pass_blocking", "pass_blocking"),
    DatasetSpec("pass_rush", "/v1/facet/defense/pass_rush", "pass_rush_summary"),
    DatasetSpec("run_defense", "/v1/facet/defense/run", "run_defense_summary"),
    DatasetSpec("coverage", "/v1/facet/defense/coverage", "coverage_summary"),
    DatasetSpec("coverage_scheme", "/v1/facet/defense/coverage_scheme", "coverage_scheme"),
    DatasetSpec("time_in_pocket", "/v1/facet/signature/passing/time_in_pocket", "time_in_pockets"),
)


def dataset_by_name(name: str) -> DatasetSpec:
    for spec in DATASETS:
        if spec.name == name:
            return spec
    raise KeyError(name)
