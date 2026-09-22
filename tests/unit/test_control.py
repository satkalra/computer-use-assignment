import json
import threading
import time

from replaykit.control import (
    ControlState,
    InterventionRequest,
    _capture_human_actions,
    await_approval,
    intervene,
)


class Page:
    url = "http://bank.example/overview.htm"

    def screenshot(self):
        return b"png-bytes"

    def expose_binding(self, name, fn):
        pass

    def add_init_script(self, script):
        pass

    def evaluate(self, script):
        pass


def test_intervene_returns_false_immediately_with_no_control_attached(tmp_path):
    request = InterventionRequest(
        capability="login", goal="log in", step_index=1, reason="stuck",
        url="http://bank.example/overview.htm", screenshot_base64=None,
    )

    resumed = intervene(Page(), set(), request, None, tmp_path)

    assert resumed is False
    assert json.loads((tmp_path / "intervention.json").read_text())["reason"] == "stuck"


def test_intervene_blocks_until_a_decision_then_resumes_control_to_agent(tmp_path):
    control = ControlState()
    request = InterventionRequest(
        capability="login", goal="log in", step_index=1, reason="stuck",
        url="http://bank.example/overview.htm", screenshot_base64=None,
    )

    def decide_after_a_moment():
        time.sleep(0.05)
        control.decision = "resume"

    threading.Thread(target=decide_after_a_moment).start()
    resumed = intervene(Page(), set(), request, control, tmp_path)

    assert resumed is True
    assert control.owner == "agent"
    assert control.decision is None


def test_intervene_reports_abort(tmp_path):
    control = ControlState()
    request = InterventionRequest(
        capability="login", goal="log in", step_index=1, reason="stuck",
        url="http://bank.example/overview.htm", screenshot_base64=None,
    )
    threading.Thread(target=lambda: (time.sleep(0.05), setattr(control, "decision", "abort"))).start()

    assert intervene(Page(), set(), request, control, tmp_path) is False


def test_await_approval_returns_false_with_no_operator(tmp_path):
    assert await_approval(Page(), set(), "risky action", None, tmp_path) is False


def test_intervene_registers_human_action_capture_once_per_page(tmp_path):
    class CountingPage(Page):
        def __init__(self):
            self.bindings = 0

        def expose_binding(self, name, fn):
            self.bindings += 1

    page = CountingPage()
    control = ControlState()
    request = InterventionRequest("login", "log in", 1, "stuck", page.url, None)

    for _ in range(2):
        threading.Thread(
            target=lambda: (time.sleep(0.01), setattr(control, "decision", "resume"))
        ).start()
        assert intervene(page, set(), request, control, tmp_path) is True

    assert page.bindings == 1


def test_capture_human_actions_logs_a_real_click(page, pages_url, tmp_path):
    log_path = tmp_path / "human_actions.jsonl"
    _capture_human_actions(page, log_path, secret_field_names=set())
    page.goto(f"{pages_url}/login.html")

    page.click("button")

    lines = log_path.read_text().strip().splitlines()
    assert any(json.loads(line)["event"] == "click" for line in lines)


def test_capture_human_actions_logs_a_click_on_a_page_already_loaded_before_capture_starts(page, pages_url, tmp_path):
    """This is the real handoff sequence: the page is already stuck and loaded
    *before* intervene() ever runs. add_init_script alone only covers the next
    navigation, so a click made without navigating away must still be caught."""
    page.goto(f"{pages_url}/login.html")
    log_path = tmp_path / "human_actions.jsonl"

    _capture_human_actions(page, log_path, secret_field_names=set())
    page.click("button")

    lines = log_path.read_text().strip().splitlines()
    assert any(json.loads(line)["event"] == "click" for line in lines)
