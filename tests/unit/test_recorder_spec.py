import pytest

from replaykit.recorder.spec import FlowSpec, InputSpec, OutputSpec


def test_flow_spec_exposes_secret_input_names():
    spec = FlowSpec(
        name="accounts_overview", goal="Log in and read the first account balance.",
        start_url="http://bank.example/index.htm",
        inputs={"username": InputSpec("string", secret=True), "password": InputSpec("string", secret=True)},
        outputs={"balance": OutputSpec("decimal")},
    )

    assert spec.secret_inputs() == {"username", "password"}
    assert spec.reset is None


def test_flow_spec_rejects_an_output_type_it_cannot_validate():
    with pytest.raises(ValueError, match="unsupported output type"):
        FlowSpec(
            name="f", goal="g", start_url="http://bank.example/",
            inputs={}, outputs={"balance": OutputSpec("money")},
        )
