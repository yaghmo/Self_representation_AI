from runtime.chat_log import CHATS_DIR, append_summary, append_turn, clear, load_recent, log_path


def test_chat_log_self_check(tmp_path):
    path = tmp_path / "test.jsonl"

    # A missing file loads as empty, no summary — matches today's
    # behaviour exactly, so a fresh corpus with no log yet is a no-op.
    turns, summary = load_recent(path, window=20)
    assert turns == [], turns
    assert summary == "", repr(summary)

    # Writing a turn then reading it back round-trips byte-for-byte.
    append_turn(path, "user", "hello")
    append_turn(path, "assistant", "hi there")
    turns, summary = load_recent(path, window=20)
    assert turns == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ], turns
    assert summary == "", "no summary written yet"

    # The last summary record wins when more than one is present.
    append_summary(path, "first summary")
    append_summary(path, "second summary")
    _, summary = load_recent(path, window=20)
    assert summary == "second summary", summary

    # Only the last `window` turns come back; older ones are ignored,
    # not deleted — the file itself keeps growing underneath.
    for n in range(30):
        append_turn(path, "user", f"turn {n}")
    turns, _ = load_recent(path, window=5)
    assert [t["content"] for t in turns] == [f"turn {n}" for n in range(25, 30)], turns
    assert len(path.read_text(encoding="utf-8").splitlines()) > 5, (
        "load_recent must not truncate the file on disk"
    )

    # A corrupt/truncated line is skipped, not fatal, and does not take
    # the lines around it down with it.
    path.write_text(
        '{"role": "user", "content": "before"}\n'
        'not valid json at all\n'
        '{"role": "user", "content": "after"}\n',
        encoding="utf-8",
    )
    turns, _ = load_recent(path, window=20)
    assert [t["content"] for t in turns] == ["before", "after"], turns

    # A syntactically valid but non-dict JSON line (e.g. a bare scalar)
    # is skipped the same way, not a crash, and doesn't take the
    # well-formed records around it down with it.
    path.write_text(
        '{"role": "user", "content": "before"}\n'
        '42\n'
        '{"role": "user", "content": "after"}\n',
        encoding="utf-8",
    )
    turns, _ = load_recent(path, window=20)
    assert [t["content"] for t in turns] == ["before", "after"], turns

    # window=0 means "nothing", not "everything" — plain slicing would
    # read `[-0:]` as `[0:]` and hand back the full list, which would
    # make `history_window: 0` in stack.json silently rehydrate the
    # entire log instead of none of it.
    path.write_text(
        '{"role": "user", "content": "a"}\n'
        '{"type": "summary", "text": "sum"}\n',
        encoding="utf-8",
    )
    turns, summary = load_recent(path, window=0)
    assert turns == [], turns
    assert summary == "sum", summary

    # Admin and fan resolve to different files under the same root.
    admin_path = log_path(agent_mode=True)
    fan_path = log_path(agent_mode=False)
    assert admin_path != fan_path
    assert admin_path.parent == CHATS_DIR
    assert admin_path.name == "admin.jsonl"
    assert fan_path.name == "fan.jsonl"

    # clear() removes the file; clearing a file that doesn't exist is a
    # no-op, not an error — the Clear button doesn't know or care
    # whether anything has ever been written yet.
    append_turn(path, "user", "will be cleared")
    clear(path)
    assert not path.exists()
    clear(path)  # second call on an already-missing file must not raise
