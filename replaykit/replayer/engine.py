import hashlib
import re
import time
from dataclasses import dataclass

from replaykit.locators.ladder import UnresolvableTarget, resolve
from replaykit.policy.policy import ApprovalRequired, Policy, check
from replaykit.recording.schema import Flow, Outcome, Step
from replaykit.replayer.extract import run_extractors, validate_outputs
from replaykit.replayer.handoff import HandoffRecord, build_handoff
from replaykit.replayer.recovery import recover
from replaykit.states.predicate import matches, wait_for


@dataclass(frozen=True)
class ReplayResult:
    status: str
    step_index: int
    handoff: HandoffRecord | None = None
    outputs: dict[str, str] | None = None
    outcome: str | None = None
    approval_reason: str | None = None


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


def _match_declared_outcome(page, flow: Flow) -> tuple[str, Outcome] | None:
    for name, outcome in flow.outcomes.items():
        if matches(page, flow.states[outcome.state]):
            return name, outcome
    return None


def _extract_outcome_fields(page, outcome: Outcome) -> dict[str, str]:
    values = {}
    for field_name, field in outcome.extract.items():
        locator, _rung = resolve(page, [field.target])
        values[field_name] = locator.inner_text().strip()
    return values


def _describe_target(step: Step) -> str:
    target = step.target[0]
    return target.name or ""


def find_resume_index(page, flow: Flow, min_index: int = 0) -> int:
    # Searching from 0 would return the *first* step whose state matches --
    # wrong whenever multiple steps share a state (e.g. several fields on one
    # login page), since that's always the earliest, already-completed one.
    # min_index pins the search to "at or after where we got stuck," so resume
    # never re-executes a step that already ran once.
    for index, step in enumerate(flow.steps[min_index:], start=min_index):
        if matches(page, flow.states[step.from_state]):
            return index
    return min_index


class ReplayEngine:
    def __init__(self, audit_log=None, policy: Policy | None = None, approved: set[int] = frozenset()):
        self.audit_log = audit_log
        self.policy = policy
        self.approved = approved

    def _audit(self, *, step_index: int, rung: int | None, page, started: float, outcome: str) -> None:
        if self.audit_log is not None:
            self.audit_log.append(
                step_index=step_index, rung=rung, snapshot_hash=_snapshot_hash(page),
                duration_ms=round((time.monotonic() - started) * 1000), outcome=outcome,
            )

    def _act(self, page, locator, step: Step, inputs: dict[str, str], step_index: int) -> None:
        if self.policy is not None:
            check(
                self.policy, url=page.url, action=step.action,
                target_name=_describe_target(step), approved=self.approved,
                step_index=step_index,
            )
        if step.action == "click":
            locator.click()
        elif step.action == "fill":
            locator.fill(_interpolate(step.value or "", inputs))
        elif step.action == "select":
            locator.select_option(_interpolate(step.value or "", inputs))
        else:
            raise ValueError(f"unsupported action {step.action!r}")

    def run(self, page, flow: Flow, inputs: dict[str, str], start_index: int = 0) -> ReplayResult:
        run_started = time.monotonic()
        for index, step in enumerate(flow.steps[start_index:], start=start_index):
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
                        self._act(page, locator, step, inputs, index)
                    except ApprovalRequired as exc:
                        self._audit(
                            step_index=index, rung=rung, page=page,
                            started=step_started, outcome="needs_approval",
                        )
                        return ReplayResult("needs_approval", index, approval_reason=str(exc))
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
                    matched = _match_declared_outcome(page, flow)
                    if matched is not None:
                        outcome_name, outcome = matched
                        self._audit(step_index=index, rung=rung, page=page, started=step_started, outcome="business_outcome")
                        return ReplayResult(
                            "business_outcome", index, outcome=outcome_name,
                            outputs=_extract_outcome_fields(page, outcome),
                        )
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
        if not flow.extract:
            return ReplayResult("success", len(flow.steps))
        expected_state = flow.states[flow.steps[-1].to or flow.steps[-1].from_state]
        try:
            values = run_extractors(page, flow)
        except Exception as exc:
            return ReplayResult(
                "handoff", len(flow.steps),
                build_handoff(
                    page, flow, step_index=len(flow.steps), expected_state=expected_state,
                    inputs=inputs, ladder_outcomes=[],
                    timings={"step_ms": 0, "total_ms": round((time.monotonic() - run_started) * 1000)},
                    reason=f"extraction failed: {exc}",
                ),
            )
        errors = validate_outputs(values, flow.outputs)
        if errors:
            return ReplayResult(
                "handoff", len(flow.steps),
                build_handoff(
                    page, flow, step_index=len(flow.steps), expected_state=expected_state,
                    inputs=inputs, ladder_outcomes=[],
                    timings={"step_ms": 0, "total_ms": round((time.monotonic() - run_started) * 1000)},
                    reason=f"output validation failed: {'; '.join(errors)}",
                ),
                outputs=values,
            )
        return ReplayResult("success", len(flow.steps), outputs=values)
