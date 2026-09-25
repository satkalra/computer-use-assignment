from replaykit.recording.schema import Extract, Flow, Input, Outcome, Output, State, Step, Target
from replaykit.locators.ladder import CandidateOutcome, UnresolvableTarget
from replaykit.policy.policy import Policy
from replaykit.replayer.audit import JsonlAuditLog
from replaykit.replayer.engine import ReplayEngine, find_resume_index
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


def test_engine_handoffs_instead_of_silently_passing_through_an_unmatched_placeholder(monkeypatch):
    """A value like 'Amt: {{inputs.x}}' isn't a supported partial-interpolation syntax --
    _interpolate's regex only handles a value that IS the placeholder, in full. Silently
    filling that literal string into a bank form field would be worse than a visible,
    inspectable handoff, so an unresolved '{{inputs.' must fail the step, not pass through."""
    locator = Locator()
    base = login_flow()
    flow = Flow(
        base.name, base.version, base.inputs, base.states,
        [Step("login", "fill", [Target(css="#username")], "Amt: {{inputs.username}}", "overview")],
    )
    monkeypatch.setattr("replaykit.replayer.engine.wait_for", lambda *_args: True)
    monkeypatch.setattr("replaykit.replayer.engine.resolve", lambda *_args: (locator, 1))
    monkeypatch.setattr("replaykit.replayer.engine.recover", lambda *_args: RecoveryResult())

    result = ReplayEngine().run(Page(), flow, {"username": "alice"})

    assert result.status == "handoff"
    assert "{{inputs." in result.handoff.to_dict()["reason"]
    assert locator.values == []


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


def test_engine_returns_validated_extractor_outputs(monkeypatch):
    locator = Locator()
    flow = login_flow()
    flow = Flow(
        flow.name, flow.version, flow.inputs, flow.states, flow.steps,
        extract=[Extract("overview", [Target(css="#balance")], outputs=["balance"])],
        outputs={"balance": Output("decimal")},
    )
    monkeypatch.setattr("replaykit.replayer.engine.wait_for", lambda *_args: True)
    monkeypatch.setattr("replaykit.replayer.engine.resolve", lambda *_args: (locator, 1))
    monkeypatch.setattr("replaykit.replayer.engine.run_extractors", lambda *_args: {"balance": "$4.20"})

    result = ReplayEngine().run(Page(), flow, {"username": "alice"})

    assert result.status == "success"
    assert result.outputs == {"balance": "$4.20"}


def test_engine_handoffs_when_extracted_output_fails_validation(monkeypatch):
    locator = Locator()
    flow = login_flow()
    flow = Flow(
        flow.name, flow.version, flow.inputs, flow.states, flow.steps,
        extract=[Extract("overview", [Target(css="#balance")], outputs=["balance"])],
        outputs={"balance": Output("decimal")},
    )
    monkeypatch.setattr("replaykit.replayer.engine.wait_for", lambda *_args: True)
    monkeypatch.setattr("replaykit.replayer.engine.resolve", lambda *_args: (locator, 1))
    monkeypatch.setattr("replaykit.replayer.engine.run_extractors", lambda *_args: {"balance": "nope"})

    result = ReplayEngine().run(Page(), flow, {"username": "alice"})

    assert result.status == "handoff"
    assert result.outputs == {"balance": "nope"}
    assert "output validation failed" in result.handoff.to_dict()["reason"]


def test_engine_reports_a_declared_business_outcome_instead_of_a_handoff(monkeypatch):
    locator = Locator()
    flow = login_flow()
    no_results = State("no_results_page", r"/login\\.htm", "- heading No results")
    flow = Flow(
        flow.name, flow.version, flow.inputs,
        {**flow.states, "no_results_page": no_results}, flow.steps,
        outcomes={"no_results": Outcome(state="no_results_page")},
    )
    monkeypatch.setattr("replaykit.replayer.engine.wait_for", lambda *args: args[1].name == "login")
    monkeypatch.setattr("replaykit.replayer.engine.resolve", lambda *_args: (locator, 1))
    monkeypatch.setattr("replaykit.replayer.engine.matches", lambda _page, state: state.name == "no_results_page")

    result = ReplayEngine().run(Page(), flow, {"username": "alice"})

    assert result.status == "business_outcome"
    assert result.outcome == "no_results"


def test_engine_default_approved_set_is_mutable():
    """cli.py does `engine.approved.add(step_index)` after an operator approves a risky
    step; a caller that doesn't pass its own `approved` set relies on the default being a
    real, mutable set(), not an immutable frozenset() that .add() would blow up on."""
    engine = ReplayEngine()

    engine.approved.add(0)

    assert engine.approved == {0}


def test_engine_returns_needs_approval_for_an_unapproved_risky_step(monkeypatch):
    risky_flow = Flow(
        "transfer", 1, {},
        {"start": State("start", r"/transfer\\.htm", "- heading")},
        [Step("start", "click", [Target(role="button", name="Transfer Funds")])],
    )
    policy = Policy(["http://bank.example"], {"click"}, ["(?i)transfer"])
    monkeypatch.setattr("replaykit.replayer.engine.wait_for", lambda *_args: True)
    monkeypatch.setattr("replaykit.replayer.engine.resolve", lambda *_args: (Locator(), 1))

    result = ReplayEngine(policy=policy).run(Page(), risky_flow, {})

    assert result.status == "needs_approval"
    assert result.step_index == 0
    assert "requires approval" in result.approval_reason


def test_engine_allows_a_pre_approved_risky_step(monkeypatch):
    locator = Locator()
    risky_flow = Flow(
        "transfer", 1, {},
        {"start": State("start", r"/transfer\\.htm", "- heading")},
        [Step("start", "click", [Target(role="button", name="Transfer Funds")])],
    )
    policy = Policy(["http://bank.example"], {"click"}, ["(?i)transfer"])
    monkeypatch.setattr("replaykit.replayer.engine.wait_for", lambda *_args: True)
    monkeypatch.setattr("replaykit.replayer.engine.resolve", lambda *_args: (locator, 1))

    result = ReplayEngine(policy=policy, approved={0}).run(Page(), risky_flow, {})

    assert result.status == "success"
    assert locator.clicks == 1


def test_engine_fails_hard_on_a_policy_violation_instead_of_offering_a_resumable_handoff(monkeypatch):
    """PolicyViolation (disallowed origin/action) is a hard stop per policy.py's own
    docstring -- unlike a locator/postcondition failure, there's no live-page state an
    operator can fix and resume from. It must not come back as a resumable 'handoff'."""
    flow = Flow(
        "transfer", 1, {},
        {"start": State("start", r"/transfer\\.htm", "- heading")},
        [Step("start", "click", [Target(role="button", name="Delete Account")])],
    )
    policy = Policy(["http://bank.example"], {"fill"}, [])  # click not in allowed_actions
    recover_calls = []
    monkeypatch.setattr("replaykit.replayer.engine.wait_for", lambda *_args: True)
    monkeypatch.setattr("replaykit.replayer.engine.resolve", lambda *_args: (Locator(), 1))
    monkeypatch.setattr("replaykit.replayer.engine.recover", lambda *_args: recover_calls.append(1))

    result = ReplayEngine(policy=policy).run(Page(), flow, {})

    assert result.status == "failed"
    assert recover_calls == []


def test_engine_requires_approval_for_a_css_only_click(monkeypatch):
    flow = Flow(
        "transfer", 1, {},
        {"start": State("start", r"/transfer\\.htm", "- heading")},
        [Step("start", "click", [Target(css="button.btn-primary")])],
    )
    policy = Policy(["http://bank.example"], {"click"}, ["(?i)transfer"])
    monkeypatch.setattr("replaykit.replayer.engine.wait_for", lambda *_args: True)
    monkeypatch.setattr("replaykit.replayer.engine.resolve", lambda *_args: (Locator(), 1))

    result = ReplayEngine(policy=policy).run(Page(), flow, {})

    assert result.status == "needs_approval"


def test_engine_run_can_start_from_a_later_step_index(monkeypatch):
    locator = Locator()
    flow = Flow(
        "two_steps", 1, {"username": Input("string")},
        {"login": State("login", r"/login\\.htm", "- heading Login")},
        [
            Step("login", "fill", [Target(css="#username")], "{{inputs.username}}"),
            Step("login", "click", [Target(role="button", name="Continue")]),
        ],
    )
    monkeypatch.setattr("replaykit.replayer.engine.wait_for", lambda *_args: True)
    monkeypatch.setattr("replaykit.replayer.engine.resolve", lambda *_args: (locator, 1))

    result = ReplayEngine().run(Page(), flow, {"username": "alice"}, start_index=1)

    assert result.status == "success"
    assert result.step_index == 2
    assert locator.values == []
    assert locator.clicks == 1


def test_find_resume_index_returns_the_first_matching_step(monkeypatch):
    flow = Flow(
        "two_steps", 1, {},
        {
            "login": State("login", r"/login\\.htm", "- heading Login"),
            "overview": State("overview", r"/overview\\.htm", "- heading Overview"),
        },
        [
            Step("login", "click", [Target(role="button", name="Continue")], to="overview"),
            Step("overview", "click", [Target(role="button", name="Finish")]),
        ],
    )
    monkeypatch.setattr("replaykit.replayer.engine.matches", lambda _page, state: state.name == "overview")

    assert find_resume_index(Page(), flow) == 1


def test_find_resume_index_does_not_jump_back_to_an_earlier_step_sharing_the_same_state(monkeypatch):
    """Three fields on one login page all declare `from: login`, exactly like
    accounts_overview_live.yaml. Getting stuck on the third step (still on the
    login page) must resume there, not replay the first field again."""
    flow = Flow(
        "login_form", 1, {},
        {"login": State("login", r"/login\\.htm", "- heading Login")},
        [
            Step("login", "fill", [Target(css="#username")], value="alice"),
            Step("login", "fill", [Target(css="#password")], value="secret"),
            Step("login", "click", [Target(role="button", name="Log In")]),
        ],
    )
    monkeypatch.setattr("replaykit.replayer.engine.matches", lambda _page, state: state.name == "login")

    assert find_resume_index(Page(), flow, min_index=2) == 2
