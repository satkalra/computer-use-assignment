from pathlib import Path
import warnings

import yaml

from .schema import Flow, Input, State, Step, Target


class RecordingValidationError(ValueError):
    """Raised when a recording is invalid for the supported format version."""


SUPPORTED_KEYS = {"flow", "version", "inputs", "states", "steps", "recovery"}
DEFERRED_KEYS = {"uses", "terminal_errors", "extract", "outputs"}
TARGET_KEYS = {"role", "name", "css", "xpath", "within"}
STEP_ACTIONS = {"fill", "click", "select"}
CREDENTIAL_WORDS = ("password", "username", "credential", "secret", "token")


def _fail(message: str) -> None:
    raise RecordingValidationError(message)


def _mapping(value: object, context: str) -> dict:
    if not isinstance(value, dict):
        _fail(f"{context} must be a mapping")
    return value


def _target(value: object, context: str) -> Target:
    data = _mapping(value, context)
    unknown = set(data) - TARGET_KEYS
    if unknown:
        _fail(f"{context} must specify exactly one of role, css, xpath; unsupported keys: {', '.join(sorted(unknown))}")
    mechanisms = [key for key in ("role", "css", "xpath") if data.get(key) is not None]
    if len(mechanisms) != 1:
        _fail(f"{context} must specify exactly one of role, css, xpath")
    if data.get("name") is not None and data.get("role") is None:
        _fail(f"{context}.name is only valid with role")
    return Target(**data)


def load_flow(path: Path) -> Flow:
    """Load a Phase 1 YAML recording with strict, fail-fast validation."""
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        _fail(f"invalid YAML: {exc}")
    data = _mapping(raw, "recording")
    deferred = set(data) & DEFERRED_KEYS
    if deferred:
        _fail(f"{', '.join(sorted(deferred))} not supported in this version")
    unknown = set(data) - SUPPORTED_KEYS
    if unknown:
        _fail(f"unsupported recording keys: {', '.join(sorted(unknown))}")
    for key in ("flow", "version", "inputs", "states", "steps"):
        if key not in data:
            _fail(f"recording is missing required key: {key}")
    if not isinstance(data["flow"], str) or not data["flow"]:
        _fail("flow must be a non-empty string")
    if not isinstance(data["version"], int):
        _fail("version must be an integer")

    inputs: dict[str, Input] = {}
    for name, spec in _mapping(data["inputs"], "inputs").items():
        spec = _mapping(spec, f"inputs.{name}")
        if spec.get("type") != "string":
            _fail(f"inputs.{name}.type must be string in this version")
        secret = spec.get("secret", False)
        if not isinstance(secret, bool):
            _fail(f"inputs.{name}.secret must be boolean")
        if any(word in name.lower() for word in CREDENTIAL_WORDS) and not secret:
            warnings.warn(f"input {name!r} looks like a credential and is not marked secret", UserWarning)
        inputs[name] = Input(type="string", secret=secret)

    states: dict[str, State] = {}
    for name, spec in _mapping(data["states"], "states").items():
        spec = _mapping(spec, f"states.{name}")
        if set(spec) != {"url", "aria"} or not all(isinstance(spec[key], str) for key in spec):
            _fail(f"states.{name} must contain string url and aria")
        states[name] = State(name=name, url=spec["url"], aria=spec["aria"])

    if not isinstance(data["steps"], list) or not data["steps"]:
        _fail("steps must be a non-empty list")
    steps: list[Step] = []
    for index, raw_step in enumerate(data["steps"]):
        step = _mapping(raw_step, f"steps[{index}]")
        allowed = {"from", "action", "target", "value", "to", "timeout_ms"}
        if set(step) - allowed:
            _fail(f"steps[{index}] has unsupported keys")
        for key in ("from", "action", "target"):
            if key not in step:
                _fail(f"steps[{index}] is missing required key: {key}")
        if step["from"] not in states:
            _fail(f"steps[{index}].from names an unknown state")
        if step.get("to") is not None and step["to"] not in states:
            _fail(f"steps[{index}].to names an unknown state")
        if step["action"] not in STEP_ACTIONS:
            _fail(f"steps[{index}].action is not supported")
        if not isinstance(step["target"], list) or not step["target"]:
            _fail(f"steps[{index}].target must be a non-empty list")
        if step["action"] in {"fill", "select"} and not isinstance(step.get("value"), str):
            _fail(f"steps[{index}].value is required for {step['action']}")
        timeout_ms = step.get("timeout_ms", 10_000)
        if not isinstance(timeout_ms, int) or timeout_ms <= 0:
            _fail(f"steps[{index}].timeout_ms must be a positive integer")
        steps.append(Step(
            from_state=step["from"], action=step["action"],
            target=[_target(target, f"steps[{index}].target") for target in step["target"]],
            value=step.get("value"), to=step.get("to"), timeout_ms=timeout_ms,
        ))

    recovery = data.get("recovery", [])
    if not isinstance(recovery, list):
        _fail("recovery must be a list")
    return Flow(data["flow"], data["version"], inputs, states, steps, recovery)
