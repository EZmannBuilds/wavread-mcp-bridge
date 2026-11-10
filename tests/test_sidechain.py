"""Phase C: sidechain compression, proven by ear-equivalent measurement (the owner's Phase 2, section 4).
"Tool Kick" (Operator, a short C1 every beat) keys a Compressor on "Tool SC Bass" (Operator, sustained C1+C2).
Proof, not read-back: the bass level is captured inside Live at ~10 Hz and must
  1. dip with the kick playing and the sidechain on (depth > 4 dB, dips on the beat);
  2. not dip with the kick stopped (no trigger: its depth is the bass's own movement, and ducking must exceed it by
     4 dB; measured 2026-11-10: 9.5 dB ducking against 2.3 dB of uncompressed movement);
  3. stay flat with the kick playing but S/C off (depth < 1.5 dB);
and the kick must still reach the Main by its own path (no double routing; validate_routing clean).
usage: python3 tests/test_sidechain.py
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from lt import call, Log
from lt import authorize
authorize()   # tests run only in saved disposable Sets

RES = os.path.join(os.path.dirname(__file__), "results")
log = Log(os.path.join(RES, "sidechain.json"))
names = {t["name"]: t["ref"] for t in call("list_tracks", devices=False)}
KICK, BASS = names["Tool Kick"], names["Tool SC Bass"]

# a refused self-source first
try:
    call("set_sidechain", track=BASS, device="Compressor", source=BASS)
    log("a compressor can't key from its own track", False)
except Exception as e:
    log("a compressor can't key from its own track", "own track" in str(e), error=str(e))

r = call("set_sidechain", track=BASS, device="Compressor", source="Tool Kick", on=True,
         params={"Threshold": "-30 dB", "Ratio": "8", "Attack": "1 ms", "Release": "150 ms"})
log("sidechain set and read back", r["source"]["name"] == "Tool Kick" and r["sc_on"][0]["value"] == r["sc_on"][0]["max"],
    result=r)
log("compressor settings read back", all(x["after"]["display"] for x in r["params"]),
    params=[(x["parameter"], x["after"]["display"]) for x in r["params"]])
# isolate the compressor: anything after it on the track (the 808 rack test's Saturator) flattens the dips
for d in call("get_track_devices", track=BASS)["devices"]:
    if d["name"] not in ("Operator", "Compressor"):
        call("set_device_on", track=BASS, device=d["index"], on=False)
call("set_device_on", track=BASS, device="Compressor", on=True)
call("set_mixer", track=BASS, volume_db=-6.0)
call("set_mixer", track=KICK, volume_db=-6.0)
call("set_song_time", tempo=60, loop=False)


def depth(label, kick_on, sc_on):
    call("transport", action="stop")
    call("transport", action="stop_all_clips")
    call("set_sidechain", track=BASS, device="Compressor", source="Tool Kick", on=sc_on)
    time.sleep(0.5)
    call("fire_clip", track=BASS, slot=0)
    if kick_on:
        call("fire_clip", track=KICK, slot=0)
    call("transport", action="play", time_beats=0)
    call("capture_start", tracks=[BASS, KICK], seconds=7.0)
    time.sleep(7.5)
    rows = [x for x in call("capture_result")["rows"] if x["t"] >= 2.0 and x[BASS] is not None]
    call("transport", action="stop")
    call("transport", action="stop_all_clips")
    vals = [x[BASS] for x in rows]
    d = round(max(vals) - min(vals), 2) if vals else None
    # where are the dips? beat phase of the lowest readings
    low = sorted(rows, key=lambda x: x[BASS])[:5]
    return d, [round(x["t"] % 1.0, 2) for x in low], round(max(vals), 2) if vals else None


d1, phase1, peak1 = depth("kick + sc", True, True)
log("bass ducks with the kick (sidechain on)", d1 is not None and d1 > 4.0, depth_db=d1, dip_beat_phase=phase1, peak=peak1)
d2, _, peak2 = depth("no kick", False, True)
log("no trigger: no ducking with the kick stopped (ducking exceeds this baseline by 4 dB)",
    d2 is not None and d1 - d2 > 4.0, depth_db=d2, ducking_db=d1, peak=peak2)
d3, _, peak3 = depth("sc off", True, False)
log("S/C off: bass stays level with the kick playing", d3 is not None and d3 < 1.5, depth_db=d3, peak=peak3)
call("set_sidechain", track=BASS, device="Compressor", source="Tool Kick", on=True)
g = call("get_routing_graph")
kick_out = [t for t in call("list_tracks", devices=False) if t["ref"] == KICK][0]["routing"]["output"]["type"]
log("kick still reaches the Main by its own path; routing clean", kick_out == "Main"
    and not [p for p in g["problems"] if p["severity"] == "error"], kick_output=kick_out, problems=g["problems"])
