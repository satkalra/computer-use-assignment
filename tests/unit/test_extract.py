from replaykit.recording.schema import Extract, Flow, Output, State, Target
from replaykit.replayer.extract import run_extractors, validate_outputs


def flow_with_extract():
    return Flow(
        "overview", 1, {}, {"overview": State("overview", r"/overview\.html", "- heading")}, [],
        extract=[Extract(from_state="overview", target=[Target(css="h1")],
                         parse=r"Accounts (\w+)", outputs=["word"])],
        outputs={"word": Output("string")},
    )


def test_run_extractors_applies_the_declared_regex(page, pages_url):
    page.goto(f"{pages_url}/overview.html")

    assert run_extractors(page, flow_with_extract()) == {"word": "Overview"}


def test_validate_outputs_rejects_a_balance_that_is_not_a_decimal():
    errors = validate_outputs({"balance": "not-money"}, {"balance": Output("decimal")})

    assert errors and "balance" in errors[0]


def test_validate_outputs_accepts_a_well_formed_decimal():
    assert validate_outputs({"balance": "$4,215.10"}, {"balance": Output("decimal")}) == []


def test_validate_outputs_reports_a_missing_declared_output():
    errors = validate_outputs({}, {"balance": Output("decimal")})

    assert errors and "missing" in errors[0]
