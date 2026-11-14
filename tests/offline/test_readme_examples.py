"""Offline: every tool call in the README's Examples block names a real tool, uses only real arguments and passes
every required one. Keeps the documentation honest as tools change."""
import asyncio, importlib.util, os, re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def test_readme_examples_match_tool_schemas():
    spec = importlib.util.spec_from_file_location("srv_readme", os.path.join(ROOT, "server", "ableton_tooling_server.py"))
    srv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(srv)
    tools = {t.name: t for t in asyncio.run(srv.mcp.list_tools())}
    s = open(os.path.join(ROOT, "README.md")).read()
    block = s[s.index("## Examples"):s.index("## What is tested")]
    code = block[block.index("```text") + 7:block.rindex("```")]
    calls = []
    for m in re.finditer(r"^([a-z_]+)\(", code, re.M):
        j, depth = m.end(), 1
        while depth:
            depth += {"(": 1, ")": -1}.get(code[j], 0)
            j += 1
        calls.append((m.group(1), code[m.end():j - 1]))
    assert len(calls) >= 15
    for name, args in calls:
        assert name in tools, name
        props = tools[name].inputSchema.get("properties", {})
        keys = re.findall(r'(?<![\w"])(\w+)=', args)
        assert not [k for k in keys if k not in props], (name, keys)
        assert not set(tools[name].inputSchema.get("required", [])) - set(keys), name


def test_readme_names_and_mcp_command():
    s = open(os.path.join(ROOT, "README.md")).read()
    assert s.startswith("# Faderhand, for Ableton Live 12\n")
    assert ('claude mcp add faderhand -s user -- uv run -q --with "mcp[cli]>=1.9,<2" python '
            '/absolute/path/to/faderhand/server/ableton_tooling_server.py') in s
    assert "claude mcp remove wavread-bridge -s user" in s
    assert "do not enable both" in s.lower()
    assert os.path.exists(os.path.join(ROOT, "server", "ableton_tooling_server.py"))
