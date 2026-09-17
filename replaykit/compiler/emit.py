import yaml

from replaykit.recording.schema import State, Target


def parameterize(value: str, inputs: dict[str, str]) -> str:
    """Replace recorded input values with their replay-time references."""
    for name, supplied in inputs.items():
        if supplied and value == supplied:
            return f"{{{{inputs.{name}}}}}"
    return value


def _target_dict(target: Target) -> dict:
    for field in ("role", "css", "xpath"):
        value = getattr(target, field)
        if value is not None:
            if field == "role" and target.name:
                return {field: value, "name": target.name}
            return {field: value}
    raise ValueError(f"target has no mechanism: {target}")


def emit(
    trace,
    states: dict[str, State],
    step_targets: list[list[Target]],
    step_states: list[tuple[str, str | None]],
    supplied_inputs: dict[str, str] | None = None,
) -> str:
    """Render a compiled trace as YAML accepted by the Phase 1 loader."""
    supplied = supplied_inputs or {}
    document: dict = {
        "flow": trace.spec.name,
        "version": 1,
        "inputs": {
            name: {"type": spec.type, **({"secret": True} if spec.secret else {})}
            for name, spec in trace.spec.inputs.items()
        },
        "states": {
            name: {"url": state.url, "aria": state.aria}
            for name, state in states.items()
        },
        "steps": [],
    }
    if trace.spec.outputs:
        document["outputs"] = {
            name: {"type": spec.type}
            for name, spec in trace.spec.outputs.items()
        }
    extracts: list[dict] = []
    for index, step in enumerate(trace.steps):
        from_state, to_state = step_states[index]
        targets = [_target_dict(target) for target in step_targets[index]]
        if step.action == "extract":
            if step.output_name not in trace.spec.outputs:
                raise ValueError(f"extract names undeclared output {step.output_name!r}")
            extracts.append({
                "from": from_state,
                "target": targets,
                "outputs": [step.output_name],
            })
            continue
        entry: dict = {
            "from": from_state,
            "action": step.action,
            "target": targets,
        }
        if step.action in {"fill", "select"}:
            entry["value"] = parameterize(step.value, supplied)
        if to_state:
            entry["to"] = to_state
        document["steps"].append(entry)
    if extracts:
        document["extract"] = extracts
    return yaml.safe_dump(document, sort_keys=False, default_flow_style=False)
