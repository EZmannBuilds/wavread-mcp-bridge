"""Offline: the MCP server against a fake Remote Script on a local port (no Live). Checks the wire format, error
replies, the connection-refused hint, fragmented replies, the tool registry and the generated reference."""
import asyncio, importlib.util, json, os, socket, subprocess, sys, threading

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))


def load_server(port, new_var=False):
    for k in ("FADERHAND_PORT", "WAVREAD_BRIDGE_PORT"):
        os.environ.pop(k, None)
    os.environ["FADERHAND_PORT" if new_var else "WAVREAD_BRIDGE_PORT"] = str(port)
    spec = importlib.util.spec_from_file_location("srv_%d" % port, os.path.join(ROOT, "server", "ableton_tooling_server.py"))
    srv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(srv)
    return srv


class FakeLive:
    """Accepts one JSON request per connection and answers from a handler; records every request."""

    def __init__(self, handler, chunked=False):
        self.handler, self.chunked, self.requests = handler, chunked, []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            with c:
                req = json.loads(c.recv(1 << 20).decode())
                self.requests.append(req)
                data = json.dumps(self.handler(req)).encode()
                if self.chunked:
                    for i in range(0, len(data), 7):
                        c.sendall(data[i:i + 7])
                else:
                    c.sendall(data)

    def close(self):
        self.sock.close()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_request_shape_and_success():
    live = FakeLive(lambda r: {"status": "success", "result": {"echo": r}})
    srv = load_server(live.port)
    res = json.loads(srv.set_track_send(track="Keys", send="B", db=-14))
    assert live.requests[0]["type"] == "set_track_send"
    assert live.requests[0]["params"] == {"track": "Keys", "send": "B", "db": -14}
    assert res["echo"]["params"]["db"] == -14
    live.close()


def test_none_params_are_not_sent():
    live = FakeLive(lambda r: {"status": "success", "result": {}})
    srv = load_server(live.port)
    srv.create_track(kind="midi")
    assert "name" not in live.requests[0]["params"]
    live.close()


def test_error_reply_becomes_ok_false():
    live = FakeLive(lambda r: {"status": "error", "message": "refused: not authorized"})
    srv = load_server(live.port)
    res = json.loads(srv.delete_track(track=0))
    assert res == {"ok": False, "error": "refused: not authorized"}
    live.close()


def test_fragmented_reply_is_reassembled():
    big = {"names": ["track %d" % i for i in range(400)]}
    live = FakeLive(lambda r: {"status": "success", "result": big}, chunked=True)
    srv = load_server(live.port)
    assert json.loads(srv.list_tracks()) == big
    live.close()


def test_connection_refused_hint():
    srv = load_server(free_port())
    res = json.loads(srv.tooling_info())
    assert res["ok"] is False and "not listening" in res["error"]


def test_env_vars_new_name_wins_old_name_falls_back():
    for k in ("FADERHAND_HOST", "FADERHAND_PORT", "WAVREAD_BRIDGE_HOST", "WAVREAD_BRIDGE_PORT"):
        os.environ.pop(k, None)
    os.environ["WAVREAD_BRIDGE_PORT"], os.environ["WAVREAD_BRIDGE_HOST"] = "9911", "127.0.0.2"
    spec = importlib.util.spec_from_file_location("srv_env", os.path.join(ROOT, "server", "ableton_tooling_server.py"))
    old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
    assert (old.HOST, old.PORT) == ("127.0.0.2", 9911)
    os.environ["FADERHAND_PORT"], os.environ["FADERHAND_HOST"] = "9922", "127.0.0.3"
    new = importlib.util.module_from_spec(spec); spec.loader.exec_module(new)
    assert (new.HOST, new.PORT) == ("127.0.0.3", 9922)
    for k in ("FADERHAND_HOST", "FADERHAND_PORT", "WAVREAD_BRIDGE_HOST", "WAVREAD_BRIDGE_PORT"):
        os.environ.pop(k, None)
    d = importlib.util.module_from_spec(spec); spec.loader.exec_module(d)
    assert (d.HOST, d.PORT) == ("127.0.0.1", 9878)


def test_server_id_is_faderhand():
    assert load_server(free_port()).mcp.name == "faderhand"


def test_server_defaults_to_loopback():
    os.environ.pop("WAVREAD_BRIDGE_HOST", None)
    os.environ.pop("FADERHAND_HOST", None)
    srv = load_server(free_port())
    assert srv.HOST == "127.0.0.1"


def test_remote_script_binds_loopback_only():
    src = open(os.path.join(ROOT, "remote_script", "Faderhand", "__init__.py")).read()
    assert 'HOST = "127.0.0.1"' in src and "0.0.0.0" not in src


def test_every_tool_documented_and_grouped():
    import gen_tool_reference as g
    tools = g.load_tools()
    names = [t.name for t in tools]
    grouped = [n for grp in g.GROUPS.values() for n in grp]
    assert len(set(names)) == len(names)
    assert not set(names) - set(grouped), "tools with no group in tools/gen_tool_reference.py"
    for t in tools:
        assert len((t.description or "").strip()) > 20, t.name


def test_tool_reference_is_current():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "gen_tool_reference.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_wav_reverse_reverses_and_refuses_overwrite(tmp_path):
    import numpy as np, soundfile as sf
    x = np.linspace(-0.5, 0.5, 4800)
    a, b = str(tmp_path / "a.wav"), str(tmp_path / "b.wav")
    sf.write(a, x, 48000, subtype="FLOAT")
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "wav_reverse.py"), a, b], check=True, capture_output=True)
    y, _ = sf.read(b)
    assert np.allclose(y, x[::-1])
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "wav_reverse.py"), a, b], capture_output=True, text=True)
    assert r.returncode != 0 and "refused" in r.stderr


@pytest.mark.skipif(sys.platform != "darwin" and not os.path.exists("/bin/bash"), reason="needs bash")
def test_install_script_installs_and_uninstalls_into_a_fake_home(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path))
    bdir = os.path.join(ROOT, "backups", "installed")
    before = set(os.listdir(bdir)) if os.path.isdir(bdir) else set()
    script = os.path.join(ROOT, "tools", "install_remote_script.sh")
    subprocess.run(["bash", script], env=env, check=True, capture_output=True)
    dest = tmp_path / "Music" / "Ableton" / "User Library" / "Remote Scripts"
    installed = [p for p in dest.iterdir() if p.is_dir()]
    assert len(installed) == 1 and (installed[0] / "__init__.py").exists()
    subprocess.run(["bash", script, "--uninstall"], env=env, check=True, capture_output=True)
    assert not any(p.is_dir() for p in dest.iterdir())
    import shutil
    for name in set(os.listdir(bdir)) - before:          # the script backs up before uninstalling: drop ours
        shutil.rmtree(os.path.join(bdir, name))
