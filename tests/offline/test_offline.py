"""Offline checks that need neither Ableton Live nor a Remote Script connection (run in CI).

- Both Remote Script modules and every tool compile.
- The MCP server imports and registers its tools with valid schemas.
- tools/audio_check.py measures a synthetic file correctly.
run: uv run --with "mcp[cli]>=1.9,<2" --with numpy --with soundfile --with pyloudnorm --with scipy --with pytest pytest tests/offline
"""
import asyncio, glob, importlib.util, json, os, py_compile, subprocess, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def test_everything_compiles():
    files = glob.glob(os.path.join(ROOT, "remote_script", "*", "*.py")) + glob.glob(os.path.join(ROOT, "server", "*.py")) \
        + glob.glob(os.path.join(ROOT, "tools", "*.py")) + glob.glob(os.path.join(ROOT, "tests", "*.py"))
    assert files
    for f in files:
        py_compile.compile(f, doraise=True)


def test_server_registers_tools():
    spec = importlib.util.spec_from_file_location("srv", os.path.join(ROOT, "server", "ableton_tooling_server.py"))
    srv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(srv)
    tools = asyncio.run(srv.mcp.list_tools())
    names = {t.name for t in tools}
    assert len(names) == len(tools) >= 70
    for required in ("tooling_info", "set_track_send", "load_effect_on_return_track", "create_audio_bus", "validate_routing"):
        assert required in names
    for t in tools:
        assert t.description and t.inputSchema.get("type") == "object"


def test_audio_check_on_a_sine(tmp_path):
    import numpy as np, soundfile as sf
    sr = 48000
    x = 0.25 * np.sin(2 * np.pi * 1000 * np.arange(sr * 3) / sr)
    path = str(tmp_path / "sine.wav")
    sf.write(path, np.stack([x, x], axis=1), sr)
    out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "audio_check.py"), path],
                         capture_output=True, text=True, check=True).stdout
    r = json.loads(out.strip().splitlines()[0])
    assert r["sample_rate"] == 48000 and r["channels"] == 2
    assert abs(r["seconds"] - 3.0) < 0.01
    assert abs(r["peak_dbfs"] - (-12.04)) < 0.1      # 0.25 amplitude
    assert r["clipped_samples"] == 0 and not r["silent"]
