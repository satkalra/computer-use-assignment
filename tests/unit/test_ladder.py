import pytest

from replaykit.locators.ladder import AmbiguousTarget, UnresolvableTarget, resolve
from replaykit.recording.schema import Target


def test_resolve_returns_first_unique_candidate_and_one_based_rung(page, pages_url):
    page.goto(f"{pages_url}/login.html")

    locator, rung = resolve(page, [Target(role="button", name="Log In"), Target(css="#username")])

    assert rung == 1
    assert locator.inner_text() == "Log In"


def test_resolve_falls_through_to_later_candidate(page, pages_url):
    page.goto(f"{pages_url}/login.html")

    locator, rung = resolve(page, [Target(role="textbox", name="Username"), Target(css="#username")])

    assert rung == 2
    assert locator.get_attribute("name") == "username"


def test_resolve_raises_for_an_ambiguous_candidate(page, pages_url):
    page.goto(f"{pages_url}/login.html")

    with pytest.raises(AmbiguousTarget, match="2"):
        resolve(page, [Target(css="input")])


def test_resolve_reports_every_exhausted_candidate(page, pages_url):
    page.goto(f"{pages_url}/login.html")

    with pytest.raises(UnresolvableTarget) as failure:
        resolve(page, [Target(css="#missing"), Target(xpath="//button[@name='missing']")])

    assert [outcome.count for outcome in failure.value.outcomes] == [0, 0]
