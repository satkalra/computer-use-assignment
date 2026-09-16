from replaykit.recording.schema import Flow, Input, State, Step, Target
from replaykit.locators.ladder import CandidateOutcome, UnresolvableTarget
from replaykit.replayer.audit import JsonlAuditLog
from replaykit.replayer.engine import ReplayEngine
from replaykit.replayer.recovery import RecoveryResult


class Locator:
    def __init__(self):
        self.values = []
        self.clicks = 0

    def fill(self, value):
        self.values.append(value)

    def click(self):
        self.clicks += 1

    def select_option(self, value):
        self.values.append(value)


class Page:
    url = "http://bank.example/login.htm"

    def locator(self, _selector):
        return self

    def aria_snapshot(self):
        return "- heading Login"

    def screenshot(self):
        return b"screen"


def login_flow():
    login = State("login", r"/login\\.htm", "- heading Login")
    overview = State("overview", r"/overview\\.htm", "- heading Overview")
    return Flow(
        "login", 1, {"username": Input("string", secret=True)},
        {"login": login, "overview": overview},
        [Step("login", "fill", [Target(css="#username")], "{{inputs.username}}", "overview")],
    )


def test_engine_performs_interpolated_action_and_audits_rung(monkeypatch, tmp_path):
    locator = Locator()
    monkeypatch.setattr("replaykit.replayer.engine.wait_for", lambda *_args: True)
    monkeypatch.setattr("replaykit.replayer.engine.resolve", lambda *_args: (locator, 2))
    engine = ReplayEngine(JsonlAuditLog(tmp_path / "run.jsonl"))

    result = engine.run(Page(), login_flow(), {"username": "alice"})

    assert result.status == "success"
    assert locator.values == ["alice"]
    assert '"rung": 2' in (tmp_path / "run.jsonl").read_text()


def test_engine_recovers_then_retries_a_failed_state_once(monkeypatch):
    locator = Locator()
    attempts = iter([False, True, True])
    monkeypatch.setattr("replaykit.replayer.engine.wait_for", lambda *_args: next(attempts))
    monkeypatch.setattr("replaykit.replayer.engine.resolve", lambda *_args: (locator, 1))
    monkeypatch.setattr("replaykit.replayer.engine.recover", lambda *_args: RecoveryResult(dialog_dismissed=True))

    result = ReplayEngine().run(Page(), login_flow(), {"username": "alice"})

    assert result.status == "success"
    assert locator.values == ["alice"]


def test_engine_stops_with_a_handoff_after_the_single_retry(monkeypatch):
    locator = Locator()
    calls = []
    monkeypatch.setattr("replaykit.replayer.engine.wait_for", lambda *_args: calls.append(1) or False)
    monkeypatch.setattr("replaykit.replayer.engine.resolve", lambda *_args: (locator, 1))
    monkeypatch.setattr("replaykit.replayer.engine.recover", lambda *_args: RecoveryResult())

    result = ReplayEngine().run(Page(), login_flow(), {"username": "alice"})

    assert result.status == "handoff"
    assert len(calls) == 2
    assert result.handoff.to_dict()["reason"] == "precondition failed"
    assert result.handoff.to_dict()["inputs"]["username"] == "[REDACTED]"


def test_engine_handoffs_immediately_when_session_expiry_is_detected(monkeypatch):
    """Session-expiry recovery is detection-only (spec 2026-09-16-phase01 4.4): a second
    precondition check can never succeed, so retrying it would only clobber the diagnosis
    with a generic 'precondition failed' message. The engine must stop on the first attempt
    and preserve the specific reason."""
    locator = Locator()
    calls = []
    monkeypatch.setattr("replaykit.replayer.engine.wait_for", lambda *_args: calls.append(1) or False)
    monkeypatch.setattr("replaykit.replayer.engine.resolve", lambda *_args: (locator, 1))
    monkeypatch.setattr("replaykit.replayer.engine.recover", lambda *_args: RecoveryResult(session_expired=True))

    result = ReplayEngine().run(Page(), login_flow(), {"username": "alice"})

    assert result.status == "handoff"
    assert len(calls) == 1
    assert result.handoff.to_dict()["reason"] == "session expired; sub-flow recovery is not supported in this version"
    assert result.handoff.to_dict()["inputs"]["username"] == "[REDACTED]"


def test_engine_handoffs_when_no_locator_candidate_resolves(monkeypatch):
    monkeypatch.setattr("replaykit.replayer.engine.wait_for", lambda *_args: True)
    monkeypatch.setattr(
        "replaykit.replayer.engine.resolve",
        lambda *_args: (_ for _ in ()).throw(UnresolvableTarget([CandidateOutcome(Target(css="#missing"), 0)])),
    )

    result = ReplayEngine().run(Page(), login_flow(), {"username": "alice"})

    assert result.status == "handoff"
    assert result.handoff.to_dict()["ladder_outcomes"][0]["count"] == 0


def test_engine_reports_session_expiry_against_the_postcondition_state(monkeypatch):
    """Session expiry can also surface as a postcondition failure (the step succeeded but
    bounced back to login instead of reaching `to`). The handoff must still name the state
    that was actually expected at that point (`to`), not unconditionally `from`."""
    locator = Locator()
    results = iter([True, False, False])  # from-state ok, to-state fails, then attempt-2 short-circuits
    monkeypatch.setattr("replaykit.replayer.engine.wait_for", lambda *_args: next(results))
    monkeypatch.setattr("replaykit.replayer.engine.resolve", lambda *_args: (locator, 1))
    monkeypatch.setattr("replaykit.replayer.engine.recover", lambda *_args: RecoveryResult(session_expired=True))

    result = ReplayEngine().run(Page(), login_flow(), {"username": "alice"})

    assert result.status == "handoff"
    assert result.handoff.to_dict()["expected_state"]["name"] == "overview"
    assert result.handoff.to_dict()["reason"] == "session expired; sub-flow recovery is not supported in this version"


def test_engine_retries_a_failed_postcondition_from_the_declared_from_state(monkeypatch):
    locator = Locator()
    states_seen = []
    results = iter([True, False, True, True])

    def fake_wait(_page, state, _timeout):
        states_seen.append(state.name)
        return next(results)

    monkeypatch.setattr("replaykit.replayer.engine.wait_for", fake_wait)
    monkeypatch.setattr("replaykit.replayer.engine.resolve", lambda *_args: (locator, 1))
    monkeypatch.setattr("replaykit.replayer.engine.recover", lambda *_args: RecoveryResult(dialog_dismissed=True))

    result = ReplayEngine().run(Page(), login_flow(), {"username": "alice"})

    assert result.status == "success"
    assert states_seen == ["login", "overview", "login", "overview"]
    assert locator.values == ["alice", "alice"]
