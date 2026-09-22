import json
import re
from pathlib import Path

from replaykit.control import await_approval
from replaykit.policy.policy import ApprovalRequired, Policy, PolicyViolation, check

from .snapshot import Snapshot, capture, locator_for
from .spec import FlowSpec
from .tools import TOOLS
from .trace import Trace, TraceStep


MODEL = "claude-sonnet-5"

_PROMPT = """You are recording a browser flow so it can be replayed later without a model.

Goal: {goal}

Inputs available to you (use these placeholders):
{inputs}

Outputs you must extract before calling done: {outputs}

You see an accessibility snapshot. Every interactive element has a ref such as
[ref=e34]. Address elements ONLY by ref -- many inputs on this site have no
accessible name, so the surrounding text is your guide to what each one is.
Refs change after every action; always use the refs from the latest snapshot.

Every action you take becomes a permanent, literal replay step -- there is no
"just looking" and nothing gets cleaned up afterward. So:
- You are already on the starting page. Never call goto.
- Fill in every required field a form needs BEFORE submitting it. Submitting
  an empty or partial form is a real error on the live site, not a no-op.
- Take the minimum number of actions that accomplish the goal. Don't click
  something to inspect it, don't repeat an action that already succeeded,
  don't explore alternate ways to do the same thing.
- The moment every declared output is extracted and the goal is met, call
  done immediately. Do not take further actions first.
- Before each tool call, say in one short sentence why you are taking it.
"""


def _observation(snapshot) -> str:
    return f"URL: {snapshot.url}\n\n{snapshot.text}"


def _settle(page) -> None:
    """Give async content (e.g. a table populated after navigation) a chance
    to render before the next capture. A capture taken mid-render produces a
    snapshot that's a strict subset of the same page settled -- undiscrimin-
    able from its own later self -- confirmed live on ParaBank's account
    overview page. Best-effort: some pages never go fully idle.

    networkidle alone isn't enough: confirmed live and reproduced directly
    that ParaBank's transfer confirmation content can still be missing from
    an aria snapshot taken immediately after networkidle resolves, and
    present a moment later with no further network activity in between --
    the render itself, not a pending request, is what's still catching up.
    """
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    page.wait_for_timeout(300)


def _resolve_placeholder(value: str, inputs: dict[str, str]) -> str:
    match = re.fullmatch(r"\{\{inputs\.([A-Za-z_][A-Za-z0-9_]*)\}\}", value)
    return inputs[match.group(1)] if match else value


def _apply(page, action: str, payload: dict, inputs: dict[str, str]) -> None:
    if action == "goto":
        page.goto(payload["url"])
        _settle(page)
        return

    locator = locator_for(page, payload["ref"])
    if action == "click":
        locator.click()
    elif action == "fill":
        locator.fill(_resolve_placeholder(payload["value"], inputs))
    elif action == "select":
        locator.select_option(label=_resolve_placeholder(payload["value"], inputs))
    _settle(page)


def _redact_snapshot(snapshot: Snapshot, secret_values: list[str]) -> Snapshot:
    # A filled secret sits in the DOM as soon as _apply() runs, so the very next
    # capture -- headed straight back to the model as the tool_result -- would
    # otherwise undo the placeholder prompt entirely and land the raw value in
    # the trace this snapshot gets stored into.
    text = snapshot.text
    for value in secret_values:
        if value:
            text = text.replace(value, "[REDACTED]")
    return Snapshot(text=text, url=snapshot.url, elements=snapshot.elements)


def _write_policy_violation(evidence_dir: Path, *, url: str, action: str, reason: str) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "policy_violation.json").write_text(
        json.dumps({"url": url, "action": action, "reason": reason}, indent=2)
    )


def _log_turn(
    evidence_dir: Path, entry: dict, secret_values: list[str],
) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)

    def redact_recursively(obj):
        if isinstance(obj, dict):
            return {k: redact_recursively(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [redact_recursively(item) for item in obj]
        elif isinstance(obj, str):
            result = obj
            for value in secret_values:
                if value:
                    result = result.replace(value, "[REDACTED]")
            return result
        else:
            return obj

    with (evidence_dir / "log.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(redact_recursively(entry)) + "\n")


def record(
    page, spec: FlowSpec, inputs: dict[str, str], client, max_steps: int = 25, *,
    policy: Policy | None = None, control=None, evidence_dir: Path | None = None,
) -> Trace:
    """Drive an injected model client over the page and record its tool actions."""
    trace = Trace(spec=spec)
    secret_values = [inputs[name] for name in spec.secret_inputs() if name in inputs]
    rendered_inputs = "\n".join(f"  {name}: {{{{inputs.{name}}}}}" for name in inputs)
    prompt = _PROMPT.format(
        goal=spec.goal,
        inputs=rendered_inputs,
        outputs=", ".join(spec.outputs) or "(none)",
    )

    snapshot = _redact_snapshot(capture(page), secret_values)
    messages = [{"role": "user", "content": f"{prompt}\n\n{_observation(snapshot)}"}]

    for turn_num in range(1, max_steps + 1):
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            tools=TOOLS,
            # The loop only executes and replies to one tool_use block per turn;
            # without this the model can emit two (e.g. alongside a thinking
            # block) and the unanswered one 400s on the next request.
            tool_choice={"type": "auto", "disable_parallel_tool_use": True},
            messages=messages,
        )
        trace.usage["input_tokens"] += response.usage.input_tokens
        trace.usage["output_tokens"] += response.usage.output_tokens
        messages.append({"role": "assistant", "content": response.content})

        reasoning = " ".join(
            getattr(b, "text", "") for b in response.content
            if getattr(b, "type", "") == "text"
        ).strip()

        call = next(
            (block for block in response.content if getattr(block, "type", "") == "tool_use"),
            None,
        )
        if call is None:
            if evidence_dir is not None:
                _log_turn(
                    evidence_dir,
                    {
                        "turn": turn_num,
                        "reasoning": reasoning,
                        "tool": None,
                        "input": None,
                        "url": snapshot.url,
                        "outcome": "no tool call",
                    },
                    secret_values,
                )
            break
        if call.name == "done":
            trace.status = "success"
            trace.outputs.update(call.input.get("outputs") or {})
            if evidence_dir is not None:
                _log_turn(
                    evidence_dir,
                    {
                        "turn": turn_num,
                        "reasoning": reasoning,
                        "tool": call.name,
                        "input": call.input,
                        "url": snapshot.url,
                        "outcome": "done",
                    },
                    secret_values,
                )
            break

        url_before, snapshot_before = snapshot.url, snapshot.text
        element = snapshot.elements.get(call.input.get("ref", ""))
        try:
            if call.name != "goto" and element is None:
                raise ValueError(f"unknown ref {call.input.get('ref', '')!r} in the current snapshot")
            # AI-mode refs are invalidated by navigation and can be reassigned
            # after DOM changes. Derive and verify the replay ladder now, while
            # this snapshot still identifies the intended live element.
            targets = []
            if element is not None:
                from replaykit.compiler.candidates import derive

                targets = derive(page, element.ref, element.role, element.name)
            if policy is not None and call.name in {"click", "fill", "select", "goto"}:
                # A goto's destination is where the action lands, not where it starts --
                # checking snapshot.url here would let a disallowed navigation happen
                # first and only get caught on the step after it.
                check_url = call.input.get("url", snapshot.url) if call.name == "goto" else snapshot.url
                try:
                    check(
                        policy, url=check_url, action=call.name,
                        target_name=element.name if element else "",
                    )
                except PolicyViolation as exc:
                    _write_policy_violation(
                        evidence_dir or Path("evidence/_discovery_pending"),
                        url=check_url, action=call.name, reason=str(exc),
                    )
                    raise RuntimeError(f"policy blocked: {exc}") from exc
                except ApprovalRequired as exc:
                    if control is None:
                        raise RuntimeError(f"discovery stopped: {exc}") from exc
                    approved = await_approval(
                        page, spec.secret_inputs(), str(exc), control,
                        evidence_dir or Path("evidence/_discovery_pending"),
                    )
                    if not approved:
                        raise RuntimeError(f"discovery stopped: {exc}") from exc
            if call.name == "extract":
                text = locator_for(page, call.input["ref"]).inner_text()
                trace.outputs[call.input["output_name"]] = text.strip()
            else:
                _apply(page, call.name, call.input, inputs)
        except RuntimeError:
            raise
        except Exception as exc:
            snapshot = _redact_snapshot(capture(page), secret_values)
            if evidence_dir is not None:
                _log_turn(
                    evidence_dir,
                    {
                        "turn": turn_num,
                        "reasoning": reasoning,
                        "tool": call.name,
                        "input": call.input,
                        "url": snapshot.url,
                        "outcome": f"error: {exc}",
                    },
                    secret_values,
                )
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "is_error": True,
                    "content": f"{exc}\n\nLatest snapshot:\n{_observation(snapshot)}",
                }],
            })
            continue

        snapshot = _redact_snapshot(capture(page), secret_values)
        # goto has no locator candidates -- it isn't an action the Phase 1
        # replayer supports -- so it's never recorded as a replayable step.
        # The navigation itself already happened via _apply(); the model
        # just sees the resulting snapshot like any other action.
        if call.name != "goto":
            trace.steps.append(TraceStep(
                action=call.name,
                ref=call.input.get("ref", ""),
                role=element.role if element else "",
                name=element.name if element else "",
                value=call.input.get("value", ""),
                output_name=call.input.get("output_name", ""),
                url_before=url_before,
                url_after=snapshot.url,
                snapshot_before=snapshot_before,
                snapshot_after=snapshot.text,
                targets=targets,
            ))
        if evidence_dir is not None:
            _log_turn(
                evidence_dir,
                {
                    "turn": turn_num,
                    "reasoning": reasoning,
                    "tool": call.name,
                    "input": call.input,
                    "url": url_before,
                    "outcome": "ok",
                },
                secret_values,
            )
        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": _observation(snapshot),
            }],
        })

    return trace
