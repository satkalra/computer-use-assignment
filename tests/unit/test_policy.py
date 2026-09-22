import pytest

from replaykit.policy.policy import ApprovalRequired, Policy, PolicyViolation, check, load_policy


def policy():
    return Policy(
        allowed_origins=["http://localhost:9099"],
        allowed_actions={"click", "fill", "select"},
        risky_patterns=[r"(?i)transfer", r"(?i)delete"],
    )


def test_check_allows_a_plain_action_on_an_allowed_origin():
    check(policy(), url="http://localhost:9099/parabank/overview.htm", action="click", target_name="Log In")


def test_check_rejects_an_action_outside_the_allowlist():
    with pytest.raises(PolicyViolation, match="not in the allowlist"):
        check(policy(), url="http://localhost:9099/parabank/overview.htm", action="goto")


def test_check_rejects_an_origin_outside_the_allowlist():
    with pytest.raises(PolicyViolation, match="outside the allowed origins"):
        check(policy(), url="http://evil.example/overview.htm", action="click", target_name="Log In")


def test_check_rejects_a_port_that_merely_shares_a_numeric_prefix():
    with pytest.raises(PolicyViolation, match="outside the allowed origins"):
        check(policy(), url="http://localhost:90990/overview.htm", action="click", target_name="Log In")


def test_check_rejects_a_host_that_merely_shares_a_string_prefix():
    with pytest.raises(PolicyViolation, match="outside the allowed origins"):
        check(policy(), url="http://localhost:9099.evil.com/overview.htm", action="click", target_name="Log In")


def test_check_requires_approval_for_a_risky_target_by_default():
    with pytest.raises(ApprovalRequired):
        check(policy(), url="http://localhost:9099/parabank/transfer.htm", action="click", target_name="Transfer Funds")


def test_check_allows_a_risky_target_once_its_step_is_pre_approved():
    check(
        policy(), url="http://localhost:9099/parabank/transfer.htm", action="click",
        target_name="Transfer Funds", approved={3}, step_index=3,
    )


def test_check_requires_approval_for_an_unnamed_click():
    with pytest.raises(ApprovalRequired, match="requires approval"):
        check(
            policy(), url="http://localhost:9099/parabank/transfer.htm",
            action="click", target_name="",
        )


def test_load_policy_reads_yaml(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text("""
allowed_origins: ["http://localhost:9099"]
allowed_actions: [click, fill]
risky_patterns: ["(?i)transfer"]
""")

    loaded = load_policy(path)

    assert loaded.allowed_origins == ["http://localhost:9099"]
    assert loaded.allowed_actions == {"click", "fill"}
    assert loaded.risky_patterns == ["(?i)transfer"]
