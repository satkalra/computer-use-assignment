from dataclasses import dataclass, field


@dataclass(frozen=True)
class Input:
    type: str
    secret: bool = False


@dataclass(frozen=True)
class Target:
    role: str | None = None
    name: str | None = None
    css: str | None = None
    xpath: str | None = None
    within: dict[str, str] | None = None


@dataclass(frozen=True)
class State:
    name: str
    url: str
    aria: str


@dataclass(frozen=True)
class Step:
    from_state: str
    action: str
    target: list[Target]
    value: str | None = None
    to: str | None = None
    timeout_ms: int = 10_000


@dataclass(frozen=True)
class Output:
    type: str


@dataclass(frozen=True)
class Extract:
    from_state: str
    target: list[Target]
    parse: str | None = None
    outputs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OutcomeField:
    target: Target
    type: str


@dataclass(frozen=True)
class Outcome:
    state: str
    extract: dict[str, OutcomeField] = field(default_factory=dict)


@dataclass(frozen=True)
class Flow:
    name: str
    version: int
    inputs: dict[str, Input]
    states: dict[str, State]
    steps: list[Step]
    recovery: list[dict] = field(default_factory=list)
    extract: list[Extract] = field(default_factory=list)
    outputs: dict[str, Output] = field(default_factory=dict)
    outcomes: dict[str, Outcome] = field(default_factory=dict)
