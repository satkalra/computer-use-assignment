import pytest

from replaykit.recorder.session import record
from replaykit.recorder.spec import FlowSpec, InputSpec
from replaykit.policy.policy import Policy


class ToolUse:
    type = "tool_use"

    def __init__(self, name, payload, identifier="t1"):
        self.name, self.input, self.id = name, payload, identifier


class Text:
    type = "text"

    def __init__(self, text):
        self.text = text


class Response:
    def __init__(self, blocks):
        self.content = blocks
        self.usage = type("Usage", (), {"input_tokens": 10, "output_tokens": 2})()


class FakeClient:
    """A deterministic stand-in for the external model boundary."""

    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.messages = self

    def create(self, **_kwargs):
        return Response([self._scripted.pop(0)])


def spec():
    return FlowSpec(
        name="login",
        goal="Log in.",
        start_url="unused",
        inputs={"username": InputSpec("string", secret=True)},
        outputs={},
    )


def test_record_executes_tool_calls_and_captures_a_trace(page, pages_url):
    page.goto(f"{pages_url}/login.html")
    from replaykit.recorder.snapshot import capture

    textbox = next(element for element in capture(page).elements.values() if element.role == "textbox")
    client = FakeClient([
        ToolUse("fill", {"ref": textbox.ref, "value": "alice"}),
        ToolUse("done", {"outputs": {}}),
    ])

    trace = record(page, spec(), {"username": "alice"}, client)

    assert trace.status == "success"
    assert [step.action for step in trace.steps] == ["fill"]
    assert trace.steps[0].value == "alice"
    assert trace.steps[0].snapshot_before and trace.steps[0].url_before
    assert trace.steps[0].targets[0].css == "#username"
    assert page.locator("#username").input_value() == "alice"


def test_record_never_leaks_a_secret_value_through_the_post_fill_snapshot(page, pages_url):
    """A filled secret sits in the live DOM immediately -- the snapshot taken right
    after filling it (and sent back to the model, and stored in the trace) must not
    reveal it, or the placeholder-prompt protection is undone one step later."""
    page.goto(f"{pages_url}/login.html")
    from replaykit.recorder.snapshot import capture

    elements = list(capture(page).elements.values())
    username_ref = next(e.ref for e in elements if e.role == "textbox")
    password_ref = [e.ref for e in elements if e.role == "textbox"][1]

    client = FakeClient([
        ToolUse("fill", {"ref": username_ref, "value": "{{inputs.username}}"}),
        ToolUse("fill", {"ref": password_ref, "value": "{{inputs.password}}"}),
        ToolUse("done", {"outputs": {}}),
    ])
    secret_spec = FlowSpec(
        name="login", goal="Log in.", start_url="unused",
        inputs={"username": InputSpec("string"), "password": InputSpec("string", secret=True)},
        outputs={},
    )

    trace = record(page, secret_spec, {"username": "alice", "password": "hunter2"}, client)

    assert trace.status == "success"
    import json
    from dataclasses import asdict

    assert "hunter2" not in json.dumps(asdict(trace))


def test_record_reports_an_unresolvable_ref_back_to_the_model(page, pages_url):
    page.goto(f"{pages_url}/login.html")
    client = FakeClient([
        ToolUse("click", {"ref": "e999"}),
        ToolUse("done", {"outputs": {}}),
    ])

    trace = record(page, spec(), {"username": "alice"}, client)

    assert trace.steps == []
    assert trace.status == "success"


def test_record_never_puts_a_literal_secret_value_in_the_prompt(monkeypatch):
    sent = []

    class Snapshot:
        url = "http://bank.example/login.htm"
        text = "- textbox [ref=e1]"
        elements = {}

    monkeypatch.setattr("replaykit.recorder.session.capture", lambda _page: Snapshot())

    class Client:
        class messages:
            @staticmethod
            def create(**kwargs):
                sent.append(kwargs["messages"])
                return Response([ToolUse("done", {"outputs": {}})])

    private_spec = FlowSpec(
        name="login", goal="log in", start_url="http://bank.example/login.htm",
        inputs={"password": InputSpec("string", secret=True)}, outputs={},
    )

    record(None, private_spec, {"password": "hunter2"}, Client())

    all_text = str(sent)
    assert "hunter2" not in all_text
    assert "{{inputs.password}}" in all_text


def test_record_stops_on_a_risky_action_with_no_operator_attached(monkeypatch):
    class Snapshot:
        url = "http://bank.example/transfer.htm"
        text = "- button [ref=e1]"
        elements = {"e1": type("El", (), {"ref": "e1", "role": "button", "name": "Transfer Funds"})()}

    monkeypatch.setattr("replaykit.recorder.session.capture", lambda _page: Snapshot())
    monkeypatch.setattr("replaykit.compiler.candidates.derive", lambda *_args: [])

    class Client:
        class messages:
            @staticmethod
            def create(**_kwargs):
                return Response([ToolUse("click", {"ref": "e1"})])

    transfer_spec = FlowSpec(
        name="transfer", goal="transfer funds",
        start_url="http://bank.example/transfer.htm", inputs={}, outputs={},
    )
    policy = Policy(["http://bank.example"], {"click"}, ["(?i)transfer"])

    with pytest.raises(RuntimeError, match="discovery stopped"):
        record(None, transfer_spec, {}, Client(), policy=policy, control=None)


def test_record_stops_and_writes_evidence_for_a_policy_violation(monkeypatch, tmp_path):
    class Snapshot:
        url = "http://bank.example/login.htm"
        text = "- button [ref=e1]"
        elements = {"e1": type("El", (), {"ref": "e1", "role": "button", "name": "Log In"})()}

    monkeypatch.setattr("replaykit.recorder.session.capture", lambda _page: Snapshot())
    monkeypatch.setattr("replaykit.compiler.candidates.derive", lambda *_args: [])

    class Client:
        class messages:
            @staticmethod
            def create(**_kwargs):
                return Response([ToolUse("click", {"ref": "e1"})])

    policy = Policy(["http://allowed.example"], {"click"}, [])

    with pytest.raises(RuntimeError, match="policy blocked"):
        record(None, spec(), {"username": "alice"}, Client(), policy=policy, evidence_dir=tmp_path)

    assert "outside the allowed origins" in (tmp_path / "policy_violation.json").read_text()


def test_record_blocks_a_goto_by_its_destination_not_its_starting_page(monkeypatch, tmp_path):
    class Snapshot:
        url = "http://bank.example/login.htm"
        text = "- heading"
        elements = {}

    monkeypatch.setattr("replaykit.recorder.session.capture", lambda _page: Snapshot())

    class Client:
        class messages:
            @staticmethod
            def create(**_kwargs):
                return Response([ToolUse("goto", {"url": "http://evil.example/steal"})])

    policy = Policy(["http://bank.example"], {"goto"}, [])

    with pytest.raises(RuntimeError, match="policy blocked"):
        record(None, spec(), {}, Client(), policy=policy, evidence_dir=tmp_path)

    violation = (tmp_path / "policy_violation.json").read_text()
    assert "evil.example" in violation
    assert "bank.example" not in violation


def test_record_logs_reasoning_and_redacts_secrets(monkeypatch, tmp_path):
    class Snapshot:
        url = "http://bank.example/login.htm"
        text = "- textbox [ref=e1]"
        elements = {"e1": type("El", (), {"ref": "e1", "role": "textbox", "name": "username"})()}

    monkeypatch.setattr("replaykit.recorder.session.capture", lambda _page: Snapshot())
    monkeypatch.setattr("replaykit.compiler.candidates.derive", lambda *_args: [])
    monkeypatch.setattr("replaykit.recorder.session._apply", lambda *_args: None)

    responses = [
        [Text("filling username field"), ToolUse("fill", {"ref": "e1", "value": "{{inputs.username}}"})],
        [Text("submitting form"), ToolUse("done", {"outputs": {}})],
    ]

    class ClientWithMultipleBlocks:
        def __init__(self):
            self.call_count = 0
            self.messages = self

        def create(self, **_kwargs):
            result = responses[self.call_count]
            self.call_count += 1
            return Response(result)

    trace = record(None, spec(), {"username": "alice"}, ClientWithMultipleBlocks(), evidence_dir=tmp_path)

    assert trace.status == "success"
    log_file = tmp_path / "log.jsonl"
    assert log_file.exists()

    import json
    lines = [json.loads(line) for line in log_file.read_text().strip().split("\n")]

    assert len(lines) == 2
    assert lines[0]["turn"] == 1
    assert lines[0]["reasoning"] == "filling username field"
    assert lines[0]["tool"] == "fill"
    assert lines[0]["outcome"] == "ok"
    assert "alice" not in json.dumps(lines[0])

    assert lines[1]["turn"] == 2
    assert lines[1]["reasoning"] == "submitting form"
    assert lines[1]["tool"] == "done"
    assert lines[1]["outcome"] == "done"
