import os
import re
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from playwright.sync_api import sync_playwright

from replaykit.harness.faults import slow_response, strip_ids
from replaykit.harness.seed import seed_users
from replaykit.recording.loader import load_flow
from replaykit.replayer.engine import ReplayEngine


BASE_URL = os.environ.get("PARABANK_URL", "http://localhost:9099/parabank")
FLOW = Path(__file__).parents[2] / "replaykit" / "flows" / "login.yaml"
LLM_HOSTS = re.compile(r"https?://(?:api\.)?(?:openai|anthropic|cohere|generativelanguage)\.", re.I)


def require_parabank():
    try:
        with urlopen(f"{BASE_URL}/index.htm", timeout=3) as response:
            if response.status != 200:
                pytest.skip(f"ParaBank is unavailable at {BASE_URL}: HTTP {response.status}")
    except URLError:
        pytest.skip(f"ParaBank is unavailable at {BASE_URL}")


@pytest.mark.slow
def test_login_replays_100_times_against_ten_seeded_users_without_llm_calls():
    require_parabank()
    users = seed_users(BASE_URL)
    flow = load_flow(FLOW)
    outbound_llm_calls = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for repeat in range(10):
                for credentials in users:
                    context = browser.new_context()
                    context.route(LLM_HOSTS, lambda route: (outbound_llm_calls.append(route.request.url), route.abort()))
                    page = context.new_page()
                    page.goto(f"{BASE_URL}/index.htm")
                    result = ReplayEngine().run(page, flow, credentials.__dict__)
                    context.close()
                    assert result.status == "success", f"repeat {repeat}, user {credentials.username}: {result.handoff}"
        finally:
            browser.close()
    assert outbound_llm_calls == []


@pytest.mark.slow
def test_fault_injector_proofs_apply_to_live_parabank():
    require_parabank()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context()
            page = context.new_page()
            strip_ids(page)
            slow_response(page, "**/index.htm", delay_ms=10)
            page.goto(f"{BASE_URL}/index.htm")
            assert page.locator("[id]").count() == 0
            context.close()
        finally:
            browser.close()
