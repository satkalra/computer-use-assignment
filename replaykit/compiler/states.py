from dataclasses import dataclass

from replaykit.recording.schema import State


@dataclass(frozen=True)
class ObservedState:
    url: str
    snapshot: str


def observed_states(trace_steps) -> list[ObservedState]:
    """Distinct (url, snapshot) pairs, in first-seen order."""
    seen: list[ObservedState] = []
    for step in trace_steps:
        for url, snapshot in ((step.url_before, step.snapshot_before), (step.url_after, step.snapshot_after)):
            if not url:
                continue
            candidate = ObservedState(url=url, snapshot=snapshot)
            if candidate not in seen:
                seen.append(candidate)
    return seen


def _template_lines(template: str) -> list[str]:
    return [line.strip() for line in template.splitlines() if line.strip()]


def discriminates(template: str, own: str, others: list[str]) -> bool:
    """A template must match its own state and no other, or it cannot tell pages apart."""
    lines = _template_lines(template)
    if not lines or not all(line in own for line in lines):
        return False
    return not any(all(line in other for line in lines) for other in others)


def build_states(named: dict[str, tuple[str, str]]) -> dict[str, State]:
    return {name: State(name=name, url=url, aria=aria) for name, (url, aria) in named.items()}
