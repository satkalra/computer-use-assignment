import json
import time
from dataclasses import dataclass, field
from pathlib import Path


_POLL_INTERVAL_S = 0.1


@dataclass
class ControlState:
    owner: str = "agent"
    request: dict | None = None
    decision: str | None = None
    captured_page_ids: set[int] = field(default_factory=set, repr=False)


@dataclass(frozen=True)
class InterventionRequest:
    capability: str
    goal: str
    step_index: int
    reason: str
    url: str
    screenshot_base64: str | None
    handoff: dict | None = None

    def to_dict(self) -> dict:
        return {
            "capability": self.capability,
            "goal": self.goal,
            "step_index": self.step_index,
            "reason": self.reason,
            "url": self.url,
            "screenshot_base64": self.screenshot_base64,
            "handoff": self.handoff,
        }


_LISTENER_SCRIPT = """
(() => {
  const send = (event, target) => window.__replaykit_capture({
    event, role: target.getAttribute('role') || target.tagName.toLowerCase(),
    accessible_name: target.getAttribute('aria-label') || target.name || target.id || '',
    field_name: target.name || '', input_type: target.type || '',
    value: target.type === 'password' ? '' : (target.value ?? ''),
  });
  document.addEventListener('click', (e) => send('click', e.target), true);
  document.addEventListener('change', (e) => send('change', e.target), true);
  document.addEventListener('submit', (e) => send('submit', e.target), true);
})();
"""


def _capture_human_actions(page, log_path: Path, secret_field_names: set[str]) -> None:
    def on_action(_source, payload: dict) -> None:
        if payload.get("field_name") in secret_field_names or payload.get("input_type") == "password":
            payload["value"] = "[REDACTED]"
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({**payload, "ts": time.time()}, sort_keys=True) + "\n")

    page.expose_binding("__replaykit_capture", on_action)
    # add_init_script only takes effect on the *next* navigation -- a handoff
    # happens on a page that's already loaded and stuck, so without also
    # evaluating the same script right now, the human's actions on that exact
    # page would never be captured at all.
    page.add_init_script(_LISTENER_SCRIPT)
    page.evaluate(_LISTENER_SCRIPT)


def _capture_human_actions_once(
    page, control: ControlState, log_path: Path, secret_field_names: set[str],
) -> None:
    if id(page) in control.captured_page_ids:
        return
    _capture_human_actions(page, log_path, secret_field_names)
    control.captured_page_ids.add(id(page))


def _wait_for_decision(control: ControlState) -> str:
    control.owner = "human"
    while control.decision is None:
        time.sleep(_POLL_INTERVAL_S)
    decision = control.decision
    control.decision = None
    control.owner = "agent"
    return decision


def intervene(
    page, secret_field_names: set[str], request: InterventionRequest,
    control: ControlState | None, evidence_dir: Path,
) -> bool:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "intervention.json").write_text(
        json.dumps(request.to_dict(), indent=2, sort_keys=True)
    )
    if control is None:
        return False
    control.request = request.to_dict()
    _capture_human_actions_once(
        page, control, evidence_dir / "human_actions.jsonl", secret_field_names,
    )
    decision = _wait_for_decision(control)
    control.request = None
    return decision == "resume"


def await_approval(
    page, secret_field_names: set[str], reason: str,
    control: ControlState | None, evidence_dir: Path,
) -> bool:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "intervention.json").write_text(
        json.dumps({"reason": reason, "url": page.url}, indent=2)
    )
    if control is None:
        return False
    control.request = {"reason": reason, "url": page.url}
    _capture_human_actions_once(
        page, control, evidence_dir / "human_actions.jsonl", secret_field_names,
    )
    decision = _wait_for_decision(control)
    control.request = None
    return decision == "resume"
