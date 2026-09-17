from replaykit.recorder.tools import TOOLS


def test_tools_address_elements_by_ref_never_by_accessible_name():
    """Unnamed inputs must remain addressable from the discovery snapshot."""
    by_name = {tool["name"]: tool for tool in TOOLS}

    assert set(by_name) == {"click", "fill", "select", "goto", "extract", "done"}
    for action in ("click", "fill", "select", "extract"):
        required = by_name[action]["input_schema"]["required"]
        assert "ref" in required
        assert "name" not in required
