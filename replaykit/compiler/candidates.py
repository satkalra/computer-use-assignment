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
    if name:
        ranked.append(Target(role=role, name=name))
    if element_id:
        ranked.append(Target(css=f"#{element_id}"))
    ranked.extend(_anchor_targets(page, locator, tag))

    verified = [target for target in ranked if _matches_element(page, locator, target)]
    if not verified:
        raise ValueError(f"no unique locator could be derived for ref {ref} ({role} {name!r})")
    return verified
