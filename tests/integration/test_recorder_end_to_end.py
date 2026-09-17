import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from replaykit.compiler import compile_trace
from replaykit.flows.specs import ALL_FLOWS, BASE_URL
from replaykit.harness.seed import seed_users
from replaykit.promotion.gate import run_gate
from replaykit.recorder.session import record
from replaykit.recording.loader import load_flow


RECORDINGS = Path(__file__).parents[2] / "replaykit" / "flows"


def _client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY is not configured; no model call attempted")
    import anthropic

    return anthropic.Anthropic(api_key=key)


@pytest.mark.slow
@pytest.mark.parametrize("spec", ALL_FLOWS, ids=lambda item: item.name)
def test_recorder_produces_a_recording_that_passes_the_promotion_gate(spec, tmp_path):
    """Only accept recordings created by discovery and validated by three replays."""
    client = _client()
    users = seed_users(BASE_URL)
    inputs = {"username": users[0].username, "password": users[0].password}
    if "amount" in spec.inputs:
        inputs["amount"] = "1.00"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(spec.start_url)
            trace = record(page, spec, inputs, client)
            assert trace.status == "success", f"discovery did not finish: {trace}"

            yaml_text = compile_trace(page, trace, inputs)
            page.close()
            path = tmp_path / f"{spec.name}.yaml"
            path.write_text(yaml_text)
            flow = load_flow(path)

            credentials = [
                {
                    "username": user.username,
                    "password": user.password,
                    **({"amount": "1.00"} if "amount" in spec.inputs else {}),
                }
                for user in users[:3]
            ]
            report = run_gate(browser, flow, spec, credentials, yaml_text, repeats=3)
        finally:
            browser.close()

    assert report.passed, f"promotion gate failed for {spec.name}:\n{report.summary}"
    (RECORDINGS / f"{spec.name}.yaml").write_text(yaml_text)
