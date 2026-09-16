from replaykit.recording.schema import Flow, Input, State
from replaykit.replayer.handoff import build_handoff, redact_inputs


class Page:
    url = "http://bank.example/parabank/index.htm"

    def locator(self, selector):
        assert selector == "body"
        return self

    def aria_snapshot(self):
        return '- heading "Customer Login"'

    def screenshot(self):
        return b"png-bytes"


def flow():
    return Flow(
        "login", 1,
        {"username": Input("string", secret=True), "password": Input("string", secret=True), "label": Input("string")},
        {"login_page": State("login_page", "/index", "- heading")}, [],
    )


def test_redact_inputs_only_redacts_declared_secret_inputs():
    assert redact_inputs({"username": "alice", "password": "p@ss", "label": "main"}, flow().inputs) == {
        "username": "[REDACTED]", "password": "[REDACTED]", "label": "main",
    }


def test_handoff_contains_expected_state_runtime_evidence_and_redacted_inputs():
    record = build_handoff(
        Page(), flow(), step_index=1, expected_state=flow().states["login_page"],
        inputs={"username": "alice", "password": "p@ss", "label": "main"},
        ladder_outcomes=[{"candidate": "#username", "count": 0}], timings={"total_ms": 23}, reason="precondition failed",
    )

    data = record.to_dict()
    assert data["flow"] == "login"
    assert data["expected_state"]["template"] == "- heading"
    assert data["actual_url"].endswith("index.htm")
    assert data["screenshot_base64"] == "cG5nLWJ5dGVz"
    assert data["inputs"]["password"] == "[REDACTED]"
