from unittest.mock import patch

from runtime import llamacpp


def test_find_server_prefers_native_binary_over_wrong_platform(tmp_path, monkeypatch):
    """BIN_DIR can hold both llama-server.exe (Windows) and llama-server (Linux)
    at once — a host dev machine and its Docker container share the same
    bind mount. Each OS must pick its own binary, never the other's."""
    (tmp_path / "llama-server.exe").touch()
    (tmp_path / "llama-server").touch()
    monkeypatch.setattr(llamacpp, "BIN_DIR", tmp_path)

    with patch.object(llamacpp.shutil, "which", return_value=None):
        with patch.object(llamacpp.os, "name", "nt"):
            assert llamacpp.find_server().name == "llama-server.exe"
        with patch.object(llamacpp.os, "name", "posix"):
            assert llamacpp.find_server().name == "llama-server"
