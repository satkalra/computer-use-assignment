import re

from replaykit.compiler.emit import emit
from replaykit.compiler.states import build_states, clean, discriminates, observed_states


def url_pattern(url: str) -> str:
    """Match the stable path; ParaBank appends a volatile session id to URLs."""
    path = url.split("?", 1)[0].split(";", 1)[0]
    return re.escape("/" + path.rstrip("/").split("/")[-1])


def minimal_template(snapshot: str) -> str:
    """Prefer the first heading as the least brittle state predicate."""
    for line in snapshot.splitlines():
        if line.strip().startswith("- heading"):
            return line.strip()
    return next((line.strip() for line in snapshot.splitlines() if line.strip()), "")


def widen_template(snapshot: str, others: list[str]) -> str:
    """Add snapshot lines until the predicate identifies exactly one state."""
    template = ""
    for line in (line.strip() for line in snapshot.splitlines() if line.strip()):
        template = f"{template}\n{line}".strip()
        if discriminates(template, snapshot, others):
            return template
    raise ValueError("no discriminating aria template could be built for this state")


def compile_trace(page, trace, supplied_inputs: dict[str, str]) -> str:
    """Compile a discovery trace into Phase 1 recording YAML without any model call.

    ``page`` is retained for the public API, but is intentionally not used to
    resolve trace refs: each step already carries the candidate ladder captured
    and verified before that ephemeral ref could expire.
    """
    del page
    observed = observed_states(trace.steps)
    if not observed:
        raise ValueError("cannot compile a trace without observed states")

    named: dict[str, tuple[str, str]] = {}
    state_names: dict[tuple[str, str], str] = {}
    for index, state in enumerate(observed, start=1):
        # observed_states() already stripped ai-mode annotations, so state.snapshot
        # is stable across revisits and safe to use as the state.snapshot identity.
        others = [other.snapshot for other in observed if other != state]
        template = minimal_template(state.snapshot)
        if not discriminates(template, state.snapshot, others):
            template = widen_template(state.snapshot, others)
        name = f"state_{index}"
        named[name] = (url_pattern(state.url), template)
        state_names[(state.url, state.snapshot)] = name

    step_targets = []
    step_states = []
    for step in trace.steps:
        if not step.targets:
            raise ValueError(
                f"trace step {step.action!r} has no captured locator candidates; "
                "refs cannot be resolved after discovery"
            )
        # Steps still carry the raw snapshot text; clean it the same way to
        # land on the same identity the states above were keyed with.
        from_name = state_names.get((step.url_before, clean(step.snapshot_before)))
        to_name = state_names.get((step.url_after, clean(step.snapshot_after)))
        if from_name is None or to_name is None:
            raise ValueError("trace step does not map to an observed state")
        step_targets.append(step.targets)
        step_states.append((from_name, to_name if to_name != from_name else None))
    return emit(trace, build_states(named), step_targets, step_states, supplied_inputs)


__all__ = ["compile_trace"]
