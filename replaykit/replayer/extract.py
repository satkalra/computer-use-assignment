import re
from decimal import Decimal, InvalidOperation

from replaykit.locators.ladder import resolve
from replaykit.recording.schema import Flow, Output


def run_extractors(page, flow: Flow) -> dict[str, str]:
    values: dict[str, str] = {}
    for extractor in flow.extract:
        locator, _rung = resolve(page, extractor.target)
        text = locator.inner_text()
        if extractor.parse is None:
            values[extractor.outputs[0]] = text.strip()
            continue
        match = re.search(extractor.parse, text)
        if match is None:
            raise ValueError(f"extractor pattern {extractor.parse!r} did not match {text[:60]!r}")
        for name, group in zip(extractor.outputs, match.groups()):
            values[name] = group.strip()
    return values


def validate_outputs(values: dict[str, str], declared: dict[str, Output]) -> list[str]:
    """Return human-readable errors; an empty list means the outputs are valid."""
    errors: list[str] = []
    for name, output in declared.items():
        if name not in values:
            errors.append(f"missing declared output {name!r}")
            continue
        raw = values[name]
        if output.type == "decimal":
            try:
                Decimal(raw.replace("$", "").replace(",", ""))
            except (InvalidOperation, ArithmeticError):
                errors.append(f"output {name!r} is not a decimal: {raw!r}")
        elif output.type == "integer" and not raw.strip().lstrip("-").isdigit():
            errors.append(f"output {name!r} is not an integer: {raw!r}")
    return errors
