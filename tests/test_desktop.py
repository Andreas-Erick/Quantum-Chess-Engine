"""The desktop launcher: its embedded server and options. (The window itself needs a display.)"""

import httpx
import pytest

from desktop.app import free_port, parse_args, start_server


def test_embedded_server_serves_api_and_ui(tmp_path):
    (tmp_path / "index.html").write_text("<title>Quantum Chess</title>")
    port = free_port("127.0.0.1")
    server = start_server("127.0.0.1", port, ui_dir=tmp_path)
    try:
        base = f"http://127.0.0.1:{port}"
        assert httpx.get(f"{base}/health").json() == {"status": "ok"}
        assert "Quantum Chess" in httpx.get(f"{base}/").text
        assert httpx.post(f"{base}/online/create", json={}).status_code == 200
    finally:
        server.should_exit = True


def test_options():
    assert parse_args([]).server is None and not parse_args([]).lan
    assert parse_args(["--server", "https://example.org"]).server == "https://example.org"
    assert parse_args(["--lan", "--port", "9000"]).port == 9000
    with pytest.raises(SystemExit):
        parse_args(["--lan", "--server", "https://example.org"])
