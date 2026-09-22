import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml


@dataclass(frozen=True)
class Policy:
    allowed_origins: list[str]
    allowed_actions: set[str]
    risky_patterns: list[str]


class PolicyViolation(Exception):
    pass


class ApprovalRequired(Exception):
    pass


def _origin(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    return parsed.scheme, parsed.netloc


def check(
    policy: Policy, *, url: str, action: str, target_name: str = "",
    approved: set[int] = frozenset(), step_index: int | None = None,
) -> None:
    if action not in policy.allowed_actions:
        raise PolicyViolation(f"action {action!r} is not in the allowlist")
    # Exact (scheme, host:port) match, never a string prefix -- "http://x:9099"
    # is a literal string-prefix of both "http://x:90990" and
    # "http://x:9099.evil.com", neither of which is the same origin.
    if not any(_origin(url) == _origin(origin) for origin in policy.allowed_origins):
        raise PolicyViolation(f"url {url!r} is outside the allowed origins")
    if not target_name and action in {"click", "select"}:
        if step_index is None or step_index not in approved:
            raise ApprovalRequired(f"{action} on an unnamed target requires approval")
    if target_name and any(re.search(pattern, target_name) for pattern in policy.risky_patterns):
        if step_index is None or step_index not in approved:
            raise ApprovalRequired(f"{action} on {target_name!r} requires approval")


def load_policy(path: Path) -> Policy:
    data = yaml.safe_load(path.read_text())
    return Policy(
        allowed_origins=list(data["allowed_origins"]),
        allowed_actions=set(data["allowed_actions"]),
        risky_patterns=list(data.get("risky_patterns", [])),
    )
