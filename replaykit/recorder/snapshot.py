import re
from dataclasses import dataclass


_ELEMENT = re.compile(
    r'^\s*-\s+(?P<role>[a-z]+)(?:\s+"(?P<name>[^"]*)")?.*?\[ref=(?P<ref>\w+)\]'
)

_INTERACTIVE = {
    "textbox",
    "button",
    "combobox",
    "checkbox",
    "radio",
    "link",
    "option",
}
_PRUNED_ROLES = {"generic", "list", "listitem", "img"}
_CHROME_NAMES = {
    "home",
    "about us",
    "services",
    "products",
    "locations",
    "forum",
    "site map",
    "contact us",
    "admin page",
    "read more",
    "register",
    "forgot login info?",
    "www.parasoft.com",
}


@dataclass(frozen=True)
class SnapshotElement:
    ref: str
    role: str
    name: str


@dataclass(frozen=True)
class Snapshot:
    text: str
    url: str
    elements: dict[str, SnapshotElement]


def _keep(role: str, name: str) -> bool:
    if role in _PRUNED_ROLES:
        return False
    return name.strip().lower() not in _CHROME_NAMES


def capture(page, prune: bool = True) -> Snapshot:
    """Observe the page the way the model will: aria roles plus addressable refs."""
    raw = page.locator("body").aria_snapshot(mode="ai")
    kept_lines: list[str] = []
    elements: dict[str, SnapshotElement] = {}
    for line in raw.splitlines():
        match = _ELEMENT.search(line)
        if match is None:
            if not prune:
                kept_lines.append(line)
            continue
        role = match.group("role")
        name = match.group("name") or ""
        ref = match.group("ref")
        if prune and not _keep(role, name):
            continue
        kept_lines.append(line)
        if role in _INTERACTIVE:
            elements[ref] = SnapshotElement(ref=ref, role=role, name=name)
    return Snapshot(text="\n".join(kept_lines), url=page.url, elements=elements)


def locator_for(page, ref: str):
    """Refs are ephemeral: they are invalidated by navigation, so resolve immediately."""
    return page.locator(f"aria-ref={ref}")
