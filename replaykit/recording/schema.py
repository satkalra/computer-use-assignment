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
class Flow:
    name: str
    version: int
    inputs: dict[str, Input]
    states: dict[str, State]
    steps: list[Step]
    recovery: list[dict] = field(default_factory=list)
