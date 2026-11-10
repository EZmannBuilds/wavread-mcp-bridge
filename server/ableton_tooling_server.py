"""ableton-tooling: an MCP server for Ableton Live 12 mixing and routing work, beside the `ableton` server (ahujasid/ableton-mcp).

It talks to the WavReadBridge Remote Script (127.0.0.1:9878). The `ableton` server (uvx ableton-mcp, port 9877)
keeps composing, clips, notes and rendering; this one adds return tracks, sends in dB, mixer, routing, audio buses,
device chains, parameter snapshots and meters.

Track references (every `track` argument): an index (0 = first track), "track:N", "return:A" (or "return:0", or
"return:Reverb"), "master", or an exact track name. Returns are addressed through song.return_tracks, never through
normal track indices.

Units: `db` arguments are dB exactly as Live displays them (the tool writes DeviceParameter.display_value and reads the
display back); raw values are Live's internal parameter values (min..max). Every write returns the read-back.
run: uv run --with "mcp[cli]>=1.9,<2" python server/ableton_tooling_server.py
"""
import json
import os
import socket
import time
from typing import Any, Optional, Union

from mcp.server.fastmcp import FastMCP

HOST = os.environ.get("WAVREAD_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("WAVREAD_BRIDGE_PORT", "9878"))
mcp = FastMCP("wavread-mcp-bridge")
Ref = Union[int, str]


class LiveError(RuntimeError):
    pass


def call(command: str, timeout: float = 30.0, **params) -> Any:
    """One request on a fresh connection; raises LiveError on an error reply."""
    params = {k: v for k, v in params.items() if v is not None}
    with socket.create_connection((HOST, PORT), timeout=5) as s:
        s.settimeout(timeout)
        s.sendall(json.dumps({"type": command, "params": params}).encode())
        buf, dec = b"", json.JSONDecoder()
        while True:
            chunk = s.recv(1 << 20)
            if not chunk:
                raise LiveError("WavReadBridge closed the connection")
            buf += chunk
            try:
                reply, _ = dec.raw_decode(buf.decode())
                break
            except ValueError:
                continue
    if reply.get("status") != "success":
        raise LiveError(reply.get("message", "unknown error"))
    return reply["result"]


def retry(command: str, tries: int = 6, wait: float = 0.25, **params) -> Any:
    """For routing calls right after a track is created: Live fills routing lists on the next tick."""
    for k in range(tries):
        try:
            return call(command, **params)
        except LiveError as e:
            if "not ready" not in str(e) and "not offered" not in str(e) and "cannot route" not in str(e) or k == tries - 1:
                raise
            time.sleep(wait)


def out(x: Any) -> str:
    return json.dumps(x, indent=1, default=str)


def guarded(fn):
    import functools

    @functools.wraps(fn)
    def wrap(*a, **k):
        try:
            return fn(*a, **k)
        except (LiveError, OSError) as e:
            hint = ""
            if isinstance(e, ConnectionRefusedError):
                hint = (" (WavReadBridge is not listening on %s:%d: pick it in Live > Settings > Link, Tempo & MIDI > "
                        "Control Surface, or restart Live)" % (HOST, PORT))
            return out({"ok": False, "error": str(e) + hint})
    return wrap


# ------------------------------------------------------------------ session
@mcp.tool()
@guarded
def tooling_info() -> str:
    """Handshake: the WavReadBridge Remote Script's version, Live's version, track and return counts, whether the
    open set is a disposable scratch set (has a track named __TOOLING_SCRATCH__), and the command list."""
    return out(call("info"))


@mcp.tool()
@guarded
def list_tracks(devices: bool = True) -> str:
    """Every track, return and the master: ref, name, kind, volume (dB as displayed), pan, mute, solo, input/output
    routing, monitoring, sends (dB) and device names."""
    return out(call("list_tracks", devices=devices))


@mcp.tool()
@guarded
def create_track(kind: str = "audio", index: int = -1, name: Optional[str] = None) -> str:
    """Create an 'audio' or 'midi' track at index (-1 = end) and optionally name it."""
    return out(call("create_track", kind=kind, index=index, name=name))


@mcp.tool()
@guarded
def rename_track(track: Ref, name: str) -> str:
    """Rename a track or return (returns keep Live's letter prefix, e.g. 'C-Plate')."""
    return out(call("rename_track", track=track, name=name))


@mcp.tool()
@guarded
def delete_track(track: Ref) -> str:
    """Delete a track or return. Refused unless the open set is a scratch set (a track named __TOOLING_SCRATCH__)."""
    return out(call("delete_track", track=track))


# ------------------------------------------------------------------ returns (priority 1)
@mcp.tool()
@guarded
def list_return_tracks() -> str:
    """Returns (song.return_tracks): letter, name, volume dB, mute/solo, output routing, devices, and which tracks
    send to each one and how much. Reuse A-Reverb and B-Delay where they fit rather than adding duplicates."""
    return out(call("list_return_tracks"))


@mcp.tool()
@guarded
def create_return_track(name: Optional[str] = None) -> str:
    """Add a return track at the end (song.create_return_track) and optionally name it."""
    return out(call("create_return_track", name=name))


@mcp.tool()
@guarded
def rename_return_track(ret: str, name: str) -> str:
    """Rename a return. ret: 'A', 'return:A', 'return:0' or its current name."""
    return out(call("rename_track", track=ret if ret.lower().startswith("return:") else "return:" + ret, name=name))


@mcp.tool()
@guarded
def get_return_track_devices(ret: str, params: bool = False) -> str:
    """The device chain on a return (rack chains included); params=True adds every parameter with raw and display values."""
    return out(call("get_track_devices", track=_ret(ret), params=params))


def _ret(ret: str) -> str:
    return ret if str(ret).lower().startswith("return:") else "return:" + str(ret)


def _load(track: Ref, effect: str, position: Optional[int]) -> dict:
    """Native device by exact name via Track.insert_device; anything else ('query:...' URI) via the browser, verified."""
    if not effect.startswith(("query:", "userlibrary:", "packs:")) and ":" not in effect:
        return call("insert_native_device", track=track, name=effect, index=-1 if position is None else position)
    started = call("load_browser_item", track=track, uri=effect)
    for _ in range(40):
        time.sleep(0.25)
        v = call("verify_load", track=track, before=started["before"], position=position)
        if v.get("ok"):
            return v
    raise LiveError("load of %s did not land on %s alone: %s" % (effect, track, v))


@mcp.tool()
@guarded
def load_effect_on_return_track(ret: str, effect: str, position: Optional[int] = None) -> str:
    """Load an effect onto a return track. effect: a native Live device's exact name ('Echo', 'Hybrid Reverb',
    'EQ Eight', 'Glue Compressor') or a browser URI ('query:Plugins#VST3:MeldaProduction:MCompressor').
    position: chain index (None = end). Verified: only that return gains exactly one device."""
    return out(_load(_ret(ret), effect, position))


@mcp.tool()
@guarded
def get_return_device_parameters(ret: str, device: Ref) -> str:
    """Parameters of a device on a return: index, name, raw value, min, max, display string, display_value
    (Hz for frequencies, ms for times), quantized items."""
    return out(call("get_device_parameters", track=_ret(ret), device=device))


@mcp.tool()
@guarded
def set_return_device_parameter(ret: str, device: Ref, parameter: Ref, value: Union[float, str], units: str = "auto") -> str:
    """Set a device parameter on a return. units: 'display' (the number as Live shows it: dB, Hz, ms, %),
    'raw' (internal min..max), 'auto' (strings like '800 Hz', '-6 dB', '35 %' or a quantized item name are display
    values; plain numbers are raw). Returns before/after read-back."""
    return out(call("set_device_parameter", track=_ret(ret), device=device, parameter=parameter, value=value, units=units))


@mcp.tool()
@guarded
def set_return_volume(ret: str, db: Union[float, str]) -> str:
    """A return's fader in dB as displayed ('-inf' for off)."""
    return out(call("set_mixer", track=_ret(ret), volume_db=db))


@mcp.tool()
@guarded
def inspect_return_routing(ret: str) -> str:
    """A return's output routing, its available output choices, its own sends, and the tracks feeding it."""
    r = call("get_routing", track=_ret(ret))
    r["fed_by"] = next(x["fed_by"] for x in call("list_return_tracks") if x["ref"] == r["ref"])
    r["sends"] = call("get_track_sends", track=r["ref"])["sends"]
    return out(r)


@mcp.tool()
@guarded
def get_track_sends(track: Ref) -> str:
    """Every send on a track: letter, the return it feeds, raw value, display string and dB."""
    return out(call("get_track_sends", track=track))


@mcp.tool()
@guarded
def set_track_send(track: Ref, send: str, db: Optional[Union[float, str]] = None, value: Optional[float] = None) -> str:
    """Set a send. send: return letter ('A'), index, or return name. db: dB as Live displays it (-inf/None = off);
    or value: raw knob 0..1 (only when you know why). The reply carries the read-back display and dB.
    Note: the raw knob value is not dB and not linear gain; see docs/UNITS.md for the measured curve."""
    return out(call("set_track_send", track=track, send=send, db=db, value=value))


@mcp.tool()
@guarded
def send_curve(track: Ref, send: str = "A", points: int = 21) -> str:
    """Live's own raw-value -> display mapping of a send knob (for audits and docs)."""
    return out(call("send_curve", track=track, send=send, points=points))


# ------------------------------------------------------------------ mixer
@mcp.tool()
@guarded
def set_mixer(track: Ref, volume_db: Optional[Union[float, str]] = None, pan: Optional[float] = None,
              mute: Optional[bool] = None, solo: Optional[bool] = None) -> str:
    """Fader in dB as displayed ('-inf' allowed), pan -50 (50L) .. 50 (50R), mute, solo. Works on tracks, returns
    and (volume, pan) the master. Returns the read-back."""
    return out(call("set_mixer", track=track, volume_db=volume_db, pan=pan, mute=mute, solo=solo))


# ------------------------------------------------------------------ devices (priority 4)
@mcp.tool()
@guarded
def get_track_devices(track: Ref, params: bool = False) -> str:
    """A track's full device chain: index, name, class, type, on/off, plugin flag, rack chains (3 levels deep);
    params=True adds every parameter."""
    return out(call("get_track_devices", track=track, params=params))


@mcp.tool()
@guarded
def load_effect(track: Ref, effect: str, position: Optional[int] = None) -> str:
    """Load an effect on any track (returns included) at a chain position. effect: native device name or browser
    URI. Verified: only that track gains exactly one device."""
    return out(_load(track, effect, position))


@mcp.tool()
@guarded
def get_device_parameters(track: Ref, device: Ref, chain: Optional[str] = None, chain_device: Optional[int] = None) -> str:
    """Parameters of a device; chain='0' with chain_device=N reaches device N inside rack chain 0."""
    return out(call("get_device_parameters", track=track, device=device, chain=chain, chain_device=chain_device))


@mcp.tool()
@guarded
def set_device_parameter(track: Ref, device: Ref, parameter: Ref, value: Union[float, str], units: str = "auto",
                         chain: Optional[str] = None, chain_device: Optional[int] = None) -> str:
    """Set one parameter by verified name or index. units as in set_return_device_parameter. Returns before/after."""
    return out(call("set_device_parameter", track=track, device=device, parameter=parameter, value=value, units=units,
                    chain=chain, chain_device=chain_device))


@mcp.tool()
@guarded
def set_device_parameters(track: Ref, device: Ref, values: dict, units: str = "auto",
                          chain: Optional[str] = None, chain_device: Optional[int] = None) -> str:
    """Set several parameters {name: value}; every name is checked before anything is written.
    chain ('c' or 'c/d/c') and chain_device reach a device inside a rack (WavReadBridge 0.1.1+)."""
    extra = {} if chain in (None, "") else {"chain": chain, "chain_device": chain_device}
    return out(call("set_device_parameters", track=track, device=device, values=values, units=units, **extra))


@mcp.tool()
@guarded
def set_device_on(track: Ref, device: Ref, on: bool = True) -> str:
    """Bypass (on=False) or enable a device through its Device On parameter."""
    return out(call("set_device_on", track=track, device=device, on=on))


@mcp.tool()
@guarded
def move_device(track: Ref, device: Ref, to_position: int, to_track: Optional[Ref] = None) -> str:
    """Reorder a device in its chain, or move it to another track (Song.move_device)."""
    return out(call("move_device", track=track, device=device, to_position=to_position, to_track=to_track))


@mcp.tool()
@guarded
def delete_device(track: Ref, device: Ref) -> str:
    """Delete a device. Refused unless the open set is a scratch set."""
    return out(call("delete_device", track=track, device=device))


@mcp.tool()
@guarded
def snapshot_device(track: Ref, device: Ref, save_to: Optional[str] = None) -> str:
    """Every parameter's raw value and display string; save_to writes the snapshot as JSON to that path."""
    s = call("snapshot_device", track=track, device=device)
    if save_to:
        with open(os.path.expanduser(save_to), "w") as f:
            json.dump(s, f, indent=1)
        s["saved_to"] = save_to
    return out(s)


@mcp.tool()
@guarded
def restore_device_snapshot(track: Ref, device: Ref, snapshot_path: str) -> str:
    """Write a saved snapshot back (by index, only where names still match) and report what still differs."""
    with open(os.path.expanduser(snapshot_path)) as f:
        snap = json.load(f)
    return out(call("restore_device_snapshot", track=track, device=device, snapshot=snap))


# ------------------------------------------------------------------ routing and buses (priority 2)
@mcp.tool()
@guarded
def get_routing(track: Ref) -> str:
    """A track's input/output type and channel, monitoring, and the choices Live offers right now."""
    return out(call("get_routing", track=track))


@mcp.tool()
@guarded
def set_routing(track: Ref, direction: str, target: Ref, channel: Optional[str] = None) -> str:
    """Set 'output' or 'input' routing. target: a choice Live offers ('Main', 'No Output', 'Sends Only', 'Ext. In',
    'No Input') or a track ref, matched by the routing type's attached track. Reports every track whose routing
    changed (it should be only this one)."""
    return out(retry("set_routing", track=track, direction=direction, target=target, channel=channel))


@mcp.tool()
@guarded
def set_monitoring(track: Ref, state: str) -> str:
    """Monitoring: 'in', 'auto' or 'off'."""
    return out(call("set_monitoring", track=track, state=state))


@mcp.tool()
@guarded
def get_routing_graph() -> str:
    """Every track's routing, monitoring, mixer state and active sends, with problems found: feedback loops, double
    routing to Main, silent buses (monitoring off, No Output, muted, -inf), soloed buses."""
    return out(call("get_routing_graph"))


@mcp.tool()
@guarded
def validate_routing() -> str:
    """Only the problems from get_routing_graph (empty list = clean)."""
    return out(call("get_routing_graph")["problems"])


def _bus_setup(bus_ref: str, monitoring: str) -> dict:
    steps = {"input": retry("set_routing", track=bus_ref, direction="input", target="No Input"),
             "monitoring": call("set_monitoring", track=bus_ref, state=monitoring),
             "output": retry("set_routing", track=bus_ref, direction="output", target="Main")}
    return steps


@mcp.tool()
@guarded
def create_audio_bus(name: str, sources: Optional[list] = None, volume_db: Optional[float] = 0.0, index: int = -1,
                     monitoring: str = "in") -> str:
    """A real audio submix bus (not a return, not a native Group Track): a new audio track with Input 'No Input',
    Monitor 'In' and Output 'Main'; each source's output is then routed into it (matched by attached track).
    Checks the routing graph afterwards and refuses to leave a loop. sources: track refs."""
    t = call("create_track", kind="audio", index=index, name=name)
    bus = t["ref"]
    res = {"bus": bus, "name": name, "setup": _bus_setup(bus, monitoring)}
    if volume_db is not None:
        res["volume"] = call("set_mixer", track=bus, volume_db=volume_db)["now"]
    res["routed"] = [_route(src, bus) for src in (sources or [])]
    res["problems"] = call("get_routing_graph")["problems"]
    return out(res)


def _route(src: Ref, bus: Ref) -> dict:
    before = call("get_routing", track=src, options=False)
    r = retry("set_routing", track=src, direction="output", target=bus)
    loops = [p for p in call("get_routing_graph")["problems"] if p["problem"] == "feedback loop"]
    if loops:
        call("set_routing", track=src, direction="output", target=before["output"]["type"])
        raise LiveError("routing %s -> %s made a feedback loop %s; reverted to %s" % (src, bus, loops, before["output"]))
    if r["changed_tracks"] != [r["ref"]]:
        r["warning"] = "other tracks changed: %s" % r["changed_tracks"]
    return {"source": r["ref"], "was": before.get("output"), "now": r["now"].get("output")}


@mcp.tool()
@guarded
def route_track_to_bus(track: Ref, bus: Ref) -> str:
    """Route one track's output into a bus track (reverts and errors if that would make a feedback loop)."""
    return out(_route(track, bus))


@mcp.tool()
@guarded
def route_multiple_tracks(tracks: list, bus: Ref) -> str:
    """Route several tracks' outputs into one bus; then the routing problems."""
    return out({"routed": [_route(t, bus) for t in tracks], "problems": call("get_routing_graph")["problems"]})


@mcp.tool()
@guarded
def set_bus_volume(bus: Ref, db: Union[float, str]) -> str:
    """A bus's fader in dB as displayed."""
    return out(call("set_mixer", track=bus, volume_db=db))


@mcp.tool()
@guarded
def set_bus_effect_chain(bus: Ref, chain: list, replace: bool = False) -> str:
    """Load a chain onto a bus (or any track, returns included). chain: [{"effect": "Glue Compressor",
    "params": {"Threshold": "-18 dB"}, "units": "auto"}, "Saturator", ...] in order. replace=True first deletes the
    track's existing devices (scratch sets only). Each effect is verified loaded, each parameter read back."""
    res = []
    if replace:
        for _ in call("get_track_devices", track=bus)["devices"]:
            call("delete_device", track=bus, device=0)
    for item in chain:
        item = {"effect": item} if isinstance(item, str) else item
        loaded = _load(bus, item["effect"], None)
        dev = len(call("get_track_devices", track=bus)["devices"]) - 1
        r = {"effect": item["effect"], "loaded": loaded}
        if item.get("params"):
            r["params"] = call("set_device_parameters", track=bus, device=dev, values=item["params"], units=item.get("units", "auto"))
        res.append(r)
    return out({"bus": bus, "chain": res, "devices": call("get_track_devices", track=bus)["devices"]})


# ------------------------------------------------------------------ meters and test material
@mcp.tool()
@guarded
def measure_levels(tracks: Optional[list] = None, seconds: float = 4.0, interval: float = 0.1) -> str:
    """Poll output meters while Live plays and report each track's peak dBFS over the window (meter dBFS =
    76 * raw - 70, verified in docs/UNITS.md; None = below -70 dBFS, i.e. silent). Use it as the audible check after
    a routing or effect change: a return that should be wet must read above -70."""
    peaks, n, playing = {}, 0, False
    t0 = time.time()
    while time.time() - t0 < seconds:
        m = call("get_meters", tracks=tracks)
        playing = playing or m["playing"]
        for ref, v in m["meters"].items():
            d = v.get("dbfs")
            if d is not None and (peaks.get(ref) is None or d > peaks[ref]):
                peaks[ref] = d
            peaks.setdefault(ref, None)
        n += 1
        time.sleep(interval)
    return out({"playing": playing, "samples": n, "peak_dbfs": peaks})


@mcp.tool()
@guarded
def transport(action: str, time_beats: Optional[float] = None) -> str:
    """'play' (from time_beats if given), 'continue', 'stop', 'stop_all_clips'."""
    return out(call("transport", action=action, time_beats=time_beats))


@mcp.tool()
@guarded
def make_test_clip(track: Ref, slot: int = 0, length: float = 4.0, notes: Optional[list] = None,
                   name: Optional[str] = None, fire: bool = False) -> str:
    """A looping session MIDI clip for tests: notes [[pitch, start_beats, length_beats, velocity], ...]."""
    return out(call("make_test_clip", track=track, slot=slot, length=length, notes=notes, name=name, fire=fire))


@mcp.tool()
@guarded
def fire_clip(track: Ref, slot: int = 0) -> str:
    """Launch a session clip slot."""
    return out(call("fire_clip", track=track, slot=slot))


# ============================================================================================ Phase 2 (ext.py)
# Positions are musical: beats (numbers) or "bar.beat.sixteenth" strings, 1-based ("7.1.1" = start of bar 7).
# Automation targets: {"mixer": "volume"|"pan"|"send", "send": "A"} or
# {"device": <ref>, "parameter": <name>, "chain": "c/d/c", "chain_device": n} (chain only inside racks).

@mcp.tool()
@guarded
def reload_extensions() -> str:
    """Re-import WavReadBridge's ext.py (Phase 2 commands) after tools/install_remote_script.sh --ext. No Live restart."""
    return out(call("reload_extensions"))


@mcp.tool()
@guarded
def probe(path: str = "song", values: bool = True) -> str:
    """Capability detection: the attributes Live exposes on one LOM object. path: 'song', 'song.view', 'app',
    'track:N' / 'return:A' / 'master' / a name, then steps 'clip:S', 'aclip:I', 'slot:S', 'device:D', 'chain:C',
    'param:P', 'mixer', e.g. 'track:3/device:0/param:Frequency'. Read-only."""
    return out(call("probe", path=path, values=values))


@mcp.tool()
@guarded
def list_automatable_parameters(track: Ref, slot: Optional[int] = None) -> str:
    """Every parameter a session clip on this track can automate (mixer, devices, rack chains), each with the
    target object to pass to the automation tools. With slot, marks which already have an envelope."""
    return out(call("list_automatable_parameters", track=track, slot=slot))


@mcp.tool()
@guarded
def set_automation_points(track: Ref, slot: int, target: dict, points: list, units: str = "auto",
                          mode: str = "ramp", replace: bool = True) -> str:
    """Write breakpoints into a SESSION clip's envelope (created if needed). points: [{"at": "1.1.1", "value": v}];
    mode "ramp" (lines between points) or "step" (hold until the next). Two points at one time make a jump.
    units: raw, or display ("200 Hz", "-6 dB", "35 %"). Reads every point back. Tested: 8-bar cutoff/send/volume."""
    return out(call("set_automation_points", track=track, slot=slot, target=target, points=points, units=units,
                    mode=mode, replace=replace))


@mcp.tool()
@guarded
def set_automation_curve(track: Ref, slot: int, target: dict, shape: str, start: Union[str, float],
                         end: Union[str, float], frm: Union[str, float], to: Optional[Union[str, float]] = None,
                         units: str = "auto", curve: str = "linear", resolution: float = 0.25, rate: float = 1.0,
                         duty: float = 0.5, replace: bool = True) -> str:
    """A shaped segment in a session clip: shape ramp/sweep/fade (frm -> to; curve linear, ease, exp, log), hold,
    pulse (to for `duty` of every `rate` beats, else frm), sine (frm..to, period `rate` beats). Display values
    interpolate in display units (a dB fade is linear in dB)."""
    return out(call("set_automation_curve", track=track, slot=slot, target=target, shape=shape, start=start, end=end,
                    frm=frm, to=to, units=units, curve=curve, resolution=resolution, rate=rate, duty=duty,
                    replace=replace))


@mcp.tool()
@guarded
def get_automation(track: Ref, slot: int, target: dict, start: Union[str, float] = 0, end=None, step: float = 1.0) -> str:
    """Sample a session clip's envelope every `step` beats."""
    return out(call("get_automation", track=track, slot=slot, target=target, start=start, end=end, step=step))


@mcp.tool()
@guarded
def delete_automation(track: Ref, slot: int, target: Optional[dict] = None) -> str:
    """Clear one envelope in a session clip, or all of them when target is omitted."""
    return out(call("delete_automation", track=track, slot=slot, target=target))


@mcp.tool()
@guarded
def copy_automation(track: Ref, slot: int, target: dict, to_track: Ref, to_slot: int,
                    to_target: Optional[dict] = None, resolution: float = 0.0625) -> str:
    """Copy an envelope to another session clip/parameter by sampling every `resolution` beats."""
    return out(call("copy_automation", track=track, slot=slot, target=target, to_track=to_track, to_slot=to_slot,
                    to_target=to_target, resolution=resolution))


@mcp.tool()
@guarded
def validate_automation(track: Ref, slot: int, target: dict, expect: list, units: str = "auto",
                        tolerance: Optional[float] = None) -> str:
    """Check expected values [{"at": pos, "value": v}] and the loop wrap (value at loop end vs loop start)."""
    return out(call("validate_automation", track=track, slot=slot, target=target, expect=expect, units=units,
                    tolerance=tolerance))


@mcp.tool()
@guarded
def record_arrangement_automation(track: Ref, target: dict, points: list, units: str = "auto",
                                  preroll_bars: int = 1, wait: bool = True) -> str:
    """ARRANGEMENT automation (the LOM can't draw it): records it in real time. Stops session clips, presses Back
    to Arrangement, selects the Main (so no MIDI track is implicitly armed), refuses if any track is armed, plays
    from a bar before the first point and writes the parameter every tick. Straight lines between points (song
    time). Takes as long as the passage plays. Tested: 8-bar Vital cutoff, survives save and reopen."""
    r = call("record_arrangement_automation", track=track, target=target, points=points, units=units,
             preroll_bars=preroll_bars)
    if not wait:
        return out(r)
    deadline = time.time() + float(r.get("seconds", 60)) + 20
    st = None
    while time.time() < deadline:
        time.sleep(1.0)
        st = call("record_arrangement_status")
        if st.get("done"):
            break
    return out({"started": r, "status": st, "state": call("param_state", track=track, target=target)})


@mcp.tool()
@guarded
def param_state(track: Ref, target: dict) -> str:
    """A parameter's value and automation state (0 none, 1 playing, 2 overridden)."""
    return out(call("param_state", track=track, target=target))


@mcp.tool()
@guarded
def re_enable_automation(track: Optional[Ref] = None, target: Optional[dict] = None) -> str:
    """Re-enable overridden automation for one parameter, or the whole song."""
    return out(call("re_enable_automation", track=track, target=target))


@mcp.tool()
@guarded
def back_to_arrangement() -> str:
    """Press Back to Arrangement (tracks follow the Arrangement and its automation again)."""
    return out(call("back_to_arrangement"))


@mcp.tool()
@guarded
def capture(tracks: list, seconds: float = 8.0, params: Optional[list] = None) -> str:
    """Sample meters (dBFS) and optional parameters [{"track", "target"}] inside Live at ~10 Hz, stamped with song
    time, for `seconds` while Live plays. Returns the rows. Use it to prove automation or ducking by ear-equivalent."""
    call("capture_start", tracks=tracks, seconds=seconds, params=params)
    time.sleep(float(seconds) + 0.6)
    return out(call("capture_result"))


@mcp.tool()
@guarded
def inspect_device_sidechain(track: Ref, device: Ref, chain: Optional[str] = None,
                             chain_device: Optional[int] = None) -> str:
    """A device's sidechain: reachable through the LOM or not, its source, choices and S/C parameters. On 12.4
    Compressor exposes its source; others may have S/C parameters but no routing."""
    return out(call("inspect_device_sidechain", track=track, device=device, chain=chain, chain_device=chain_device))


@mcp.tool()
@guarded
def set_sidechain(track: Ref, device: Ref, source: Ref, channel: Optional[str] = None, on: bool = True,
                  params: Optional[dict] = None, chain: Optional[str] = None, chain_device: Optional[int] = None) -> str:
    """Key a device from another track (never its own), turn S/C on, set S/C or compressor parameters in display
    units, e.g. params={"Threshold": "-30 dB", "Ratio": "4", "Attack": "1 ms", "Release": "150 ms"}. Prove it with
    capture: ducking with the trigger, none without. Tested: 9.9 dB ducking on the beat."""
    return out(call("set_sidechain", track=track, device=device, source=source, channel=channel, on=on,
                    params=params, chain=chain, chain_device=chain_device))


@mcp.tool()
@guarded
def create_effect_rack(track: Ref, name: Optional[str] = None, index: int = -1, kind: str = "Audio Effect Rack") -> str:
    """Insert an empty rack (Audio Effect Rack, Instrument Rack, MIDI Effect Rack, Drum Rack). It starts with 0 chains."""
    return out(call("create_effect_rack", track=track, name=name, index=index, kind=kind))


@mcp.tool()
@guarded
def add_rack_chain(track: Ref, device: Ref, name: Optional[str] = None, index: int = -1) -> str:
    """Add a chain to a rack."""
    return out(call("add_rack_chain", track=track, device=device, name=name, index=index))


@mcp.tool()
@guarded
def insert_device_in_chain(track: Ref, device: Ref, chain_index: int, name: str, index: int = -1) -> str:
    """Insert a native device (exact browser name) into a rack chain."""
    return out(call("insert_device_in_chain", track=track, device=device, chain_index=chain_index, name=name, index=index))


@mcp.tool()
@guarded
def set_chain_mixer(track: Ref, device: Ref, chain_index: int, volume_db: Optional[float] = None,
                    pan: Optional[float] = None, active: Optional[bool] = None) -> str:
    """A rack chain's volume (dB), pan (-50..50) and on/off."""
    return out(call("set_chain_mixer", track=track, device=device, chain_index=chain_index, volume_db=volume_db,
                    pan=pan, active=active))


@mcp.tool()
@guarded
def set_rack_macros(track: Ref, device: Ref, visible: Optional[int] = None, values: Optional[dict] = None,
                    units: str = "auto") -> str:
    """Show `visible` macros and set macro values. Mapping a macro to a parameter is NOT possible through the LOM."""
    return out(call("set_rack_macros", track=track, device=device, visible=visible, values=values, units=units))


@mcp.tool()
@guarded
def get_clip(track: Ref, slot: Optional[int] = None, arrangement_index: Optional[int] = None) -> str:
    """A clip's markers, loop, and for audio: pitch, gain, warp mode, warp markers, file, sample rate."""
    return out(call("get_clip", track=track, slot=slot, arrangement_index=arrangement_index))


@mcp.tool()
@guarded
def set_clip(track: Ref, slot: Optional[int] = None, arrangement_index: Optional[int] = None,
             name: Optional[str] = None, pitch_coarse: Optional[int] = None, pitch_fine: Optional[float] = None,
             gain: Optional[float] = None, warping: Optional[bool] = None, warp_mode: Optional[int] = None,
             looping: Optional[bool] = None, loop_start=None, loop_end=None, start_marker=None, end_marker=None) -> str:
    """Clip properties; positions musical. warp_mode 0 beats, 1 tones, 2 texture, 3 re-pitch, 4 complex,
    6 complex pro. gain 0..1 (0.4 = 0 dB). Reverse and fades aren't in the LOM (reverse: tools/wav_reverse.py)."""
    return out(call("set_clip", track=track, slot=slot, arrangement_index=arrangement_index, name=name,
                    pitch_coarse=pitch_coarse, pitch_fine=pitch_fine, gain=gain, warping=warping,
                    warp_mode=warp_mode, looping=looping, loop_start=loop_start, loop_end=loop_end,
                    start_marker=start_marker, end_marker=end_marker))


@mcp.tool()
@guarded
def warp_marker(track: Ref, action: str, beat: Union[str, float], slot: Optional[int] = None,
                arrangement_index: Optional[int] = None, seconds: Optional[float] = None,
                delta: Optional[float] = None) -> str:
    """Add (beat + seconds), move (beat, delta beats) or remove (beat) a warp marker on an audio clip."""
    return out(call("warp_marker", track=track, action=action, beat=beat, slot=slot,
                    arrangement_index=arrangement_index, seconds=seconds, delta=delta))


@mcp.tool()
@guarded
def create_audio_clip(track: Ref, path: str, slot: Optional[int] = None, at=None) -> str:
    """Load an audio file (absolute path) into a session slot or the Arrangement at a position (audio tracks)."""
    return out(call("create_audio_clip", track=track, path=path, slot=slot, at=at))


@mcp.tool()
@guarded
def duplicate_to_arrangement(track: Ref, slot: int, at) -> str:
    """Copy a session clip into the Arrangement. On an instrument track its envelopes are dropped (measured)."""
    return out(call("duplicate_to_arrangement", track=track, slot=slot, at=at))


@mcp.tool()
@guarded
def record_track_audio(dst: Ref, source: Ref, slot: int = 0, bars: int = 2, channel: Optional[str] = None,
                       wait: bool = True) -> str:
    """Record (resample) a track's output, or "Resampling" for the Main, into a session slot of an audio track for
    exactly `bars` bars. Set the playhead first (set_song_time(position=...)) and DON'T press play: the launch
    starts the transport (a play call restarts it and cuts the recording). This is also the dialog-free render:
    record the Main, then run tools/audio_check.py on the file."""
    r = call("record_track_audio", dst=dst, source=source, slot=slot, bars=bars, channel=channel)
    if not wait:
        return out(r)
    st = None
    deadline = time.time() + 600
    while time.time() < deadline:
        time.sleep(1.0)
        st = call("record_track_audio_status")
        if st.get("done"):
            break
    call("transport", action="stop")
    return out(st)


@mcp.tool()
@guarded
def set_arm(track: Ref, arm: bool) -> str:
    """Arm or disarm a track; reports explicit and implicit (controller) arm."""
    return out(call("set_arm", track=track, arm=arm))


@mcp.tool()
@guarded
def set_song_time(tempo: Optional[float] = None, numerator: Optional[int] = None, denominator: Optional[int] = None,
                  loop: Optional[bool] = None, loop_start=None, loop_length=None, position=None) -> str:
    """Tempo, time signature, loop brace, and the playhead position (set it while stopped)."""
    return out(call("set_song_time", tempo=tempo, numerator=numerator, denominator=denominator, loop=loop,
                    loop_start=loop_start, loop_length=loop_length, position=position))


@mcp.tool()
@guarded
def list_arrangement_clips(track: Ref) -> str:
    """A track's Arrangement clips: index, name, start and end (beats), looping, audio."""
    return out(call("list_arrangement_clips", track=track))


@mcp.tool()
@guarded
def move_arrangement_clip(track: Ref, to, at=None, index: Optional[int] = None, to_track: Optional[Ref] = None) -> str:
    """Move an Arrangement clip (found by its start `at` or `index`) to a musical position, optionally on another
    track of the same kind. Done as verified copy + delete via a temporary spot. Proven by null test (-45 dB)."""
    return out(call("move_arrangement_clip", track=track, to=to, at=at, index=index, to_track=to_track))


@mcp.tool()
@guarded
def copy_arrangement_clip(track: Ref, to, at=None, index: Optional[int] = None, to_track: Optional[Ref] = None) -> str:
    """Copy an Arrangement clip to a musical position (pastes over whatever is there)."""
    return out(call("copy_arrangement_clip", track=track, to=to, at=at, index=index, to_track=to_track))


@mcp.tool()
@guarded
def trim_arrangement_clip(track: Ref, at=None, index: Optional[int] = None, start=None, end=None) -> str:
    """Trim an Arrangement clip to [start, end) in song time, content kept in place (clip unlooped). Live adds its
    short clip-edge fade at a new edge."""
    return out(call("trim_arrangement_clip", track=track, at=at, index=index, start=start, end=end))


@mcp.tool()
@guarded
def split_arrangement_clip(track: Ref, split_at, at=None, index: Optional[int] = None) -> str:
    """Split an Arrangement clip at a song position into two clips that play exactly as before (null -215 dB)."""
    return out(call("split_arrangement_clip", track=track, split_at=split_at, at=at, index=index))


@mcp.tool()
@guarded
def create_arrangement_midi_clip(track: Ref, at, length, notes: Optional[list] = None, name: Optional[str] = None) -> str:
    """A MIDI clip directly in the Arrangement; notes [[pitch, start, length, velocity]] in clip beats."""
    return out(call("create_arrangement_midi_clip", track=track, at=at, length=length, notes=notes, name=name))


# ============================================================================================ write permission
@mcp.tool()
@guarded
def get_set_identity() -> str:
    """The open Live Set's identity: file_path, name, and a set_id stored inside the Set. Read-only tools work on any
    Set; tools that change a Set need it saved (untitled Sets are refused)."""
    return out(call("get_set_identity"))


@mcp.tool()
@guarded
def write_status() -> str:
    """writes_allowed (the one to check: true for any saved Set), whether it's a disposable Set (deletes run only
    there), and the open Set's identity. Suggest a backup of important Sets before editing them."""
    return out(call("write_status"))


def main():
    mcp.run()


if __name__ == "__main__":
    main()
