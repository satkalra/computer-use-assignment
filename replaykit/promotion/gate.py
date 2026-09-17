from dataclasses import dataclass, field

from replaykit.recording.schema import Flow
from replaykit.replayer.engine import ReplayEngine
from replaykit.replayer.extract import validate_outputs


@dataclass(frozen=True)
class GateRun:
    user: str
    status: str
    outputs: dict[str, str] | None
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GateReport:
    passed: bool
    runs: list[GateRun]
    recording_yaml: str
    summary: str


def summarize(runs: list[GateRun], recording_yaml: str) -> GateReport:
    """Produce a promotion decision and a concise per-run diagnostic report."""
    failures = [run for run in runs if run.status != "success" or run.errors]
    lines = [
        f"{run.user}: {run.status}"
        + (f" — {'; '.join(run.errors)}" if run.errors else "")
        for run in runs
    ]
    return GateReport(
        passed=not failures and bool(runs),
        runs=runs,
        recording_yaml=recording_yaml,
        summary="\n".join(lines),
    )


def run_gate(
    browser,
    flow: Flow,
    spec,
    credentials: list[dict[str, str]],
    recording_yaml: str,
    repeats: int = 3,
) -> GateReport:
    """Replay a recording repeatedly through the Phase 1 engine before promotion."""
    if repeats <= 0:
        raise ValueError("repeats must be positive")
    if spec.reset is None and not credentials:
        raise ValueError("credentials are required when the flow has no reset hook")

    runs: list[GateRun] = []
    for index in range(repeats):
        inputs = spec.reset() if spec.reset else credentials[index % len(credentials)]
        page = browser.new_page()
        try:
            page.goto(spec.start_url)
            result = ReplayEngine().run(page, flow, inputs)
        finally:
            page.close()
        errors = (
            validate_outputs(result.outputs or {}, flow.outputs)
            if result.status == "success"
            else [result.handoff.reason] if result.handoff else []
        )
        runs.append(
            GateRun(
                user=inputs.get("username", f"run{index}"),
                status=result.status,
                outputs=result.outputs,
                errors=errors,
            )
        )
    return summarize(runs, recording_yaml)
