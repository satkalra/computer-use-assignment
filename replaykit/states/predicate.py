import re

from playwright.sync_api import TimeoutError, expect

from replaykit.recording.schema import State


def matches(page, state: State) -> bool:
    """Return whether the current page meets both parts of a named state."""
    if re.search(state.url, page.url) is None:
        return False
    try:
        expect(page).to_match_aria_snapshot(state.aria, timeout=100)
    except (AssertionError, TimeoutError):
        return False
    return True


def wait_for(page, state: State, timeout_ms: int) -> bool:
    """Use Playwright's URL and aria assertions as the state wait primitives."""
    try:
        page.wait_for_url(re.compile(state.url), timeout=timeout_ms)
        expect(page).to_match_aria_snapshot(state.aria, timeout=timeout_ms)
    except (AssertionError, TimeoutError):
        return False
    return True
