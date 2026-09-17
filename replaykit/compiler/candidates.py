from replaykit.locators.ladder import build_locator
from replaykit.recording.schema import Target


_ANCHOR_JS = """
(el) => {
  const SKIP = new Set(['INPUT', 'SELECT', 'BUTTON', 'TEXTAREA', 'OPTION']);
  const cleanText = (node) => {
    if (!node || node.nodeType !== 1 || SKIP.has(node.tagName)) return '';
    const clone = node.cloneNode(true);
    clone.querySelectorAll('input,select,button,textarea,option').forEach(c => c.remove());
    return (clone.textContent || '').trim();
  };
  for (let n = el.previousSibling; n; n = n.previousSibling) {
    if (n.nodeType === 3) {
      const t = n.textContent.trim();
      if (t) return {anchor: t, kind: 'text'};
    } else if (n.nodeType === 1) {
      const t = cleanText(n);
      if (t) return {anchor: t, kind: 'element', tag: n.tagName.toLowerCase()};
    }
  }
  for (let p = el.parentElement; p; p = p.parentElement) {
    const own = Array.from(p.childNodes).filter(n => n.nodeType === 3)
      .map(n => n.textContent.trim()).filter(Boolean).join(' ');
    if (own) return {anchor: own, kind: 'ancestor', tag: p.tagName.toLowerCase()};
  }
  return {anchor: null, kind: null};
}
"""

_TAG_JS = "(el) => el.tagName.toLowerCase()"
_ID_JS = "(el) => el.id || null"

# A data cell's accessible "name" IS its own text content -- the balance, an
# account number -- not a stable label like a button's. The nearest sibling
# text an anchor would use is exactly the same kind of data one column over.
# Neither is safe to derive a locator from for these roles.
_DATA_ROLES = {"cell"}

# Table/list DATA cells have no stable label to anchor on -- the nearest text
# IS the dynamic data (an account number, a balance). Walk up instead: find
# the nearest ancestor with a stable id (e.g. a table's #accountTable) and
# express the element as a position within it (row 1, column 2). This is
# what the balance of "the first listed account" actually is -- a position,
# not a value -- and it holds across users whose account numbers and
# balances all differ from whoever was logged in during discovery.
_POSITION_JS = """
(el) => {
  let node = el;
  const chain = [];
  for (let depth = 0; depth < 12 && node && node.nodeType === 1; depth++) {
    if (node.id) return {root: node.id, path: chain.slice().reverse().join(' > ')};
    const parent = node.parentElement;
    if (!parent) break;
    const siblings = Array.from(parent.children).filter(c => c.tagName === node.tagName);
    const index = siblings.indexOf(node) + 1;
    chain.push(`${node.tagName.toLowerCase()}:nth-of-type(${index})`);
    node = parent;
  }
  return {root: null, path: null};
}
"""


def _matches_element(page, element, target: Target) -> bool:
    try:
        candidate = build_locator(page, target)
        if candidate.count() != 1:
            return False
        return candidate.evaluate(
            "(resolved, expected) => resolved === expected", element.element_handle()
        )
    except Exception:
        return False


def _xpath_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    return "concat(" + ", \"'\", ".join(f"'{part}'" for part in value.split("'")) + ")"


def _positional_targets(locator) -> list[Target]:
    info = locator.evaluate(_POSITION_JS)
    root, path = info.get("root"), info.get("path")
    if not root:
        return []
    css = f"#{root} {path}" if path else f"#{root}"
    return [Target(css=css)]


def _anchor_targets(page, locator, tag: str) -> list[Target]:
    info = locator.evaluate(_ANCHOR_JS)
    anchor, kind = info.get("anchor"), info.get("kind")
    if not anchor:
        return []
    anchor = anchor.strip()[:40]
    quoted = _xpath_literal(anchor)
    if kind == "text":
        return [Target(xpath=f"//text()[contains(.,{quoted})]/following::{tag}[1]")]
    if kind == "element":
        return [Target(xpath=f"//{info['tag']}[contains(.,{quoted})]/following::{tag}[1]")]
    return [Target(xpath=f"//{info['tag']}[contains(text(),{quoted})]//{tag}")]


def derive(page, ref: str, role: str, name: str) -> list[Target]:
    """Derive the ranked ladder for one element, keeping only what actually resolves."""
    from replaykit.recorder.snapshot import locator_for

    locator = locator_for(page, ref)
    tag = locator.evaluate(_TAG_JS)
    element_id = locator.evaluate(_ID_JS)

    ranked: list[Target] = []
    if name and role not in _DATA_ROLES:
        ranked.append(Target(role=role, name=name))
    if element_id:
        ranked.append(Target(css=f"#{element_id}"))
    ranked.extend(_positional_targets(locator))
    if role not in _DATA_ROLES:
        ranked.extend(_anchor_targets(page, locator, tag))

    verified = [target for target in ranked if _matches_element(page, locator, target)]
    if not verified:
        raise ValueError(f"no unique locator could be derived for ref {ref} ({role} {name!r})")
    return verified
