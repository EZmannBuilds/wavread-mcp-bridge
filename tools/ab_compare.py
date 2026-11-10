#!/usr/bin/env python3
"""A/B a production choice in Live (the owner's Phase 2, section 10):
  1. preserve the current state of everything the alternatives touch,
  2. apply A, render, apply B, render (both by resampling the Main or one track, identical start and length),
  3. restore the original state (or keep A or B with --keep),
  4. measure both and write loudness-matched copies (tools/ab_analyze.py).
Measurements inform the choice; listening decides it.

usage: python3 tools/ab_compare.py SPEC.json [--keep A|B]
SPEC: {"name": "808 grit", "source": "Resampling" or a track ref/name, "bars": 4, "position": "1.1.1",
       "play": [{"track": "Tool SC Bass", "slot": 0}] (session clips to fire; omit to play the Arrangement),
       "A": [ {"cmd": "set_rack_macros", "params": {...}}, ... ], "B": [ ... ]}
Supported state-changing commands (each is read back before, so it can be restored): set_device_parameter,
set_device_parameters, set_rack_macros (values), set_mixer, set_track_send, set_device_on, set_chain_mixer.
Renders land on the audio track "Tool AB Render" (created if missing) in the open set's project folder.
"""
import json, os, subprocess, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))
from lt import call, LiveError, authorize

spec = json.load(open(sys.argv[1]))
keep = sys.argv[sys.argv.index("--keep") + 1] if "--keep" in sys.argv else None
if not call("info")["scratch_set"]:
    sys.exit("refused: A/B runs only in a set with the __TOOLING_SCRATCH__ marker (never in a production set)")
authorize()


def params_of(p):
    return {k: v for k, v in p.items() if k not in ("values", "parameter", "value", "units", "volume_db", "pan",
                                                     "mute", "solo", "db", "on", "active")}


def capture_state(step):
    """What to re-apply to undo this step."""
    c, p = step["cmd"], step["params"]
    loc = params_of(p)
    if c in ("set_device_parameter", "set_device_parameters", "set_rack_macros"):
        names = [p["parameter"]] if c == "set_device_parameter" else list(p.get("values", {}).keys())
        dev = {k: loc[k] for k in ("track", "device", "chain", "chain_device") if k in loc}
        ps = {x["name"]: x["value"] for x in call("get_device_parameters", **dev)["parameters"]}
        return {"cmd": "set_device_parameters", "params": dict(dev, values={n: ps[n] for n in names}, units="raw")}
    if c == "set_mixer":
        m = call("get_mixer", track=p["track"])
        return {"cmd": "set_mixer", "params": {"track": p["track"], "volume_db": m["volume_db"], "mute": m["mute"]}}
    if c == "set_track_send":
        s = [x for x in call("get_track_sends", track=p["track"])["sends"] if x["send"] == p["send"]][0]
        return {"cmd": "set_track_send", "params": {"track": p["track"], "send": p["send"], "value": s["value"]}}
    if c == "set_device_on":
        d = [x for x in call("get_track_devices", track=p["track"])["devices"]
             if x["name"] == p["device"] or x["index"] == p["device"]][0]
        return {"cmd": "set_device_on", "params": {"track": p["track"], "device": p["device"], "on": d["on"]}}
    if c == "set_chain_mixer":
        return None   # chain state isn't read back here; list it explicitly in both A and B
    raise SystemExit("unsupported step for A/B (no restore known): %s" % c)


def apply(steps):
    for s in steps:
        call(s["cmd"], **s["params"])


def render(label):
    names = {t["name"]: t["ref"] for t in call("list_tracks", devices=False)}
    renders = sorted(n for n in names if n.startswith("Tool AB Render"))
    dst = names[renders[-1]] if renders else call("create_track", kind="audio", name="Tool AB Render")["ref"]
    # first empty slot
    slot = 0
    while True:
        try:
            call("get_clip", track=dst, slot=slot)
            slot += 1
        except LiveError:
            break
    call("transport", action="stop")
    call("transport", action="stop_all_clips")
    time.sleep(0.6)                       # stop_all_clips applies a tick later and would cancel new launches
    call("set_song_time", position=spec.get("position", "1.1.1"))
    if not spec.get("play"):
        call("back_to_arrangement")
    for c in spec.get("play", []):
        call("fire_clip", track=c["track"], slot=c["slot"])
    try:
        call("record_track_audio", dst=dst, source=spec.get("source", "Resampling"), slot=slot, bars=spec.get("bars", 4))
    except LiveError as e:
        if "out of range" not in str(e):
            raise
        # every slot on the render track is used: start a new render track
        dst = call("create_track", kind="audio", name="Tool AB Render %d" % int(time.time() % 100000))["ref"]
        slot = 0
        call("record_track_audio", dst=dst, source=spec.get("source", "Resampling"), slot=slot, bars=spec.get("bars", 4))
    st = None
    for _ in range(int(spec.get("bars", 4) * 8 + 60)):
        time.sleep(0.5)
        st = call("record_track_audio_status")
        if st["done"]:
            break
    call("transport", action="stop")
    call("transport", action="stop_all_clips")
    if not st or st.get("error") or not st.get("file"):
        raise SystemExit("render %s failed: %s" % (label, st))
    call("set_clip", track=dst, slot=slot, name="%s %s" % (spec.get("name", "AB"), label))
    return st["file"]


undo = [u for u in (capture_state(s) for s in spec["A"] + spec["B"]) if u]
files = {}
try:
    for label in ("A", "B"):
        apply(spec[label])
        time.sleep(0.3)
        files[label] = render(label)
finally:
    if keep in ("A", "B"):
        apply(spec[keep])
    else:
        apply(undo)
here = os.path.dirname(os.path.abspath(__file__))
an = subprocess.run(["/opt/homebrew/bin/uv", "run", "-q", "--with", "numpy", "--with", "soundfile", "--with", "pyloudnorm",
                     "--with", "scipy", "python", os.path.join(here, "ab_analyze.py"), files["A"], files["B"]],
                    capture_output=True, text=True)
print(json.dumps({"name": spec.get("name"), "renders": files, "kept": keep or "original restored",
                  "analysis": json.loads(an.stdout) if an.returncode == 0 else an.stderr[-800:]}, indent=1))
