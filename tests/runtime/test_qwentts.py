from unittest.mock import MagicMock, patch

import pytest

from runtime import qwentts


def _server(tmp_path) -> qwentts.TTSServer:
    model_dir = tmp_path / "qwen3-tts-gguf-base"
    model_dir.mkdir()
    return qwentts.TTSServer(
        talker_path=model_dir / "qwen-talker-1.7b-base-Q8_0.gguf",
        codec_path=model_dir / "qwen-tokenizer-12hz-Q8_0.gguf",
        port=8091,
    )


def test_command_builds_correct_docker_invocation(tmp_path):
    server = _server(tmp_path)
    model_dir = server.talker_path.parent

    command = server.command()

    assert command[:3] == ["docker", "run", "--rm"]
    assert "--name" in command and command[command.index("--name") + 1] == "qwentts-8091"
    assert "--gpus" in command and command[command.index("--gpus") + 1] == "all"
    assert "-p" in command and command[command.index("-p") + 1] == "8091:8080"
    assert f"{model_dir.as_posix()}:/models:ro" in command
    assert "MODEL_PATH=/models/qwen-talker-1.7b-base-Q8_0.gguf" in command
    assert "CODEC_PATH=/models/qwen-tokenizer-12hz-Q8_0.gguf" in command
    assert command[-1] == qwentts.IMAGE


def test_start_returns_self_when_already_running(tmp_path):
    server = _server(tmp_path)
    with patch.object(qwentts.TTSServer, "already_running", return_value=True):
        result = server.start()

    assert result is server
    assert server.reused is True


def test_start_spawns_container_and_polls_until_healthy(tmp_path):
    server = _server(tmp_path)
    fake_process = MagicMock()
    fake_process.poll.return_value = None
    health_results = iter([False, True])

    with patch.object(qwentts.subprocess, "run") as mock_run, \
         patch.object(qwentts.subprocess, "Popen", return_value=fake_process), \
         patch.object(qwentts.TTSServer, "already_running", side_effect=lambda: next(health_results)), \
         patch.object(qwentts.time, "sleep"):
        result = server.start(wait_seconds=5)

    assert result is server
    assert server.process is fake_process
    # The pre-flight `docker rm -f` cleanup ran before spawning.
    assert mock_run.call_args[0][0][:3] == ["docker", "rm", "-f"]


def test_start_raises_and_cleans_up_when_container_exits_early(tmp_path):
    server = _server(tmp_path)
    fake_process = MagicMock()
    fake_process.poll.return_value = 1
    fake_process.returncode = 1
    fake_process.stdout.read.return_value = "boom"

    with patch.object(qwentts.subprocess, "run"), \
         patch.object(qwentts.subprocess, "Popen", return_value=fake_process), \
         patch.object(qwentts.TTSServer, "already_running", return_value=False):
        with pytest.raises(RuntimeError, match="exited with 1"):
            server.start(wait_seconds=5)

    assert server.process is None


def test_stop_stops_the_named_container(tmp_path):
    server = _server(tmp_path)
    fake_process = MagicMock()
    fake_process.poll.return_value = None
    server.process = fake_process
    qwentts._running.add(server)

    with patch.object(qwentts.subprocess, "run") as mock_run:
        server.stop()

    assert mock_run.call_args[0][0] == ["docker", "stop", "qwentts-8091"]
    assert server.process is None
