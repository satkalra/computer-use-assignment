import sys
from types import SimpleNamespace

import app


def test_main_dispatches_replay_and_returns_the_handler_exit_code(monkeypatch):
    captured = {}

    def fake_run_replay(args, control):
        captured["target"] = args.target
        captured["control"] = control
        return 3

    monkeypatch.setattr(app, "run_replay", fake_run_replay)

    exit_code = app.main(["replay", "flow.yaml", "--target", "http://bank.example"])

    assert exit_code == 3
    assert captured["target"] == "http://bank.example"
    assert captured["control"] is None


def test_main_requires_a_subcommand():
    try:
        app.main([])
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert exc.code != 0


def test_main_serves_a_recording_with_a_shared_control_state(monkeypatch):
    captured = {}
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=lambda: object()))
    monkeypatch.setattr(app, "serve_in_background", lambda control, port: captured.update(control=control, port=port))
    monkeypatch.setattr(
        app, "run_record",
        lambda _args, control, client: captured.update(record_control=control, client=client) or 0,
    )

    result = app.main([
        "record", "--name", "login", "--goal", "Log in", "--target", "http://bank.example",
        "--serve", "--port", "5050",
    ])

    assert result == 0
    assert captured["port"] == 5050
    assert captured["control"] is captured["record_control"]
