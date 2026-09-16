from collections.abc import Callable
from dataclasses import dataclass

SUPPORTED_OUTPUT_TYPES = {"string", "decimal", "integer"}


@dataclass(frozen=True)
class InputSpec:
    type: str
    secret: bool = False


@dataclass(frozen=True)
class OutputSpec:
    type: str


@dataclass(frozen=True)
class FlowSpec:
    name: str
    goal: str
    start_url: str
    inputs: dict[str, InputSpec]
    outputs: dict[str, OutputSpec]
    # Run before each promotion-gate replay. Flows that mutate bank state declare
    # one (e.g. seed a fresh user); flows without one are treated as idempotent.
    reset: Callable[[], dict[str, str]] | None = None

    def __post_init__(self):
        for name, output in self.outputs.items():
            if output.type not in SUPPORTED_OUTPUT_TYPES:
                raise ValueError(f"unsupported output type {output.type!r} for {name!r}")

    def secret_inputs(self) -> set[str]:
        return {name for name, spec in self.inputs.items() if spec.secret}
