import yaml

from replaykit.compiler import compile_trace
from replaykit.recorder.spec import FlowSpec, OutputSpec
from replaykit.recorder.trace import Trace, TraceStep
from replaykit.recording.schema import Target


def _spec(outputs=None):
    return FlowSpec(
        name="overview", goal="Read the account overview.",
        start_url="http://bank.example/index.htm", inputs={}, outputs=outputs or {},
    )


def test_compile_trace_uses_targets_captured_while_the_ref_was_live():
    trace = Trace(
        spec=_spec(),
        steps=[TraceStep(
            action="click", ref="expired-ref", role="button", name="Continue",
            url_before="http://bank.example/index.htm",
            url_after="http://bank.example/overview.htm",
            snapshot_before='- heading "Login"',
            snapshot_after='- heading "Overview"',
            targets=[Target(css="#continue")],
        )],
    )

    recording = yaml.safe_load(compile_trace(object(), trace, {}))

    assert recording["steps"][0]["target"] == [{"css": "#continue"}]
    assert recording["steps"][0]["from"] == "state_1"
    assert recording["steps"][0]["to"] == "state_2"


def test_compile_trace_promotes_captured_extract_target_to_top_level_block():
    trace = Trace(
        spec=_spec({"balance": OutputSpec("decimal")}),
        steps=[TraceStep(
            action="extract", ref="expired-ref", role="paragraph", name="Balance",
            output_name="balance", url_before="http://bank.example/overview.htm",
            url_after="http://bank.example/overview.htm",
            snapshot_before='- heading "Overview"',
            snapshot_after='- heading "Overview"',
            targets=[Target(css="#balance")],
        )],
    )

    recording = yaml.safe_load(compile_trace(object(), trace, {}))

    assert recording["steps"] == []
    assert recording["extract"] == [{
        "from": "state_1", "target": [{"css": "#balance"}], "outputs": ["balance"],
    }]


def test_compile_trace_strips_ai_mode_annotations_from_state_templates():
    """ai-mode snapshots annotate every element with [ref=..] and clickable
    ones with [cursor=..]. Both are ephemeral/ai-mode-only -- Playwright's
    to_match_aria_snapshot (what the replayer checks state predicates with)
    doesn't recognise them, so a template built from raw lines can never
    match a real page at replay time."""
    trace = Trace(
        spec=_spec(),
        steps=[TraceStep(
            action="click", ref="e39", role="button", name="Log In",
            url_before="http://bank.example/index.htm",
            url_after="http://bank.example/overview.htm",
            snapshot_before='- heading "Customer Login" [level=2] [ref=e29]\n'
                             '- button "Log In" [ref=e39] [cursor=pointer]',
            snapshot_after='- heading "Accounts Overview" [level=2] [ref=f29]',
            targets=[Target(role="button", name="Log In")],
        )],
    )

    recording = yaml.safe_load(compile_trace(object(), trace, {}))

    for state in recording["states"].values():
        assert "[ref=" not in state["aria"]
        assert "[cursor=" not in state["aria"]
