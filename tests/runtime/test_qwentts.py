from unittest.mock import MagicMock, patch

import pytest

from runtime import qwentts


def test_find_tts_server_prefers_native_binary_over_wrong_platform(tmp_path, monkeypatch):
    (tmp_path / "tts-server.exe").touch()
    (tmp_path / "tts-server").touch()
    monkeypatch.setattr(qwentts, "BIN_DIR", tmp_path)

    with patch.object(qwentts.shutil, "which", return_value=None):
        with patch.object(qwentts.os, "name", "nt"):
            assert qwentts.find_tts_server().name == "tts-server.exe"
        with patch.object(qwentts.os, "name", "posix"):
            assert qwentts.find_tts_server().name == "tts-server"


def _server(tmp_path) -> qwentts.TTSServer:
    return qwentts.TTSServer(
        talker_path=tmp_path / "talker.gguf",
        codec_path=tmp_path / "codec.gguf",
    )


def test_start_returns_self_when_already_running(tmp_path):
    server = _server(tmp_path)
    with patch.object(qwentts.TTSServer, "already_running", return_value=True):
        result = server.start()

    assert result is server
    assert server.reused is True


def test_start_spawns_process_and_polls_until_healthy(tmp_path, monkeypatch):
    monkeypatch.setattr(qwentts, "find_tts_server", lambda: tmp_path / "tts-server")
    server = _server(tmp_path)
    fake_process = MagicMock()
    fake_process.poll.return_value = None
    health_results = iter([False, True])

    with patch.object(qwentts.subprocess, "Popen", return_value=fake_process), \
         patch.object(qwentts.TTSServer, "already_running", side_effect=lambda: next(health_results)), \
         patch.object(qwentts.time, "sleep"):
        result = server.start(wait_seconds=5)

    assert result is server
    assert server.process is fake_process


def test_start_raises_and_cleans_up_when_process_exits_early(tmp_path, monkeypatch):
    monkeypatch.setattr(qwentts, "find_tts_server", lambda: tmp_path / "tts-server")
    server = _server(tmp_path)
    fake_process = MagicMock()
    fake_process.poll.return_value = 1
    fake_process.returncode = 1
    fake_process.stdout.read.return_value = "boom"

    with patch.object(qwentts.subprocess, "Popen", return_value=fake_process), \
         patch.object(qwentts.TTSServer, "already_running", return_value=False):
        with pytest.raises(RuntimeError, match="exited with 1"):
            server.start(wait_seconds=5)

    assert server.process is None


def test_stop_terminates_running_process(tmp_path):
    server = _server(tmp_path)
    fake_process = MagicMock()
    fake_process.poll.return_value = None
    server.process = fake_process
    qwentts._running.add(server)

    server.stop()

    fake_process.terminate.assert_called_once()
    assert server.process is None
