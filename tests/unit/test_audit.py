import json

from replaykit.replayer.audit import JsonlAuditLog


def test_audit_log_appends_a_json_record(tmp_path):
    log = JsonlAuditLog(tmp_path / "run.jsonl")

    log.append(step_index=2, rung=3, snapshot_hash="abc", duration_ms=17, outcome="success")

    assert json.loads((tmp_path / "run.jsonl").read_text()) == {
        "duration_ms": 17,
        "outcome": "success",
        "rung": 3,
        "snapshot_hash": "abc",
        "step_index": 2,
    }
