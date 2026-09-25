import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

from playwright.sync_api import sync_playwright

from replaykit.compiler import compile_trace
from replaykit.control import ControlState, InterventionRequest, intervene
from replaykit.policy.policy import load_policy
from replaykit.promotion.gate import run_gate
from replaykit.recorder.session import record
from replaykit.recorder.spec import FlowSpec, InputSpec, OutputSpec
from replaykit.recording.loader import load_flow
from replaykit.replayer.audit import JsonlAuditLog
from replaykit.replayer.engine import ReplayEngine, find_resume_index
from replaykit.replayer.handoff import capture_screenshot_base64


def _parse_kv(pairs: list[str]) -> dict[str, str]:
    result = {}
    for pair in pairs:
        key, separator, value = pair.partition("=")
        if not separator:
            raise ValueError(f"expected key=value, got {pair!r}")
        result[key] = value
    return result


def build_record_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--input", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--output", action="append", default=[], metavar="NAME:TYPE")
    parser.add_argument("--secret", action="append", default=[], metavar="KEY")
    parser.add_argument("--serve", action="store_true", help="open the local operator dashboard")
    parser.add_argument("--port", type=int, default=5000)


def build_replay_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("flow_path")
    parser.add_argument("--target", required=True)
    parser.add_argument("--input", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--approve", action="append", default=[], type=int, metavar="STEP_INDEX")


def run_record(args, control: ControlState | None, client) -> int:
    inputs = _parse_kv(args.input)
    secrets = set(args.secret)
    input_specs = {name: InputSpec("string", secret=name in secrets) for name in inputs}
    output_specs = {}
    for entry in args.output:
        name, _, type_ = entry.partition(":")
        output_specs[name] = OutputSpec(type_)
    spec = FlowSpec(
        name=args.name, goal=args.goal, start_url=args.target,
        inputs=input_specs, outputs=output_specs,
    )
    evidence_dir = Path("evidence") / f"discovery-{args.name}-{int(time.time())}"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    policy = load_policy(Path("policy.yaml"))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=control is None)
        try:
            page = browser.new_page()
            page.goto(spec.start_url)
            trace = record(
                page, spec, inputs, client, policy=policy,
                control=control, evidence_dir=evidence_dir,
            )
            (evidence_dir / "trace.json").write_text(json.dumps(asdict(trace), indent=2, default=str))
            if trace.status != "success":
                print(f"discovery did not complete: {trace.status}", file=sys.stderr)
                return 1
            yaml_text = compile_trace(page, trace, inputs)
            (evidence_dir / "recording.yaml").write_text(yaml_text)

            # Never save a recording nobody has replayed yet -- run it through the
            # same gate a Python-API caller would, against the one credential set
            # the CLI has. Repeating identical inputs 3x only proves determinism
            # for a mutating flow if it's given a reset hook, which the CLI can't
            # express; that's a known limit of gating from the command line.
            candidate_flow = load_flow(evidence_dir / "recording.yaml")
            gate_report = run_gate(browser, candidate_flow, spec, credentials=[inputs], recording_yaml=yaml_text)
            (evidence_dir / "promotion_gate.json").write_text(json.dumps({
                "passed": gate_report.passed, "summary": gate_report.summary,
            }, indent=2))
            if not gate_report.passed:
                print(f"promotion gate failed, not saving as a trusted flow:\n{gate_report.summary}", file=sys.stderr)
                return 1
        finally:
            browser.close()

    out_path = Path("replaykit/flows") / f"{args.name}.yaml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml_text)
    print(f"wrote {out_path} (passed the promotion gate: {len(gate_report.runs)} replays)")
    return 0


def run_replay(args, control: ControlState | None) -> int:
    flow = load_flow(Path(args.flow_path))
    inputs = _parse_kv(args.input)
    policy = load_policy(Path("policy.yaml"))
    evidence_dir = Path("evidence") / f"replay-{flow.name}-{int(time.time())}"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    audit_log = JsonlAuditLog(evidence_dir / "log.jsonl")
    secret_fields = {name for name, spec in flow.inputs.items() if spec.secret}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=control is None)
        try:
            page = browser.new_page()
            page.goto(args.target)
            engine = ReplayEngine(audit_log, policy=policy, approved=set(args.approve))
            start_index = 0
            while True:
                result = engine.run(page, flow, inputs, start_index=start_index)
                if result.status == "failed":
                    # A hard stop (e.g. a policy violation): no live-page fix exists for an
                    # operator to make and resume from, so unlike "handoff" this is never
                    # offered as resumable.
                    break
                if result.status not in {"handoff", "needs_approval"}:
                    break
                reason = result.approval_reason or (result.handoff.reason if result.handoff else "unknown")
                request = InterventionRequest(
                    capability=flow.name, goal=flow.name, step_index=result.step_index,
                    reason=reason, url=page.url,
                    screenshot_base64=capture_screenshot_base64(page),
                    handoff=result.handoff.to_dict() if result.handoff else None,
                )
                if not intervene(page, secret_fields, request, control, evidence_dir):
                    break
                if result.status == "needs_approval":
                    engine.approved.add(result.step_index)
                start_index = find_resume_index(page, flow, min_index=result.step_index)
        finally:
            browser.close()

    (evidence_dir / "result.json").write_text(json.dumps({
        "status": result.status,
        "outputs": result.outputs,
        "outcome": result.outcome,
        "handoff": result.handoff.to_dict() if result.handoff else None,
    }, indent=2, default=str))
    print(json.dumps({
        "status": result.status,
        "outputs": result.outputs,
        "outcome": result.outcome,
    }, indent=2))
    return 0 if result.status in {"success", "business_outcome"} else 1
