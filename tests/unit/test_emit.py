import yaml

from replaykit.compiler.emit import emit, parameterize
from replaykit.recorder.spec import FlowSpec, InputSpec, OutputSpec
from replaykit.recorder.trace import Trace, TraceStep
from replaykit.recording.schema import State, Target


def test_parameterize_replaces_a_value_that_came_from_an_input():
    """Removing input substitution would expose supplied secrets in recordings."""
    assert parameterize("alice", {"username": "alice"}) == "{{inputs.username}}"
    assert parameterize("1002", {"username": "alice"}) == "1002"


def spec():
    return FlowSpec(
        name="login", goal="Log in.", start_url="http://bank.example/index.htm",
        inputs={"username": InputSpec("string", secret=True)},
        outputs={},
    )


def test_emit_writes_a_recording_the_phase_one_loader_accepts(tmp_path):
    """Changing emitted recording keys or target conversion breaks Phase 1 replay."""
    trace = Trace(spec=spec(), status="success")
    trace.steps.append(TraceStep(action="fill", ref="e1", role="textbox", name="", value="alice"))
    states = {
        "login_page": State("login_page", r"/index\.htm", '- heading "Customer Login"'),
        "overview": State("overview", r"/overview\.htm", '- heading "Accounts Overview"'),
    }

    text = emit(
        trace, states, step_targets=[[Target(css="#username")]],
        step_states=[("login_page", "overview")],
        supplied_inputs={"username": "alice"},
    )

    data = yaml.safe_load(text)
    assert data["flow"] == "login"
    assert data["inputs"]["username"] == {"type": "string", "secret": True}
    assert data["steps"][0]["value"] == "{{inputs.username}}"
    assert data["steps"][0]["target"] == [{"css": "#username"}]
    assert data["steps"][0]["to"] == "overview"

    path = tmp_path / "login.yaml"
    path.write_text(text)
    from replaykit.recording.loader import load_flow

    flow = load_flow(path)
    assert flow.steps[0].target[0].css == "#username"


def test_emit_promotes_discovery_extracts_to_declared_output_extractors():
    """Leaving extract calls in steps makes replay reject an otherwise valid output flow."""
    output_spec = FlowSpec(
        name="overview", goal="Read the balance.", start_url="http://bank.example/overview.htm",
        inputs={}, outputs={"balance": OutputSpec("decimal")},
    )
    trace = Trace(
        spec=output_spec,
        steps=[TraceStep(action="extract", ref="e1", role="paragraph", name="Balance", output_name="balance")],
    )
    states = {"overview": State("overview", r"/overview\.htm", '- heading "Accounts Overview"')}

    data = yaml.safe_load(
        emit(
            trace, states, step_targets=[[Target(css="#balance")]],
            step_states=[("overview", None)],
        )
    )

    assert data["outputs"] == {"balance": {"type": "decimal"}}
    assert data["extract"] == [{
        "from": "overview", "target": [{"css": "#balance"}], "outputs": ["balance"],
    }]
    assert data["steps"] == []
