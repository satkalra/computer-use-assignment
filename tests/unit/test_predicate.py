from replaykit.recording.schema import State
from replaykit.states.predicate import matches, wait_for


LOGIN = State("login", r"/login\.html", '- heading "Customer Login"')
OVERVIEW = State("overview", r"/overview\.html", '- heading "Accounts Overview"')


def test_matches_requires_both_url_and_aria_template(page, pages_url):
    page.goto(f"{pages_url}/login.html")

    assert matches(page, LOGIN) is True
    assert matches(page, OVERVIEW) is False


def test_wait_for_returns_false_when_the_state_never_arrives(page, pages_url):
    page.goto(f"{pages_url}/login.html")

    assert wait_for(page, OVERVIEW, timeout_ms=100) is False
