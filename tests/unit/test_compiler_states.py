from replaykit.compiler.states import ObservedState, build_states, discriminates, observed_states
from replaykit.recorder.trace import TraceStep


def _step(url_before, url_after, snap_before, snap_after):
    return TraceStep(action="click", ref="e1", role="button", name="Go",
                     url_before=url_before, url_after=url_after,
                     snapshot_before=snap_before, snapshot_after=snap_after)


def test_observed_states_collapses_repeated_visits_to_one_state():
    steps = [
        _step("/login.htm", "/login.htm", "- heading \"Login\"", "- heading \"Login\""),
        _step("/login.htm", "/overview.htm", "- heading \"Login\"", "- heading \"Overview\""),
    ]

    states = observed_states(steps)

    assert [s.url for s in states] == ["/login.htm", "/overview.htm"]


def test_discriminates_rejects_a_template_matching_another_state():
    assert discriminates("- heading \"Overview\"", own="- heading \"Overview\"",
                         others=["- heading \"Login\""]) is True
    # a template so loose it matches everything is exactly the false-success risk
    assert discriminates("- heading", own="- heading \"Overview\"",
                         others=["- heading \"Login\""]) is False


def test_build_states_produces_phase_one_state_objects():
    states = build_states({"overview": (r"/overview\.htm", "- heading \"Overview\"")})

    assert states["overview"].name == "overview"
    assert states["overview"].url == r"/overview\.htm"
    assert states["overview"].aria == "- heading \"Overview\""
