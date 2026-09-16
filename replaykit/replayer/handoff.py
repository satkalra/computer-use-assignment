import base64
from dataclasses import asdict, dataclass

from replaykit.recording.schema import Flow, Input, State


def redact_inputs(inputs: dict[str, str], declarations: dict[str, Input]) -> dict[str, str]:
    return {name: "[REDACTED]" if declarations.get(name, Input("string")).secret else value for name, value in inputs.items()}


def _snapshot(page) -> str | None:
    try:
        return page.locator("body").aria_snapshot()
    except Exception:
        return None


def _screenshot(page) -> str | None:
    try:
        return base64.b64encode(page.screenshot()).decode("ascii")
    except Exception:
        return None


@dataclass(frozen=True)
class HandoffRecord:
    flow: str
    version: int
    step_index: int
    expected_state: dict[str, str]
    actual_url: str
    actual_aria_snapshot: str | None
    screenshot_base64: str | None
    ladder_outcomes: list[dict]
    timings: dict[str, int]
    inputs: dict[str, str]
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def build_handoff(page, flow: Flow, *, step_index: int, expected_state: State, inputs: dict[str, str], ladder_outcomes: list[dict], timings: dict[str, int], reason: str) -> HandoffRecord:
    return HandoffRecord(
        flow=flow.name, version=flow.version, step_index=step_index,
        expected_state={"name": expected_state.name, "template": expected_state.aria},
        actual_url=page.url, actual_aria_snapshot=_snapshot(page), screenshot_base64=_screenshot(page),
        ladder_outcomes=ladder_outcomes, timings=timings,
        inputs=redact_inputs(inputs, flow.inputs), reason=reason,
    )
