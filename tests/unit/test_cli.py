import argparse
import json

from replaykit.cli import _parse_kv, build_record_parser, build_replay_parser, run_record, run_replay
from replaykit.promotion.gate import GateReport, GateRun
from replaykit.recorder.trace import Trace


def test_parse_kv_splits_on_first_equals_only():
    assert _parse_kv(["username=alice", "note=a=b"]) == {"username": "alice", "note": "a=b"}


def test_build_replay_parser_accepts_target_input_and_approve():
    parser = argparse.ArgumentParser()
    build_replay_parser(parser)

    args = parser.parse_args([
        "flow.yaml", "--target", "http://bank.example",
        "--input", "username=alice", "--approve", "2",
    ])

    assert args.flow_path == "flow.yaml"
    assert args.target == "http://bank.example"
    assert args.input == ["username=alice"]
    assert args.approve == [2]


def test_run_replay_writes_evidence_and_returns_zero_on_success(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "policy.yaml").write_text(
        "allowed_origins: ['http://bank.example']\nallowed_actions: [click]\n"
    )
    flow_path = tmp_path / "login.yaml"
    flow_path.write_text("""
flow: login
version: 1
inputs: {}
states:
  start: {url: /start, aria: '- heading'}
steps:
  - from: start
    action: click
    target: [{role: button, name: Go}]
""")

    class FakeResult:
        status = "success"
        outputs = {"balance": "$1.00"}
        outcome = None
        handoff = None
        step_index = 1
        approval_reason = None

    class FakePage:
        url = "http://bank.example/start"

        def goto(self, _url):
            pass

        def screenshot(self):
            return b"x"

    class FakeBrowser:
        def new_page(self):
            return FakePage()

        def close(self):
            pass

    class FakePlaywrightCtx:
        def __enter__(self):
            chromium = type("Chromium", (), {"launch": staticmethod(lambda headless=True: FakeBrowser())})
            return type("PW", (), {"chromium": chromium})()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("replaykit.cli.sync_playwright", lambda: FakePlaywrightCtx())
    monkeypatch.setattr(
        "replaykit.cli.ReplayEngine",
        lambda *_a, **_kw: type("E", (), {"run": staticmethod(lambda *a, **kw: FakeResult())})(),
    )

    parser = argparse.ArgumentParser()
    build_replay_parser(parser)
    args = parser.parse_args([str(flow_path), "--target", "http://bank.example/start"])

    exit_code = run_replay(args, control=None)

    assert exit_code == 0
    evidence_dirs = list((tmp_path / "evidence").iterdir())
    assert len(evidence_dirs) == 1
    result_json = json.loads((evidence_dirs[0] / "result.json").read_text())
    assert result_json["status"] == "success"


def test_run_replay_approves_a_step_after_an_operator_resumes(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "policy.yaml").write_text(
        "allowed_origins: ['http://bank.example']\nallowed_actions: [click]\n"
    )
    flow_path = tmp_path / "login.yaml"
    flow_path.write_text("""
flow: login
version: 1
inputs: {}
states:
  start: {url: /start, aria: '- heading'}
steps:
  - from: start
    action: click
    target: [{role: button, name: Go}]
""")

    class Result:
        def __init__(self, status, step_index=0):
            self.status = status
            self.outputs = None
            self.outcome = None
            self.handoff = None
            self.step_index = step_index
            self.approval_reason = "click requires approval"

    class Page:
        url = "http://bank.example/start"

        def goto(self, _url):
            pass

        def screenshot(self):
            return b"x"

    class Browser:
        def new_page(self):
            return Page()

        def close(self):
            pass

    class PlaywrightContext:
        def __enter__(self):
            chromium = type("Chromium", (), {"launch": staticmethod(lambda headless=True: Browser())})
            return type("PW", (), {"chromium": chromium})()

        def __exit__(self, *exc):
            return False

    class Engine:
        def __init__(self, *_args, **kwargs):
            self.approved = kwargs["approved"]
            self.approvals_seen = []
            self.results = iter([Result("needs_approval"), Result("success", 1)])

        def run(self, *_args, **_kwargs):
            self.approvals_seen.append(set(self.approved))
            return next(self.results)

    engine = Engine(approved=set())
    monkeypatch.setattr("replaykit.cli.sync_playwright", lambda: PlaywrightContext())
    monkeypatch.setattr("replaykit.cli.ReplayEngine", lambda *_a, **_kw: engine)
    monkeypatch.setattr("replaykit.cli.intervene", lambda *_args: True)
    monkeypatch.setattr("replaykit.cli.find_resume_index", lambda *_args, **_kwargs: 0)

    parser = argparse.ArgumentParser()
    build_replay_parser(parser)
    args = parser.parse_args([str(flow_path), "--target", "http://bank.example/start"])

    assert run_replay(args, control=object()) == 0
    assert engine.approvals_seen == [set(), {0}]


_CANDIDATE_YAML = """
flow: login
version: 1
inputs: {}
states:
  start: {url: /start, aria: '- heading'}
steps:
  - from: start
    action: click
    target: [{role: button, name: Go}]
"""


def _record_cli_test_fixture(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "policy.yaml").write_text(
        "allowed_origins: ['http://bank.example']\nallowed_actions: [click, fill, goto, select, extract]\n"
    )

    class Page:
        url = "http://bank.example/start"

        def goto(self, _url):
            pass

    class Browser:
        def new_page(self):
            return Page()

        def close(self):
            pass

    class PlaywrightContext:
        def __enter__(self):
            chromium = type("Chromium", (), {"launch": staticmethod(lambda headless=True: Browser())})
            return type("PW", (), {"chromium": chromium})()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("replaykit.cli.sync_playwright", lambda: PlaywrightContext())
    monkeypatch.setattr("replaykit.cli.record", lambda *_a, **_kw: Trace(spec=None, status="success"))
    monkeypatch.setattr("replaykit.cli.compile_trace", lambda *_a, **_kw: _CANDIDATE_YAML)

    parser = argparse.ArgumentParser()
    build_record_parser(parser)
    return parser.parse_args([
        "--name", "login", "--goal", "log in",
        "--target", "http://bank.example/start",
    ])


def test_run_record_saves_the_flow_once_the_promotion_gate_passes(monkeypatch, tmp_path):
    args = _record_cli_test_fixture(monkeypatch, tmp_path)
    passing_report = GateReport(
        passed=True, runs=[GateRun(user="run0", status="success", outputs={})],
        recording_yaml=_CANDIDATE_YAML, summary="run0: success",
    )
    monkeypatch.setattr("replaykit.cli.run_gate", lambda *_a, **_kw: passing_report)

    exit_code = run_record(args, control=None, client=object())

    assert exit_code == 0
    assert (tmp_path / "replaykit" / "flows" / "login.yaml").exists()
    gate_evidence = json.loads(next((tmp_path / "evidence").glob("discovery-*/promotion_gate.json")).read_text())
    assert gate_evidence["passed"] is True


def test_run_record_does_not_save_a_flow_that_fails_the_promotion_gate(monkeypatch, tmp_path):
    args = _record_cli_test_fixture(monkeypatch, tmp_path)
    failing_report = GateReport(
        passed=False, runs=[GateRun(user="run0", status="handoff", outputs=None, errors=["postcondition failed"])],
        recording_yaml=_CANDIDATE_YAML, summary="run0: handoff — postcondition failed",
    )
    monkeypatch.setattr("replaykit.cli.run_gate", lambda *_a, **_kw: failing_report)

    exit_code = run_record(args, control=None, client=object())

    assert exit_code == 1
    assert not (tmp_path / "replaykit" / "flows" / "login.yaml").exists()
