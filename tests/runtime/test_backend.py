from runtime.backend import LocalBackend, Message


def test_backend_self_check():
    # A plain message serialises as it always did — no null keys, because
    # llama-server rejects a tool_calls: null on a user turn.
    plain = Message("user", "hi")
    assert plain.as_dict() == {"role": "user", "content": "hi"}, plain.as_dict()

    # An assistant turn that called a tool carries the calls back verbatim:
    # the model must see its own call in the history or the tool result is
    # an answer to a question it never asked.
    call = {"id": "call_1", "type": "function",
            "function": {"name": "search_sources", "arguments": "{}"}}
    assistant = Message("assistant", "", tool_calls=[call])
    assert assistant.as_dict()["tool_calls"] == [call]

    # A tool result is addressed to the call it answers.
    result = Message("tool", "2 entries", tool_call_id="call_1")
    assert result.as_dict() == {
        "role": "tool", "content": "2 entries", "tool_call_id": "call_1"
    }

    # Tools reach the payload only when supplied.
    backend = LocalBackend()
    schema = [{"type": "function", "function": {"name": "noop", "parameters": {}}}]
    assert "tools" not in backend._payload([plain], False)
    assert backend._payload([plain], False, tools=schema)["tools"] == schema

    # Thinking gets extra room on top of max_tokens, so a <think> block can't
    # eat the whole answer budget; off leaves max_tokens untouched.
    assert backend._payload([plain], False, max_tokens=512, thinking=True)["max_tokens"] == 1536
    assert backend._payload([plain], False, max_tokens=512, thinking=False)["max_tokens"] == 512

    # repeat_penalty and repeat_last_n always ride along, even when the caller
    # passes nothing — llama-server's own defaults (1.0 / 64) leave a small
    # model free to regurgitate its own last reply once it's more than 64
    # tokens back in the context.
    assert backend._payload([plain], False)["repeat_penalty"] == 1.3
    assert backend._payload([plain], False, repeat_penalty=1.1)["repeat_penalty"] == 1.1
    assert backend._payload([plain], False)["repeat_last_n"] == 512
    assert backend._payload([plain], False, repeat_last_n=64)["repeat_last_n"] == 64


def test_backend_payload_seed_is_fixed_by_default():
    # A fixed default seed rides along on every request so the same
    # conversation reproduces the same reply, unless a caller overrides it.
    backend = LocalBackend()
    plain = Message("user", "hi")
    assert backend._payload([plain], False)["seed"] == 42
    assert backend._payload([plain], False, seed=7)["seed"] == 7
