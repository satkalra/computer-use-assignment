import json
from pathlib import Path


class JsonlAuditLog:
    """Append-only, secret-free run audit log."""

    def __init__(self, path: Path):
        self.path = path

    def append(self, *, step_index: int, rung: int | None, snapshot_hash: str, duration_ms: int, outcome: str) -> None:
        record = {
            "step_index": step_index,
            "rung": rung,
            "snapshot_hash": snapshot_hash,
            "duration_ms": duration_ms,
            "outcome": outcome,
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
