from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def write_odds_asof_outputs(result: dict[str, Any], *, output_dir: Path | str, overwrite: bool = False) -> dict[str, str]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "selected_snapshots": output_dir / "selected_snapshots.csv",
        "selected_odds": output_dir / "selected_odds.csv",
        "odds_coverage": output_dir / "odds_coverage.csv",
        "report": output_dir / "odds_asof_report.md",
    }
    if not overwrite and any(path.exists() for path in outputs.values()):
        raise FileExistsError(f"Odds as-of output directory already exists: {output_dir}")
    result["selected_snapshots"].to_csv(outputs["selected_snapshots"], index=False)
    result["selected_odds"].to_csv(outputs["selected_odds"], index=False)
    result["coverage"].to_csv(outputs["odds_coverage"], index=False)
    report = [
        "# Odds as-of report",
        "",
        f"- As-of: {result['as_of'].isoformat()}",
        f"- Sportsbooks requested: {'|'.join(result.get('requested_sportsbooks', []))}",
        f"- Selected snapshots: {int((result['selected_snapshots']['selection_status'] == 'selected').sum()) if not result['selected_snapshots'].empty else 0}",
        f"- Selected odds rows: {len(result['selected_odds'])}",
        "",
        "Odds are selected independently by sportsbook. No averaging across snapshots or books is performed.",
    ]
    outputs["report"].write_text("\n".join(report), encoding="utf-8")
    return {key: str(value) for key, value in outputs.items()}

