from dataclasses import dataclass

from replaykit.recording.schema import Target


@dataclass(frozen=True)
class CandidateOutcome:
    candidate: Target
    count: int | None
    error: str | None = None


class AmbiguousTarget(RuntimeError):
    def __init__(self, candidate: Target, count: int):
        self.candidate = candidate
        self.count = count
        super().__init__(f"ambiguous target {candidate}: matched {count} elements")


class UnresolvableTarget(RuntimeError):
    def __init__(self, outcomes: list[CandidateOutcome]):
        self.outcomes = outcomes
        summary = "; ".join(f"{item.candidate}: {item.count if item.error is None else item.error}" for item in outcomes)
        super().__init__(f"no target candidate resolved ({summary})")


def _role_locator(scope, role: str, name: str | None):
    return scope.get_by_role(role, name=name) if name is not None else scope.get_by_role(role)


def build_locator(page, target: Target):
    """Build, but do not weaken, a locator from one recording descriptor."""
    if target.role is not None:
        scope = page
        if target.within is not None:
            scope = _role_locator(page, target.within["role"], target.within.get("name"))
        return _role_locator(scope, target.role, target.name)
    if target.css is not None:
        return page.locator(target.css)
    if target.xpath is not None:
        return page.locator(f"xpath={target.xpath}")
    raise ValueError("target must have role, css, or xpath")


def resolve(page, targets: list[Target]):
    """Return the first uniquely resolving locator and its one-based rung."""
    outcomes: list[CandidateOutcome] = []
    for rung, target in enumerate(targets, start=1):
        try:
            locator = build_locator(page, target)
            count = locator.count()
        except Exception as exc:
            outcomes.append(CandidateOutcome(target, None, str(exc)))
            continue
        outcomes.append(CandidateOutcome(target, count))
        if count == 1:
            return locator, rung
        if count > 1:
            raise AmbiguousTarget(target, count)
    raise UnresolvableTarget(outcomes)
