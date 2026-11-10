#!/usr/bin/env python3
"""Write docs/TOOL-REFERENCE.md from the MCP server's own tool registry, grouped. No Live needed.

run: uv run --with "mcp[cli]>=1.9,<2" python tools/gen_tool_reference.py [--check]
--check exits non-zero if the file on disk is out of date or a tool has no group (CI uses it).
"""
import asyncio, importlib.util, os, re, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "docs", "TOOL-REFERENCE.md")

# Group -> tools, in display order. Every registered tool must appear exactly once (tests/offline enforces it).
GROUPS = {
    "Connection and inspection": ["tooling_info", "probe", "reload_extensions"],
    "Write authorization": ["get_set_identity", "write_status", "authorize_set", "confirm_authorization", "set_approval_mode", "revoke_authorization"],
    "Tracks and mixer": ["list_tracks", "create_track", "rename_track", "delete_track", "set_mixer", "set_arm"],
    "Return tracks and sends": ["list_return_tracks", "create_return_track", "rename_return_track",
                                "get_return_track_devices", "load_effect_on_return_track",
                                "get_return_device_parameters", "set_return_device_parameter", "set_return_volume",
                                "inspect_return_routing", "get_track_sends", "set_track_send", "send_curve"],
    "Routing and audio buses": ["get_routing", "set_routing", "set_monitoring", "get_routing_graph",
                                "validate_routing", "create_audio_bus", "route_track_to_bus", "route_multiple_tracks",
                                "set_bus_volume", "set_bus_effect_chain"],
    "Devices and parameters": ["get_track_devices", "load_effect", "get_device_parameters", "set_device_parameter",
                               "set_device_parameters", "set_device_on", "move_device", "delete_device",
                               "snapshot_device", "restore_device_snapshot"],
    "Racks": ["create_effect_rack", "add_rack_chain", "insert_device_in_chain", "set_chain_mixer", "set_rack_macros"],
    "Sidechain": ["inspect_device_sidechain", "set_sidechain"],
    "Automation": ["list_automatable_parameters", "set_automation_points", "set_automation_curve", "get_automation",
                   "delete_automation", "copy_automation", "validate_automation", "record_arrangement_automation",
                   "param_state", "re_enable_automation", "back_to_arrangement"],
    "Clips, audio and recording": ["get_clip", "set_clip", "warp_marker", "create_audio_clip", "make_test_clip",
                                   "fire_clip", "duplicate_to_arrangement", "record_track_audio"],
    "Arrangement editing": ["list_arrangement_clips", "move_arrangement_clip", "copy_arrangement_clip",
                            "trim_arrangement_clip", "split_arrangement_clip", "create_arrangement_midi_clip"],
    "Transport, time and metering": ["transport", "set_song_time", "measure_levels", "capture"],
}


def load_tools():
    spec = importlib.util.spec_from_file_location("srv", os.path.join(ROOT, "server", "ableton_tooling_server.py"))
    srv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(srv)
    return asyncio.run(srv.mcp.list_tools())


def signature(t):
    props = t.inputSchema.get("properties", {})
    req = set(t.inputSchema.get("required", []))
    return ", ".join(k if k in req else k + "?" for k in props)


def render(tools):
    by = {t.name: t for t in tools}
    grouped = [n for g in GROUPS.values() for n in g if n in by]
    lines = ["# Tool reference", "",
             "Generated from the server's registry by `tools/gen_tool_reference.py`; do not edit by hand.",
             "`arg?` is optional. Status per feature: `docs/CAPABILITY-MATRIX.md`. Units and conventions: `docs/TOOLS.md`.",
             "", "**%d tools.**" % len(tools), ""]
    for g, names in GROUPS.items():
        present = [n for n in names if n in by]
        if not present:
            continue
        lines += ["## %s" % g, "", "| Tool | Arguments | What it does |", "|---|---|---|"]
        for n in present:
            d = " ".join((by[n].description or "").split())
            first = re.split(r"(?<!e\.g)(?<!i\.e)(?<!\.)\.\s+(?=[A-Z`'\"(])", d)[0].rstrip(".") + "." if d else ""
            lines.append("| `%s` | %s | %s |" % (n, signature(by[n]).replace("|", "\\|") or "none", first.replace("|", "\\|")))
        lines.append("")
    return "\n".join(lines), sorted(set(by) - set(grouped))


if __name__ == "__main__":
    text, ungrouped = render(load_tools())
    if ungrouped:
        print("tools with no group:", ", ".join(ungrouped))
    if "--check" in sys.argv:
        same = os.path.exists(OUT) and open(OUT).read() == text
        print("TOOL-REFERENCE.md", "up to date" if same else "OUT OF DATE")
        sys.exit(0 if same and not ungrouped else 1)
    open(OUT, "w").write(text)
    print("wrote", OUT)
    sys.exit(1 if ungrouped else 0)
