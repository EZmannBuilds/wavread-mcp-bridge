"""Nested rack parameters (WavReadBridge 0.1.1+): reach a Sampler two racks deep, set a parameter in display units,
read it back. For example, a Sampler LFO destination.
Needs the open scratch set with "Dark Corner Pad.adg" (Core Library, Sampler/Pad, query:Synths#Sampler:Pad:FileId_4944)
on the track "Tool Plugin Bench MIDI". Measured layout on 2026-11-10: rack > chain 0 > device 1 (Instrument Rack) >
chain 0 > device 0 (MultiSampler), so the path is device=0, chain="0/1/0", chain_device=0.
usage: python3 tests/test_racks.py [--reopened]
Results: tests/results/racks[-reopened].json
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from lt import call, Log, LiveError
from lt import authorize
authorize()   # tests run only in saved disposable Sets

REOPENED = "--reopened" in sys.argv
RES = os.path.join(os.path.dirname(__file__), "results")
log = Log(os.path.join(RES, "racks-reopened.json" if REOPENED else "racks.json"))
info = call("info")
log("WavReadBridge 0.1.1+", info["version"] >= "0.1.1", version=info["version"])
names = {t["name"]: t["ref"] for t in call("list_tracks", devices=False)}
track = names["Tool Plugin Bench MIDI"]
PATH = dict(track=track, device=0, chain="0/1/0", chain_device=0)
ps = call("get_device_parameters", **PATH)
log("reach the Sampler two racks deep", ps["class_name"] == "MultiSampler", device=ps["device"], class_name=ps["class_name"])
by = {p["name"]: p for p in ps["parameters"]}
lfo = sorted(n for n in by if "LFO" in n)
log("Sampler LFO parameters listed", bool(lfo), lfo=lfo)
TARGET = ("LFO 1 Rate" if "LFO 1 Rate" in by else lfo[0]) if lfo else None
GOAL = by[TARGET]["min"] + (by[TARGET]["max"] - by[TARGET]["min"]) * 0.37 if TARGET else None
if not REOPENED:
    r = call("set_device_parameter", parameter=TARGET, value=GOAL, units="raw", **PATH)
    log("set %s (raw) and read back" % TARGET, abs(r["after"]["value"] - GOAL) < 1e-3,
        before=r["before"], after=r["after"])
    w = call("set_device_parameters", values={"Volume": "-9 dB"}, units="display", **PATH)
    log("batch write inside the rack (Volume -9 dB)", w["results"][0]["after"]["display"].startswith("-9"),
        result=w["results"][0])
else:
    log("%s survived save and reopen" % TARGET, abs(by[TARGET]["value"] - GOAL) < 1e-3,
        value=by[TARGET]["value"], display=by[TARGET]["display"])
    log("Volume survived save and reopen", by["Volume"]["display"].startswith("-9"), display=by["Volume"]["display"])
try:
    call("get_device_parameters", track=track, device=0, chain="0/9/0", chain_device=0)
    log("a bad path is an error, never a guess", False)
except LiveError as e:
    log("a bad path is an error, never a guess", "out of range" in str(e), error=str(e))
