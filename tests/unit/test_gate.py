from replaykit.promotion.gate import GateRun, summarize
from replaykit.recorder.spec import FlowSpec, InputSpec, OutputSpec


def spec_with_reset(calls):
    return FlowSpec(
        name="transfer", goal="Move money.", start_url="http://bank.example/",
        inputs={"username": InputSpec("string", secret=True)},
        outputs={"balance": OutputSpec("decimal")},
        reset=lambda: (calls.append(1), {"username": f"user{len(calls)}"})[1],
    )


def test_summarize_passes_only_when_every_run_succeeded():
    runs = [GateRun("u1", "success", {"balance": "$1.00"}, []),
            GateRun("u2", "success", {"balance": "$2.00"}, [])]

    assert summarize(runs, "flow: transfer\n").passed is True


def test_summarize_fails_when_any_run_handed_off():
    runs = [GateRun("u1", "success", {"balance": "$1.00"}, []),
            GateRun("u2", "handoff", None, ["precondition failed at step 2"])]

    report = summarize(runs, "flow: transfer\n")

    assert report.passed is False
    assert "u2" in report.summary


def test_summarize_fails_when_outputs_are_invalid_even_if_replay_succeeded():
    runs = [GateRun("u1", "success", {"balance": "nonsense"}, ["output 'balance' is not a decimal"])]

    assert summarize(runs, "flow: transfer\n").passed is False


def test_a_reset_hook_is_invoked_once_per_replay():
    calls = []
    spec = spec_with_reset(calls)

    credentials = [spec.reset() for _ in range(3)]

    assert len(calls) == 3
    assert credentials[0]["username"] == "user1"

