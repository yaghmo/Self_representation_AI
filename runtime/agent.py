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

from service.logging_config import get_logger, log_payload

from .backend import Message
from .bible import section_index
from .tools import (
    FOLLOWUP_SCHEMAS,
    TOOL_SCHEMAS,
    Proposal,
    entry_feeds,
    entry_id_of,
    read_profile_section,
    run_tool,
)

logger = get_logger("runtime.agent")

MAX_ITERATIONS = 8


@dataclass
class Step:
    """One observable thing the loop did. The UI renders these in order."""

    kind: str  # tool_call | tool_result | proposal | answer | stopped
    text: str = ""
    name: str = ""
    proposal: Proposal | None = None
    # Set on a `proposal` step. The loop stops there, and resuming means
    # answering *this* call id with what the creator decided. Without the id
    # and the history behind it, the next turn starts from a transcript in
    # which the model never called a tool — so it calls it again, and the
    # entry gets logged twice.
    call_id: str = ""
    history: list[Message] | None = None


def _result_message(call_id: str, text: str) -> Message:
    return Message("tool", text, tool_call_id=call_id)


def _elsewhere(index: Callable[[], str] | None) -> str:
    """The prompt fragment for facts that belong in an unlisted section.

    The `Feeds:` line is the model's judgement from the logging phase, and it
    gets it wrong: an answer giving a nationality, a species and an age was
    filed as feeding Background and Relationships, and the profile's Age field
    lives in Core Identity — so the age had nowhere to go and quietly went
    nowhere. Naming the gap is honest; writing into a section the entry never
    claimed is the agent overruling the record.
    """
    if index is None:
        return ""
    try:
        headings = index()
    except Exception:  # a missing profile is not a reason to lose the task
        return ""
    return (
        "If part of the entry belongs in a section that is not above, do not "
        "put it in one of these instead — say at the end which section it "
        "needs. The profile's sections are:\n\n"
        f"{headings}\n\n"
    )


def followup(
    entry: str,
    read_section: Callable[[str], str] = read_profile_section,
    index: Callable[[], str] | None = section_index,
) -> list[Message]:
    """The task that follows a logged entry: put it in the profile.

    A fresh, bounded conversation rather than a continuation of the chat. The
    entry names the sections it feeds and carries its own id, so everything
    the work needs is in this one message — which means the task is the same
    size on turn thirty as on turn one, and the model is not re-deriving what
    it is doing from a transcript it half remembers.
    """
    entry_id = entry_id_of(entry) or "the entry above"
    sections = entry_feeds(entry)
    if not sections:
        return [
            Message(
                "user",
                f"{entry}\n\nThis entry names no sections in its Feeds line, so "
                "there is nothing to add to the profile. Say so and stop.",
            )
        ]

    current = []
    for name in sections:
        try:
            current.append(read_section(name))
        except Exception as exc:  # a missing section is a fact, not a crash
            current.append(f"## {name}\n[could not read this section: {exc}]")

    joined = "\n\n".join(current)
    return [
        Message(
            "user",
            f"This entry was just logged:\n\n{entry}\n\n"
            f"It feeds {len(sections)} section(s): {', '.join(sections)}.\n"
            f"Here they are as they stand:\n\n{joined}\n\n"
            f"Record what {entry_id} says in each of those sections, one call "
            "at a time. The sections are above — you have everything you need, "
            "so do not go looking for more.\n\n"
            "If the section already has a line for this field — an Age row, a "
            "Nationality row, a **Family:** bullet — use `replace_profile_line` "
            "on that line, keeping every cite it already carries and adding "
            f"{entry_id}. Use `add_profile_line` only for a field that is not "
            "there at all. Never copy a line that is already in the section: "
            "leave the ones this entry does not change exactly as they are.\n\n"
            f"Every line you write carries {entry_id}. Match the shape already "
            "used — a row where there is a table, a bullet where there are "
            "bullets. One fact goes in one line: do not file the same thing "
            "again under a second label.\n\n"
            f"{_elsewhere(index)}"
            "When the sections are done, say what you changed and stop.",
        )
    ]


def resumed(step: Step, outcome: str) -> list[Message]:
    """The history to hand back to `run` once the creator has decided.

    The paused turn ends with an assistant message holding a tool call that
    nothing answered. Resuming without closing it leaves the model looking at
    its own unanswered call — so it repeats it, and the write happens twice.
    """
    if step.history is None:
        raise ValueError("only a proposal step can be resumed")
    return [*step.history, _result_message(step.call_id, outcome)]


def run(
    post: Callable[[list[Message], list[dict]], dict],
    messages: list[Message],
    max_iterations: int = MAX_ITERATIONS,
    tools: list[dict] | None = None,
    seen: dict[tuple[str, str], int] | None = None,
) -> Iterator[Step]:
    """Drive the model until it answers, proposes a write, or runs out of turns.

    Yields a Step per event so the caller can render as it goes. A write tool
    yields a `proposal` and the generator stops there: applying it is the
    creator's decision, and resuming is the caller's business — it calls `run`
    again with the tool result appended. Suspending inside a generator would
    hide that decision inside the loop, which is exactly the thing that has to
    be visible.
    """
    tools = TOOL_SCHEMAS if tools is None else tools
    # Offered and dispatchable are the same set. A model that names a tool it
    # was not given gets told so rather than having it run — otherwise the
    # restriction is a suggestion, and the whole point of restricting is that
    # a suggestion is what already failed.
    allowed = {schema["function"]["name"] for schema in tools}

    history = list(messages)
    # What it has already done. A small model asked to edit a profile will
    # happily read every section in the file, one turn each, and run out of
    # turns before it writes anything — so the second identical call gets a
    # nudge instead of the payload.
    #
    # The caller can pass this in, and for the confirm gate it must: every
    # Apply resumes through a fresh `run`, and a guard that forgets at each
    # resume does not guard the case that actually happens — the same write
    # proposed again one click later.
    seen = {} if seen is None else seen

    for iteration in range(max_iterations):
        logger.info("turn %d/%d, %d messages in history", iteration + 1, max_iterations, len(history))
        reply = post(history, tools)
        tool_calls = reply.get("tool_calls") or []

        if not tool_calls:
            content = reply.get("content", "")
            # A model that writes `<tool_call>` into its answer meant to call
            # one and the template did not parse it. Worth saying out loud —
            # from the loop's side it is indistinguishable from a plain reply.
            if "tool_call" in content:
                logger.warning(
                    "reply contains tool-call markup but no parsed call — "
                    "the chat template did not turn it into one:\n%s",
                    content[:1000],
                )
            yield Step("answer", text=content)
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

            log_payload(logger, f"tool {name} <<", arguments)

            if name not in allowed:
                refusal = (
                    f"{name} is not available for this task. You have: "
                    f"{', '.join(sorted(allowed))}."
                )
                logger.warning("refused out-of-scope tool %s", name)
                history.append(_result_message(call_id, refusal))
                yield Step("tool_result", text=refusal, name=name)
                continue

            signature = (name, json.dumps(arguments, sort_keys=True, default=str))
            seen[signature] = seen.get(signature, 0) + 1
            if seen[signature] > 1:
                repeat = (
                    f"you already called {name} with these arguments earlier in "
                    "this conversation — the answer has not changed. Use what it "
                    "returned and take the next step, or write the edit."
                )
                logger.warning("repeat call to %s — nudged instead of answered", name)
                history.append(_result_message(call_id, repeat))
                yield Step("tool_result", text=repeat, name=name)
                continue

            outcome = run_tool(name, arguments)
            logger.info(
                "tool %s >> %s",
                name,
                outcome.summary if isinstance(outcome, Proposal) else str(outcome)[:1000],
            )

            if isinstance(outcome, Proposal):
                # Stop here. The creator applies or rejects, then the caller
                # resumes by calling run() again with the result appended.
                yield Step(
                    "proposal",
                    name=name,
                    proposal=outcome,
                    text=outcome.summary,
                    call_id=call_id,
                    history=list(history),
                )
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

            # An invented name never reaches the dispatcher — it fails the
            # offered-set check first, which also tells the model what it does
            # have. Either way it is a result, not an exception: the model gets
            # a chance to correct itself.
            steps = list(run(bad_tool, [Message("user", "hi")]))
            assert "not available for this task" in steps[1].text, steps[1]
            assert "search_sources" in steps[1].text, steps[1]
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

            # Asking the same question twice gets a nudge, not the payload
            # again — re-reading is how a small model spends eight turns
            # without writing anything.
            def rereads(messages, tools_schema):
                if len(messages) < 6:
                    return {
                        "content": "",
                        "tool_calls": [call("search_sources", '{"query": "alpha"}')],
                    }
                return {"content": "moved on", "tool_calls": []}

            steps = list(run(rereads, [Message("user", "hi")]))
            results = [s.text for s in steps if s.kind == "tool_result"]
            assert "alpha answer" in results[0], results[0]
            assert "already called" in results[1], results[1]
            assert steps[-1].text == "moved on"

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

            # Resuming closes the tool call the pause left open. A model that
            # comes back to an unanswered call of its own repeats it — which is
            # how one answer gets logged as two entries.
            assert pause.call_id == "c1", pause.call_id
            continued = resumed(pause, "applied")
            assert continued[-1].as_dict() == {
                "role": "tool", "content": "applied", "tool_call_id": "c1"
            }, continued[-1]
            assistant = [m for m in continued if m.role == "assistant"]
            assert assistant and assistant[-1].tool_calls, "the call itself must survive the pause"

            def after_apply(messages, tools_schema):
                assert messages[-1].role == "tool", "the loop must resume with the result"
                return {"content": "logged", "tool_calls": []}

            steps = list(run(after_apply, continued))
            assert [s.kind for s in steps] == ["answer"], steps

            # A tool outside the offered set is refused, not dispatched. In the
            # follow-up phase the entry is already logged, and the system
            # prompt still opens by saying to log one — so the loop must be
            # able to say no to a call the prompt invited.
            def logs_again(messages, tools_schema):
                if len(messages) < 3:
                    return {
                        "content": "",
                        "tool_calls": [call("append_source", '{"answer": "x", "feeds": []}')],
                    }
                return {"content": "fine", "tool_calls": []}

            steps = list(run(logs_again, [Message("user", "hi")], tools=FOLLOWUP_SCHEMAS))
            assert "not available for this task" in steps[1].text, steps[1]
            assert "add_profile_line" in steps[1].text, steps[1]
            assert sources.read_text(encoding="utf-8") == corpus, "a refused tool writes nothing"
            assert steps[-1].text == "fine"

            # The repeat guard can be carried by the caller, because every
            # Apply resumes through a fresh run — a guard that resets there
            # does not guard the case that happens.
            carried: dict = {}
            first = list(run(rereads, [Message("user", "hi")], max_iterations=1, seen=carried))
            assert first[-1].kind == "stopped", first
            again = list(run(rereads, [Message("user", "hi")], max_iterations=1, seen=carried))
            assert "already called" in again[1].text, again[1]

            # The follow-up task is built from the entry alone: its id, the
            # sections its Feeds line names, and how those sections read now.
            # No chat history, so it is the same size on turn thirty as on one.
            entry = (
                "### S-042\n"
                "- **Date:** 2026-01-09\n"
                "- **Q:** placeholder question\n"
                "- **A:** placeholder answer\n"
                "- **Feeds:** 0. At a Glance, 6. Voice\n"
            )
            asked: list[str] = []

            def fake_section(name: str) -> str:
                asked.append(name)
                return f"## {name}\n- existing line [S-001]\n"

            task = followup(entry, read_section=fake_section)
            assert asked == ["0. At a Glance", "6. Voice"], asked
            assert len(task) == 1 and task[0].role == "user", task
            body = task[0].content
            assert "S-042" in body and "placeholder answer" in body, body
            assert "existing line [S-001]" in body, "the sections must come in with the task"
            assert "at a time" in body, body

            # An entry feeding nothing says so rather than sending the model
            # looking for somewhere to put it.
            nowhere = followup("### S-043\n- **Feeds:** —\n", read_section=fake_section)
            assert "nothing to add" in nowhere[0].content, nowhere[0].content

            # A section that cannot be read is reported, not raised — the other
            # sections in the same entry still get their line.
            def broken(name: str) -> str:
                raise KeyError(f"no section {name!r}")

            degraded = followup(entry, read_section=broken)
            assert "could not read this section" in degraded[0].content
        finally:
            tools.SOURCES_PATH = real_sources

    print("agent self-check: ok")


if __name__ == "__main__":
    _self_check()
