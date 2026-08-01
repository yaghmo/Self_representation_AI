"""The agent loop. Written here, not imported.

An agent is a loop: the model emits a tool call, code runs it, the result goes
back in, repeat until it stops. Wrapping that in a framework puts abstraction
exactly where local models break — malformed calls, runaway repetition, a tool
result the model ignores — which is where you most need to see what happened.

The loop runs client-side. The service passes tools through and returns tool
calls but never executes one, so no deployment can reach `data/` over HTTP.

`post` is injected: the caller supplies something that speaks POST /chat, and
the self-check supplies a script. That is the whole reason this is testable
without a model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Iterator

from .backend import Message
from .tools import TOOL_SCHEMAS, Proposal, run_tool

MAX_ITERATIONS = 8


@dataclass
class Step:
    """One observable thing the loop did. The UI renders these in order."""

    kind: str  # tool_call | tool_result | proposal | answer | stopped
    text: str = ""
    name: str = ""
    proposal: Proposal | None = None


def _result_message(call_id: str, text: str) -> Message:
    return Message("tool", text, tool_call_id=call_id)


def run(
    post: Callable[[list[Message], list[dict]], dict],
    messages: list[Message],
    max_iterations: int = MAX_ITERATIONS,
) -> Iterator[Step]:
    """Drive the model until it answers, proposes a write, or runs out of turns.

    Yields a Step per event so the caller can render as it goes. A write tool
    yields a `proposal` and the generator stops there: applying it is the
    creator's decision, and resuming is the caller's business — it calls `run`
    again with the tool result appended. Suspending inside a generator would
    hide that decision inside the loop, which is exactly the thing that has to
    be visible.
    """
    history = list(messages)

    for _ in range(max_iterations):
        reply = post(history, TOOL_SCHEMAS)
        tool_calls = reply.get("tool_calls") or []

        if not tool_calls:
            yield Step("answer", text=reply.get("content", ""))
            return

        history.append(Message("assistant", reply.get("content", ""), tool_calls=tool_calls))

        for call in tool_calls:
            function = call.get("function") or {}
            name = function.get("name", "")
            call_id = call.get("id", "")
            yield Step("tool_call", text=function.get("arguments", ""), name=name)

            raw = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError as exc:
                text = f"could not parse the arguments to {name}: {exc}"
                history.append(_result_message(call_id, text))
                yield Step("tool_result", text=text, name=name)
                continue

            if not isinstance(arguments, dict):
                text = f"the arguments to {name} must be a JSON object, got {type(arguments).__name__}"
                history.append(_result_message(call_id, text))
                yield Step("tool_result", text=text, name=name)
                continue

            outcome = run_tool(name, arguments)

            if isinstance(outcome, Proposal):
                # Stop here. The creator applies or rejects, then the caller
                # resumes by calling run() again with the result appended.
                yield Step("proposal", name=name, proposal=outcome, text=outcome.summary)
                return

            history.append(_result_message(call_id, outcome))
            yield Step("tool_result", text=outcome, name=name)

    yield Step(
        "stopped",
        text=(
            f"stopped after {max_iterations} turns without an answer — the "
            "model kept calling tools. Say what you want in fewer steps, or "
            "check the tool results above for one it is misreading."
        ),
    )


def _self_check() -> None:
    import tempfile
    from pathlib import Path

    from . import tools

    def call(name: str, arguments: str) -> dict:
        return {
            "id": "c1",
            "type": "function",
            "function": {"name": name, "arguments": arguments},
        }

    # Point the tools at a fixture corpus: the loop must be testable without
    # data/ existing, and a self-check that reads the creator's real file
    # would pass or fail for reasons that have nothing to do with the loop.
    corpus = (
        "# Sources\n\n"
        "## Source log\n\n"
        "### S-001\n"
        "- **Date:** 2026-01-01\n"
        "- **Type:** direct answer\n"
        "- **Tags:** alpha\n"
        "- **Q:** placeholder question one\n"
        "- **A:** alpha answer\n"
        "- **Feeds:** 6. Voice\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        sources = Path(tmp) / "sources.md"
        sources.write_text(corpus, encoding="utf-8")
        real_sources = tools.SOURCES_PATH
        tools.SOURCES_PATH = sources
        try:
            calls: list[dict] = []

            def scripted(messages, tools_schema):
                calls.append({"n": len(messages)})
                if len(calls) == 1:
                    return {
                        "content": "",
                        "tool_calls": [
                            call("search_sources", '{"query": "nothing matches this"}')
                        ],
                    }
                return {"content": "done", "tool_calls": []}

            steps = list(run(scripted, [Message("user", "hi")]))
            assert [s.kind for s in steps] == ["tool_call", "tool_result", "answer"], steps
            assert steps[-1].text == "done"
            assert len(calls) == 2, "the tool result must go back for a second turn"

            # An unknown tool comes back as a result, not an exception: the
            # model gets a chance to correct itself.
            def bad_tool(messages, tools_schema):
                if len(messages) < 3:
                    return {"content": "", "tool_calls": [call("nope", "{}")]}
                return {"content": "recovered", "tool_calls": []}

            steps = list(run(bad_tool, [Message("user", "hi")]))
            assert "no such tool" in steps[1].text, steps[1]
            assert steps[-1].text == "recovered"

            # Malformed JSON arguments are a result too, not a crash.
            def bad_json(messages, tools_schema):
                if len(messages) < 3:
                    return {"content": "", "tool_calls": [call("search_sources", "{not json")]}
                return {"content": "ok", "tool_calls": []}

            steps = list(run(bad_json, [Message("user", "hi")]))
            assert "could not parse" in steps[1].text, steps[1]

            # Valid JSON that is not an object would blow up on **arguments.
            def not_an_object(messages, tools_schema):
                if len(messages) < 3:
                    return {"content": "", "tool_calls": [call("search_sources", '"query"')]}
                return {"content": "ok", "tool_calls": []}

            steps = list(run(not_an_object, [Message("user", "hi")]))
            assert "must be a JSON object" in steps[1].text, steps[1]

            # A model that never answers is stopped rather than left to spin.
            def never_stops(messages, tools_schema):
                return {"content": "", "tool_calls": [call("search_sources", '{"query": "x"}')]}

            steps = list(run(never_stops, [Message("user", "hi")], max_iterations=3))
            assert steps[-1].kind == "stopped", steps[-1]
            assert "3" in steps[-1].text, steps[-1].text

            # A write pauses: the proposal is yielded and nothing continues
            # until the caller decides.
            def wants_to_write(messages, tools_schema):
                return {
                    "content": "",
                    "tool_calls": [
                        call(
                            "append_source",
                            json.dumps(
                                {
                                    "answer": "placeholder answer",
                                    "question": "placeholder question",
                                    "entry_type": "direct answer",
                                    "tags": ["placeholder"],
                                    "date": "unknown",
                                    "feeds": [],
                                }
                            ),
                        )
                    ],
                }

            loop = run(wants_to_write, [Message("user", "hi")])
            first = next(loop)
            assert first.kind == "tool_call"
            pause = next(loop)
            assert pause.kind == "proposal", pause
            assert pause.proposal is not None and pause.proposal.diff
            assert sources.read_text(encoding="utf-8") == corpus, "a proposal writes nothing"
        finally:
            tools.SOURCES_PATH = real_sources

    print("agent self-check: ok")


if __name__ == "__main__":
    _self_check()
