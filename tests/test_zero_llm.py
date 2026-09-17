import ast
from pathlib import Path


PACKAGE = Path(__file__).parents[1] / "replaykit"
FORBIDDEN = {"anthropic", "openai", "cohere", "google.generativeai", "boto3"}


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_replaykit_contains_no_llm_client_imports():
    imports = set().union(*(imported_modules(path) for path in PACKAGE.rglob("*.py")))

    assert not any(module == forbidden or module.startswith(f"{forbidden}.") for module in imports for forbidden in FORBIDDEN)


def test_replayer_never_imports_the_test_harness():
    imports = set().union(*(imported_modules(path) for path in (PACKAGE / "replayer").glob("*.py")))

    assert not any(module == "replaykit.harness" or module.startswith("replaykit.harness.") for module in imports)


def test_the_recorder_receives_its_model_client_by_injection():
    """The recorder can stay inside the package-wide no-SDK import guard."""
    import inspect

    from replaykit.recorder.session import record

    assert "client" in inspect.signature(record).parameters
