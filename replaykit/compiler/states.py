import re
from dataclasses import dataclass

from replaykit.recording.schema import State

# ai-mode snapshots annotate every element with [ref=e34] and clickable ones
# with [cursor=pointer]; ref is reassigned on every capture, so two visits to
# the literal same page never compare equal on the raw text. [active] marks
# momentary focus -- real, but a snapshot of DOM state at one instant, not a
# property of the page itself; confirmed live it can end up in a widened
# template and then not hold on a fresh page load at replay time. None of
# the three are a stable basis for state identity.
_AI_MODE_ANNOTATION = re.compile(r"\s*\[(?:ref=[^\]]*|cursor=[^\]]*|active)\]")


def clean(snapshot: str) -> str:
    """Strip annotations that aren't stable across snapshots of the same page."""
    return "\n".join(_AI_MODE_ANNOTATION.sub("", line) for line in snapshot.splitlines())


def _usable(line: str) -> bool:
    """A line ending in a bare ':' is a container (e.g. a link with a nested
    /url:, or a combobox with nested options) whose children aren't carried
    along when the line is used alone -- standalone it's an incomplete
    aria-snapshot fragment that never matches to_match_aria_snapshot, and
    it's exactly the kind of content (a dropdown's current selection) most
    likely to differ between two visits that are the same logical page."""
    return not line.rstrip().endswith(":")


def anchor(snapshot: str) -> str:
    """A stable, low-noise fingerprint for 'this is conceptually the same
    page'. Prefers the first heading (usually a page title) over exact full-
    text equality, so two visits to the same logical page collapse to one
    state even when they differ in ways that don't reflect a real distinct
    page: a table still loading, which field has focus, a dropdown's
    current selection. All three were confirmed live to otherwise fragment
    one page into multiple undiscriminable "states"."""
    lines = [line.strip() for line in snapshot.splitlines() if line.strip() and _usable(line.strip())]
    for line in lines:
        if line.startswith("- heading"):
            return line
    return lines[0] if lines else ""


@dataclass(frozen=True)
class ObservedState:
    url: str
    snapshot: str
    anchor: str


def observed_states(trace_steps) -> list[ObservedState]:
    """Distinct (url, anchor) identities, in first-seen order.

    Snapshots are cleaned of ai-mode annotations before anchoring. When the
    same identity recurs with a longer snapshot (e.g. a table that has since
    finished loading), the fuller snapshot replaces the shorter one, so the
    template built from it isn't accidentally a subset of some later visit
    to the very state it's supposed to represent.
    """
    seen: dict[tuple[str, str], ObservedState] = {}
    order: list[tuple[str, str]] = []
    for step in trace_steps:
        for url, snapshot in ((step.url_before, step.snapshot_before), (step.url_after, step.snapshot_after)):
            if not url:
                continue
            cleaned = clean(snapshot)
            key = (url, anchor(cleaned))
            if key not in seen:
                seen[key] = ObservedState(url=url, snapshot=cleaned, anchor=key[1])
                order.append(key)
            elif len(cleaned) > len(seen[key].snapshot):
                seen[key] = ObservedState(url=url, snapshot=cleaned, anchor=key[1])
    return [seen[key] for key in order]


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
