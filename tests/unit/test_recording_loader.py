from pathlib import Path

import pytest

from replaykit.recording.loader import RecordingValidationError, load_flow


def write_recording(tmp_path: Path, contents: str) -> Path:
    path = tmp_path / "flow.yaml"
    path.write_text(contents)
    return path


VALID_FLOW = """
flow: login
version: 1
inputs:
  username: {type: string, secret: true}
  password: {type: string, secret: true}
states:
  login_page: {url: /login\\.htm, aria: '- heading "Customer Login"'}
  accounts_overview: {url: /overview\\.htm, aria: '- heading "Accounts Overview"'}
steps:
  - from: login_page
    action: fill
    target: [{css: 'input[name=username]'}]
    value: '{{inputs.username}}'
  - from: login_page
    action: click
    target: [{role: button, name: 'Log In'}]
    to: accounts_overview
recovery: []
"""


def test_load_flow_builds_typed_recording(tmp_path):
    flow = load_flow(write_recording(tmp_path, VALID_FLOW))

    assert flow.name == "login"
    assert flow.inputs["password"].secret is True
    assert flow.steps[0].target[0].css == "input[name=username]"
    assert flow.steps[1].to == "accounts_overview"


def test_load_flow_rejects_deferred_schema_keys(tmp_path):
    path = write_recording(tmp_path, VALID_FLOW + "uses: [login]\n")

    with pytest.raises(RecordingValidationError, match="uses.*not supported in this version"):
        load_flow(path)


def test_load_flow_parses_declared_extractors_and_outputs(tmp_path):
    flow = load_flow(write_recording(
        tmp_path,
        VALID_FLOW + """
outputs:
  balance: {type: decimal}
extract:
  - from: accounts_overview
    target: [{css: '#balance'}]
    parse: 'Balance: (.+)'
    outputs: [balance]
""",
    ))

    assert flow.outputs["balance"].type == "decimal"
    assert flow.extract[0].from_state == "accounts_overview"
    assert flow.extract[0].target[0].css == "#balance"


def test_load_flow_parses_declared_outcomes(tmp_path):
    flow = load_flow(write_recording(
        tmp_path,
        VALID_FLOW + """
outcomes:
  no_results:
    state: login_page
    extract:
      message: {css: '.error', type: string}
""",
    ))

    outcome = flow.outcomes["no_results"]
    assert outcome.state == "login_page"
    assert outcome.extract["message"].type == "string"
    assert outcome.extract["message"].target.css == ".error"


def test_load_flow_rejects_outcome_naming_unknown_state(tmp_path):
    path = write_recording(
        tmp_path,
        VALID_FLOW + "outcomes:\n  no_results:\n    state: not_a_state\n",
    )

    with pytest.raises(RecordingValidationError, match="outcomes.no_results.state names an unknown state"):
        load_flow(path)


def test_load_flow_rejects_missing_step_target(tmp_path):
    path = write_recording(
        tmp_path,
        VALID_FLOW.replace("    target: [{css: 'input[name=username]'}]\n", ""),
    )

    with pytest.raises(RecordingValidationError, match="target"):
        load_flow(path)


def test_load_flow_rejects_invalid_target_descriptor(tmp_path):
    path = write_recording(tmp_path, VALID_FLOW.replace("{css: 'input[name=username]'}", "{text: username}"))

    with pytest.raises(RecordingValidationError, match="one of role, css, xpath"):
        load_flow(path)


def test_load_flow_warns_for_credential_like_input_without_secret(tmp_path):
    path = write_recording(tmp_path, VALID_FLOW.replace("secret: true", "secret: false", 1))

    with pytest.warns(UserWarning, match="username.*secret"):
        load_flow(path)
