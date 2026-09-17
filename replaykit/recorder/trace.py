from dataclasses import dataclass, field

from .spec import FlowSpec
from replaykit.recording.schema import Target


@dataclass(frozen=True)
class TraceStep:
    action: str                 # click | fill | select | extract
    ref: str
    role: str
    name: str
    value: str = ""             # fill/select text, as the model supplied it
    output_name: str = ""       # extract only
    url_before: str = ""
    url_after: str = ""
    snapshot_before: str = ""
    snapshot_after: str = ""
    # Refs belong to a single accessibility snapshot. Keep the mechanically
    # verified locator ladder while that snapshot is still live, rather than
    # attempting to resolve the ref later during compilation.
    targets: list[Target] = field(default_factory=list)


@dataclass
class Trace:
    spec: FlowSpec
    steps: list[TraceStep] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)
    status: str = "incomplete"  # incomplete | success
    usage: dict[str, int] = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})
