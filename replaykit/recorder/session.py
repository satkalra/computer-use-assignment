from .snapshot import capture, locator_for
from .spec import FlowSpec
from .tools import TOOLS
from .trace import Trace, TraceStep


MODEL = "claude-sonnet-5"

_PROMPT = """You are recording a browser flow so it can be replayed later without a model.

Goal: {goal}

Inputs available to you (use these exact values):
{inputs}

Outputs you must extract before calling done: {outputs}

You see an accessibility snapshot. Every interactive element has a ref such as
[ref=e34]. Address elements ONLY by ref -- many inputs on this site have no
accessible name, so the surrounding text is your guide to what each one is.
Refs change after every action; always use the refs from the latest snapshot.
"""


def _observation(snapshot) -> str:
    return f"URL: {snapshot.url}\n\n{snapshot.text}"


def _apply(page, action: str, payload: dict) -> None:
    if action == "goto":
        page.goto(payload["url"])
        return

    locator = locator_for(page, payload["ref"])
    if action == "click":
        locator.click()
    elif action == "fill":
        locator.fill(payload["value"])
    elif action == "select":
        locator.select_option(label=payload["value"])


def record(page, spec: FlowSpec, inputs: dict[str, str], client, max_steps: int = 25) -> Trace:
    """Drive an injected model client over the page and record its tool actions."""
    trace = Trace(spec=spec)
    rendered_inputs = "\n".join(f"  {name}: {value}" for name, value in inputs.items())
    prompt = _PROMPT.format(
        goal=spec.goal,
        inputs=rendered_inputs,
        outputs=", ".join(spec.outputs) or "(none)",
    )

    snapshot = capture(page)
    messages = [{"role": "user", "content": f"{prompt}\n\n{_observation(snapshot)}"}]

    for _ in range(max_steps):
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

        call = next(
            (block for block in response.content if getattr(block, "type", "") == "tool_use"),
            None,
        )
        if call is None:
            break
        if call.name == "done":
            trace.status = "success"
            trace.outputs.update(call.input.get("outputs") or {})
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
            if call.name == "extract":
                text = locator_for(page, call.input["ref"]).inner_text()
                trace.outputs[call.input["output_name"]] = text.strip()
            else:
                _apply(page, call.name, call.input)
        except Exception as exc:
            snapshot = capture(page)
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

        snapshot = capture(page)
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
        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": _observation(snapshot),
            }],
        })

    return trace
