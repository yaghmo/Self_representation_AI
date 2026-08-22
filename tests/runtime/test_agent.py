import json

from runtime import tools
from runtime.agent import followup, resumed, run
from runtime.backend import Message
from runtime.tools import FOLLOWUP_SCHEMAS


def test_agent_self_check(tmp_path):
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
    sources = tmp_path / "sources.md"
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
