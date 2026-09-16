import hashlib
import re
import time
from dataclasses import dataclass

from replaykit.locators.ladder import UnresolvableTarget, resolve
from replaykit.recording.schema import Flow, Step
from replaykit.replayer.handoff import HandoffRecord, build_handoff
from replaykit.replayer.recovery import recover
from replaykit.states.predicate import wait_for


@dataclass(frozen=True)
class ReplayResult:
    status: str
    step_index: int
    handoff: HandoffRecord | None = None


def _interpolate(value: str, inputs: dict[str, str]) -> str:
    match = re.fullmatch(r"\{\{inputs\.([A-Za-z_][A-Za-z0-9_]*)\}\}", value)
    if match is None:
        return value
    name = match.group(1)
    if name not in inputs:
        raise ValueError(f"recording requires missing input {name!r}")
    return inputs[name]


def _snapshot_hash(page) -> str:
    try:
        snapshot = page.locator("body").aria_snapshot()
    except Exception:
        snapshot = ""
    return hashlib.sha256(snapshot.encode()).hexdigest()


def _outcomes(error: Exception) -> list[dict]:
    if not isinstance(error, UnresolvableTarget):
        return []
    return [
        {"candidate": repr(item.candidate), "count": item.count, "error": item.error}
        for item in error.outcomes
    ]


class ReplayEngine:
    def __init__(self, audit_log=None):
        self.audit_log = audit_log

    def _audit(self, *, step_index: int, rung: int | None, page, started: float, outcome: str) -> None:
        if self.audit_log is not None:
            self.audit_log.append(
                step_index=step_index, rung=rung, snapshot_hash=_snapshot_hash(page),
                duration_ms=round((time.monotonic() - started) * 1000), outcome=outcome,
            )

    @staticmethod
    def _act(locator, step: Step, inputs: dict[str, str]) -> None:
        if step.action == "click":
            locator.click()
        elif step.action == "fill":
            locator.fill(_interpolate(step.value or "", inputs))
        elif step.action == "select":
            locator.select_option(_interpolate(step.value or "", inputs))
        else:
            raise ValueError(f"unsupported action {step.action!r}")

    def run(self, page, flow: Flow, inputs: dict[str, str]) -> ReplayResult:
        run_started = time.monotonic()
        for index, step in enumerate(flow.steps):
            step_started = time.monotonic()
            from_state = flow.states[step.from_state]
            handoff_state = from_state
            rung: int | None = None
            ladder_outcomes: list[dict] = []
            reason = ""
            for attempt in range(2):
                if not wait_for(page, from_state, step.timeout_ms):
                    reason = "precondition failed"
                    handoff_state = from_state
                else:
                    try:
                        locator, rung = resolve(page, step.target)
                        self._act(locator, step, inputs)
                    except Exception as exc:
                        reason = f"action or target failed: {exc}"
                        ladder_outcomes = _outcomes(exc)
                        self._audit(step_index=index, rung=rung, page=page, started=step_started, outcome="handoff")
                        return ReplayResult(
                            "handoff", index,
                            build_handoff(
                                page, flow, step_index=index, expected_state=from_state, inputs=inputs,
                                ladder_outcomes=ladder_outcomes,
                                timings={"step_ms": round((time.monotonic() - step_started) * 1000), "total_ms": round((time.monotonic() - run_started) * 1000)},
                                reason=reason,
                            ),
                        )
                    if step.to is None or wait_for(page, flow.states[step.to], step.timeout_ms):
                        self._audit(step_index=index, rung=rung, page=page, started=step_started, outcome="success")
                        break
                    handoff_state = flow.states[step.to]
                    reason = "postcondition failed"
                if attempt == 0:
                    recovery = recover(page, flow)
                    if recovery.session_expired:
                        # Detection-only (spec 4.4): a second precondition check can never
                        # succeed here, so stop now instead of letting it overwrite this
                        # diagnosis with a generic "precondition failed" on the next loop.
                        self._audit(step_index=index, rung=rung, page=page, started=step_started, outcome="handoff")
                        return ReplayResult(
                            "handoff", index,
                            build_handoff(
                                page, flow, step_index=index, expected_state=handoff_state, inputs=inputs,
                                ladder_outcomes=ladder_outcomes,
                                timings={"step_ms": round((time.monotonic() - step_started) * 1000), "total_ms": round((time.monotonic() - run_started) * 1000)},
                                reason="session expired; sub-flow recovery is not supported in this version",
                            ),
                        )
                    continue
                self._audit(step_index=index, rung=rung, page=page, started=step_started, outcome="handoff")
                return ReplayResult(
                    "handoff", index,
                    build_handoff(
                        page, flow, step_index=index, expected_state=handoff_state, inputs=inputs,
                        ladder_outcomes=ladder_outcomes,
                        timings={"step_ms": round((time.monotonic() - step_started) * 1000), "total_ms": round((time.monotonic() - run_started) * 1000)},
                        reason=reason,
                    ),
                )
            else:
                raise AssertionError("unreachable retry loop")
        return ReplayResult("success", len(flow.steps))
