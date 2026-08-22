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
    # nudge instead of the payload. The caller must pass this in across a
    # resume, or the same write can get proposed again one click later.
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
