from replaykit.compiler.states import ObservedState, anchor, build_states, discriminates, observed_states
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


def test_observed_states_collapses_visits_with_different_ai_mode_refs():
    """ai-mode assigns a fresh ref to every element on every capture (e29,
    f1e29, f2e29, ...), so two visits to the literal same page never match
    on raw text. Identity has to ignore refs or every revisit looks new."""
    steps = [
        _step("/login.htm", "/login.htm",
              "- heading \"Login\" [ref=e29]", "- heading \"Login\" [ref=f1e29]"),
        _step("/login.htm", "/overview.htm",
              "- heading \"Login\" [ref=f1e29]", "- heading \"Overview\" [ref=f2e10]"),
    ]

    states = observed_states(steps)

    assert [s.url for s in states] == ["/login.htm", "/overview.htm"]


def test_observed_states_keeps_the_fuller_snapshot_on_a_repeat_visit():
    """Confirmed live: ParaBank's account table renders a moment after the
    page loads, so an early capture is a strict subset of a later one on the
    same page. If observed_states() kept the first (partial) capture, no
    template built from it could ever discriminate against the fuller one."""
    partial = '- heading "Accounts Overview"\n- table:\n  - row:\n    - cell "*note"'
    full = ('- heading "Accounts Overview"\n- table:\n  - row:\n    - cell "12345"\n'
            '    - cell "$10.00"\n  - row:\n    - cell "*note"')
    steps = [
        _step("/overview.htm", "/overview.htm", partial, full),
    ]

    states = observed_states(steps)

    assert len(states) == 1
    assert states[0].snapshot == full


def test_observed_states_collapses_visits_that_differ_only_inside_a_container_line():
    """A combobox's current selection lives inside its own nested container
    line, which isn't part of the anchor. Two visits to the same form that
    differ only in what's selected must still be one state."""
    before = '- heading "Open New Account"\n- combobox:\n  - option "CHECKING"'
    after = '- heading "Open New Account"\n- combobox:\n  - option "SAVINGS"'
    steps = [_step("/openaccount.htm", "/openaccount.htm", before, after)]

    states = observed_states(steps)

    assert len(states) == 1


def test_anchor_prefers_the_first_heading_over_other_content():
    assert anchor('- paragraph: noise\n- heading "Accounts Overview"\n- button "Go"') \
        == '- heading "Accounts Overview"'


def test_anchor_prefers_a_level_1_heading_over_a_shared_nav_heading():
    """ParaBank's left-nav 'Account Services' [level=2] heading precedes the
    page's own [level=1] title in every authenticated page's document order.
    Confirmed live: preferring the first heading regardless of level picked
    that shared nav heading -- identical on every page -- so a form and its
    own in-place confirmation (same URL, ParaBank swaps content without
    navigating) wrongly anchored to the same identity, corrupting the
    precondition for every step recorded against the form."""
    form = '- heading "Account Services" [level=2]\n- heading "Transfer Funds" [level=1]'
    confirmation = '- heading "Account Services" [level=2]\n- heading "Transfer Complete!" [level=1]'

    assert anchor(form) == '- heading "Transfer Funds" [level=1]'
    assert anchor(confirmation) == '- heading "Transfer Complete!" [level=1]'


def test_observed_states_keeps_a_form_and_its_own_confirmation_distinct():
    form = '- heading "Account Services" [level=2]\n- heading "Transfer Funds" [level=1]'
    confirmation = '- heading "Account Services" [level=2]\n- heading "Transfer Complete!" [level=1]'
    steps = [_step("/transfer.htm", "/transfer.htm", form, confirmation)]

    states = observed_states(steps)

    assert len(states) == 2


def test_anchor_skips_bare_colon_container_lines():
    assert anchor('- link "about":\n- heading "Customer Login" [level=2]') \
        == '- heading "Customer Login" [level=2]'


def test_observed_states_strips_active_focus_markers():
    """[active] reflects momentary DOM focus, not a durable property of the
    page. Confirmed live: a widened template that includes it can fail to
    match on a freshly loaded page at replay time, even though the page is
    genuinely the same state."""
    steps = [_step("/login.htm", "/login.htm",
                    '- textbox [active]\n- heading "Login"', '- textbox [active]\n- heading "Login"')]

    states = observed_states(steps)

    assert "[active]" not in states[0].snapshot


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
