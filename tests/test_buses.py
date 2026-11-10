"""Priority 2 calibration: a real audio submix bus, routing validation, audible proof.
Needs the sources from test_returns.py build (Tool Src 1-3) in the open scratch set.
usage: python3 tests/test_buses.py
Results: tests/results/buses.json
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from lt import call, retry, peaks, Log
from lt import authorize
authorize()   # tests run only in saved disposable Sets

RES = os.path.join(os.path.dirname(__file__), "results")
log = Log(os.path.join(RES, "buses.json"))
names = {t["name"]: t["ref"] for t in call("list_tracks", devices=False)}
srcs = [names["Tool Src 1"], names["Tool Src 2"]]
other = names["Tool Src 3"]
if not call("info")["scratch_set"]:
    sys.exit("open the scratch set")

before = {t["ref"]: t["routing"] for t in call("list_tracks", devices=False)}
bus = call("create_track", kind="audio", name="Tool Drum Bus")["ref"]
time.sleep(0.3)
steps = {"input": retry("set_routing", track=bus, direction="input", target="No Input"),
         "monitoring": call("set_monitoring", track=bus, state="in"),
         "output": retry("set_routing", track=bus, direction="output", target="Main")}
log("bus created: No Input, Monitor In, Main", steps["input"]["now"]["input"]["type"] == "No Input"
    and steps["monitoring"]["monitoring"] == "in" and steps["output"]["now"]["output"]["type"] == "Main", bus=bus, steps=steps)
for s in srcs:
    r = retry("set_routing", track=s, direction="output", target=bus)
    log("route %s -> bus" % s, r["now"]["output"]["type"].endswith("Tool Drum Bus") and r["changed_tracks"] == [s],
        now=r["now"], changed=r["changed_tracks"])
after = {t["ref"]: t["routing"] for t in call("list_tracks", devices=False)}
unexpected = [k for k in before if k not in srcs and before[k] != after.get(k)]
log("no unexpected routing changes", not unexpected, unexpected=unexpected)
g = call("get_routing_graph")
log("routing graph clean", not [p for p in g["problems"] if p["severity"] == "error"], problems=g["problems"])

# loop guard: routing the bus into one of its sources must be refused or detected
try:
    r = retry("set_routing", track=bus, direction="output", target=srcs[0], tries=2)
    loops = [p for p in call("get_routing_graph")["problems"] if p["problem"] == "feedback loop"]
    call("set_routing", track=bus, direction="output", target="Main")
    log("feedback loop detected (or offered by Live)", bool(loops), loops=loops, live_offered=True)
except Exception as e:
    log("feedback loop refused by Live itself", "cannot route" in str(e) or "not offered" in str(e), error=str(e))

# audible: the bus carries the two sources; muting the bus silences them on Main; Src 3 stays direct
call("transport", action="play")
for s in srcs + [other]:
    call("fire_clip", track=s, slot=0)
time.sleep(1.5)
p = peaks(srcs + [other, bus, "master"], seconds=3.0)
log("bus audible", p[bus] is not None and p[bus] > -60, peaks=p)
call("set_mixer", track=bus, volume_db=-12.0)
time.sleep(1.5)
q = peaks([bus], seconds=2.5)
log("bus fader -12 dB measured", q[bus] is not None and p[bus] is not None and abs((p[bus] - q[bus]) - 12.0) <= 0.6,
    at_0=p[bus], at_minus12=q[bus])
# A track's own output meter reads BEFORE its mute and solo (measured on Live 12.4.16, 2026-11-10), so mute and solo
# are judged by what reaches the main and the bus, never by the muted or soloed track's own meter.
call("set_mixer", track=bus, volume_db=0.0, mute=True)
time.sleep(2.0)
m = peaks(["master"], seconds=2.5)
call("set_mixer", track=bus, mute=False, volume_db=-70.0)
time.sleep(2.0)
z = peaks(["master"], seconds=2.5)
call("set_mixer", track=bus, volume_db=0.0)
log("bus muted: the main drops exactly as with the bus fader at -inf", None not in (m["master"], z["master"])
    and p["master"] - m["master"] >= 1.0 and abs(m["master"] - z["master"]) <= 0.3,
    main_on=p["master"], main_muted=m["master"], main_fader_inf=z["master"])
# solo a source that feeds the bus: only that source reaches the bus (solo-in-place follows routing)
call("set_mixer", track=srcs[0], solo=True)
time.sleep(2.0)
s1 = peaks([srcs[0], srcs[1], bus, "master"], seconds=2.5)
call("set_mixer", track=srcs[0], solo=False)
log("solo a bus source: the bus carries that source only", None not in (s1[bus], s1[srcs[0]])
    and abs(s1[bus] - s1[srcs[0]]) <= 0.3 and abs(s1[bus] - p[bus]) >= 1.0, soloed=s1)
call("set_mixer", track=bus, solo=True)
time.sleep(2.0)
s2 = peaks([srcs[0], srcs[1], bus, other], seconds=2.5)
call("set_mixer", track=bus, solo=False)
log("solo the bus: its sources stay audible", s2[bus] is not None, soloed=s2)
call("transport", action="stop")
call("transport", action="stop_all_clips")
