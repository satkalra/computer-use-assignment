import re
from dataclasses import dataclass

from replaykit.recording.schema import Flow
from replaykit.states.predicate import matches


@dataclass(frozen=True)
class RecoveryResult:
    dialog_dismissed: bool = False
    session_expired: bool = False


def _compile_name(raw: str | None):
    """A recovery target's `name` may be a literal, or a `/pattern/flags` regex —
    the shape login.yaml's dialog rule uses for wording that varies by bank."""
    if raw is None:
        return None
    match = re.fullmatch(r"/(.*)/([a-z]*)", raw)
    if match is None:
        return raw
    pattern, flags = match.groups()
    return re.compile(pattern, re.I if "i" in flags else 0)


def _dismiss_declared_dialog(page, rule: dict) -> bool:
    dialog = page.locator("[role=dialog]")
    if not (dialog.count() and dialog.first.is_visible()):
        return False
    for action in rule.get("do", []):
        if action.get("action") != "click":
            continue
        for candidate in action.get("target", []):
            role = candidate.get("role")
            if role is None:
                continue
            button = dialog.first.get_by_role(role, name=_compile_name(candidate.get("name")))
            if button.count() == 1:
                button.click()
                return True
    return False


def _declared_session_expiry(page, flow: Flow, rule: dict) -> bool:
    state_name = rule.get("when", {}).get("state")
    declares_handoff = any("handoff" in action for action in rule.get("do", []))
    if state_name is None or not declares_handoff or state_name not in flow.states:
        return False
    return matches(page, flow.states[state_name])


def recover(page, flow: Flow) -> RecoveryResult:
    """Apply exactly the recovery rules the recording declares.

    Only the two rule *shapes* from the parent design are understood in this
    version (dialog-dismiss triggered by an aria template, a named-state
    handoff trigger) — nothing about which dialog wording or which state name
    is hardcoded; both come from `flow.recovery`.
    """
    dismissed = False
    session_expired = False
    for rule in flow.recovery:
        when = rule.get("when", {})
        if "aria" in when and not dismissed:
            dismissed = _dismiss_declared_dialog(page, rule)
        elif "state" in when:
            session_expired = session_expired or _declared_session_expiry(page, flow, rule)
    return RecoveryResult(dialog_dismissed=dismissed, session_expired=session_expired)
