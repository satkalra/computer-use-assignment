from replaykit.recorder.session import record
from replaykit.recorder.spec import FlowSpec, InputSpec


class ToolUse:
    type = "tool_use"

    def __init__(self, name, payload, identifier="t1"):
        self.name, self.input, self.id = name, payload, identifier


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


def test_record_reports_an_unresolvable_ref_back_to_the_model(page, pages_url):
    page.goto(f"{pages_url}/login.html")
    client = FakeClient([
        ToolUse("click", {"ref": "e999"}),
        ToolUse("done", {"outputs": {}}),
    ])

    trace = record(page, spec(), {"username": "alice"}, client)

    assert trace.steps == []
    assert trace.status == "success"
