"""Internet play: the desktop app's Cloudflare quick tunnel. A stand-in for cloudflared prints
what the real one does, so no tunnel is opened."""

import sys
import time

import pytest

import desktop.tunnel as tunnel_module
from desktop.app import Desktop, JoinedGames
from desktop.tunnel import Tunnel, TunnelError
from tests.test_desktop import FakeWindow, host_app  # noqa: F401 (fixture)

ADDRESS = "https://quiet-fox-runs.trycloudflare.com"

# What cloudflared logs while it opens a quick tunnel (abridged), then it keeps running.
WORKING = f"""
import sys, time
print("INF Requesting new quick Tunnel on trycloudflare.com...", file=sys.stderr, flush=True)
print("INF |  {ADDRESS}  |", file=sys.stderr, flush=True)
print("INF args:", sys.argv[1:], file=sys.stderr, flush=True)
time.sleep(60)
"""
FAILING = """
import sys
print("ERR failed to request quick Tunnel: no network", file=sys.stderr, flush=True)
sys.exit(1)
"""


def fake(tmp_path, source):
    script = tmp_path / "fake_cloudflared.py"
    script.write_text(source)
    return [sys.executable, str(script)]


def test_reads_the_public_address_and_stops(tmp_path):
    tunnel = Tunnel(52814, fake(tmp_path, WORKING))
    assert tunnel.start(timeout=20) == ADDRESS
    process = tunnel._process
    assert process.poll() is None  # still forwarding
    tunnel.stop()
    assert process.poll() is not None and tunnel.url is None


def test_points_cloudflared_at_the_local_port(tmp_path, monkeypatch):
    seen = []
    real_popen = tunnel_module.subprocess.Popen
    monkeypatch.setattr(
        tunnel_module.subprocess,
        "Popen",
        lambda args, **kw: seen.append(args) or real_popen(args, **kw),
    )
    tunnel = Tunnel(4321, fake(tmp_path, WORKING))
    tunnel.start(timeout=20)
    tunnel.stop()
    assert seen[0][-4:] == ["tunnel", "--no-autoupdate", "--url", "http://localhost:4321"]


def test_explains_a_tunnel_that_fails(tmp_path):
    tunnel = Tunnel(52814, fake(tmp_path, FAILING))
    started = time.monotonic()
    with pytest.raises(TunnelError, match="no network"):
        tunnel.start(timeout=20)
    assert time.monotonic() - started < 10  # gave up when cloudflared exited, not at the timeout


def test_missing_cloudflared_without_a_package_manager_explains(monkeypatch):
    monkeypatch.setattr(tunnel_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(tunnel_module, "_known_locations", lambda: [])
    monkeypatch.setattr(tunnel_module.sys, "platform", "linux")
    with pytest.raises(TunnelError, match="github.com/cloudflare/cloudflared"):
        Tunnel(52814).start()


def test_sharing_hosts_tunnels_once_and_stops_with_hosting(host_app, tmp_path):  # noqa: F811
    app, url = host_app
    desktop = Desktop(app, f"{url}/", JoinedGames(tmp_path / "joined.json"))
    desktop._window = FakeWindow(f"{url}/")
    command = fake(tmp_path, WORKING)

    assert desktop._share_online(command) == ADDRESS  # starts hosting too
    lan = desktop.info()["lan_url"]
    assert lan and desktop._tunnel.port == int(lan.rsplit(":", 1)[1])
    assert desktop.info()["public_url"] == ADDRESS
    process = desktop._tunnel._process
    assert desktop._share_online(command) == ADDRESS and desktop._tunnel._process is process

    desktop._window.url = f"{ADDRESS}/?game=abc"
    desktop.verify_current()
    assert "You hosted this game" in desktop._window.dialogs[-1]

    desktop._window.url = f"{url}/"
    desktop.stop_hosting()
    assert process.poll() is not None
    assert desktop.info() == {"own_page": True, "lan_url": None, "public_url": None}
