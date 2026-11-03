"""Write a stage's machine-readable summary for --json.

Every stage script prints a summary for people; with --json PATH it also writes the same
numbers as JSON, so the final report quotes counts instead of re-reading printed text.
The file is replaced atomically, so a reader never sees half a report.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path


def write_report(path: Path | None, stage: str, **fields: object) -> None:
    """Write {"stage", "finished_at", **fields} to path; do nothing when path is None."""
    if path is None:
        return
    report = {"stage": stage, "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              **fields}
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".tmp")
    partial.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(partial, path)
