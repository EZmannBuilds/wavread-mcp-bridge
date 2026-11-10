"""Priority 1 calibration: returns, sends in dB, return effects, audible proof (handoff section 4 steps 1-9).
Run with Live open on a DISPOSABLE set made by tests/make_scratch_set (it must hold a track named __TOOLING_SCRATCH__).
Phases: build (steps 1-6), verify (7-9). After `build`+`verify`, save the set (Cmd+S), close it, reopen it, and run
`verify --reopened` (step 10).
usage: python3 tests/test_returns.py build|verify [--reopened]
Results: tests/results/returns-<phase>.json
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from lt import call, peaks, Log
from lt import authorize
authorize()   # tests run only in saved disposable Sets

RES = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(RES, exist_ok=True)
SOURCES = [("Tool Src 1", 48), ("Tool Src 2", 55), ("Tool Src 3", 62)]
RET_NAME = "Tool Echo"
SENDS_DB = [-6.0, -12.0, -20.0]
# Echo settings in display units, set by verified names (names read from the device first, step 4)
ECHO = {"Dry Wet": 100.0, "Feedback": 30.0}


def ret_ref():
    for r in call("list_return_tracks"):
        if r["name"].endswith(RET_NAME):
            return r["ref"], r["letter"]
    return None, None


def src_refs():
    names = {t["name"]: t["ref"] for t in call("list_tracks", devices=False)}
    return [names[n] for n, _ in SOURCES]


def build():
    log = Log(os.path.join(RES, "returns-build.json"))
    info = call("info")
    if not log("scratch set open", info["scratch_set"], info=info):
        sys.exit("open a disposable scratch set first")
    # 1. three source tracks with audible material: Operator, a looping held note each
    for name, pitch in SOURCES:
        t = call("create_track", kind="midi", name=name)
        d = call("insert_native_device", track=t["ref"], name="Operator")
        call("make_test_clip", track=t["ref"], slot=0, length=4.0, notes=[[pitch, 0.0, 4.0, 100]], name="tone")
        log("1 source " + name, d["inserted"] == "Operator", track=t["ref"])
    # 2. a test return
    ref, letter = ret_ref()
    if ref is None:
        r = call("create_return_track", name=RET_NAME)
        ref = r["ref"]
        letter = ref.split(":")[1]
    log("2 test return", ref is not None, ref=ref)
    # 3. Echo directly onto the return
    if not any(d["name"] == "Echo" for d in call("get_track_devices", track=ref)["devices"]):
        ins = call("insert_native_device", track=ref, name="Echo")
        log("3 Echo on the return", ins["inserted"] == "Echo" and ins["track"] == ref, result=ins)
    # 4. the parameter list
    params = call("get_device_parameters", track=ref, device="Echo")["parameters"]
    names = [p["name"] for p in params]
    log("4 Echo parameters read", len(params) > 10, names=names)
    # 5. wet/dry, time, feedback, filter in validated units
    wanted = dict(ECHO)
    for cand in ("L 16th", "L Time", "L Division"):
        if cand in names:
            break
    filt = [n for n in names if "filter" in n.lower() or n.lower() in ("hp freq", "lp freq", "hp", "lp")]
    res = call("set_device_parameters", track=ref, device="Echo", values=wanted, units="display")
    ok = all(abs((r["after"].get("display_value") or 0) - float(wanted[r["parameter"]])) < 0.6 for r in res["results"])
    log("5 Echo wet/feedback by display units", ok, results=[(r["parameter"], r["after"]["display"]) for r in res["results"]],
        time_params=[n for n in names if "time" in n.lower() or "16th" in n.lower() or "sync" in n.lower()], filter_params=filt)
    # 6. sends in dB
    for sref, db in zip(src_refs(), SENDS_DB):
        r = call("set_track_send", track=sref, send=letter, db=db)
        log("6 send %s -> %s %.0f dB" % (sref, letter, db), r["db"] is not None and abs(r["db"] - db) < 0.05,
            display=r["after"]["display"], raw=r["after"]["value"], method=r["method"])
    # curve for the docs
    curve = call("send_curve", track=src_refs()[0], send=letter, points=41)
    log("6 send curve recorded", len(curve) == 41, curve=curve)


def verify(reopened=False):
    tag = "reopened" if reopened else "verify"
    log = Log(os.path.join(RES, "returns-%s.json" % tag))
    ref, letter = ret_ref()
    srcs = src_refs()
    # 7. sends through the API
    for sref, db in zip(srcs, SENDS_DB):
        s = [x for x in call("get_track_sends", track=sref)["sends"] if x["send"] == letter][0]
        log("7 send read-back %s" % sref, s["db"] is not None and abs(s["db"] - db) < 0.05, read=s)
    echo = {p["name"]: p for p in call("get_device_parameters", track=ref, device="Echo")["parameters"]}
    log("7 Echo settings read-back", all(abs(echo[k].get("display_value", 1e9) - v) < 0.6 for k, v in ECHO.items()),
        read={k: echo[k]["display"] for k in ECHO})
    # 8. audible: play, measure. First the dB mapping by ear-equivalent: Echo off so the return passes its input
    # straight through; each source alone; return peak - source peak should equal the send in dB.
    call("transport", action="play")
    for s in srcs:
        call("fire_clip", track=s, slot=0)
    time.sleep(1.5)
    call("set_device_on", track=ref, device="Echo", on=False)
    time.sleep(2.5)                                 # let Echo's feedback tail die before the first reading
    for i, s in enumerate(srcs):
        for k, other in enumerate(srcs):
            call("set_mixer", track=other, mute=(k != i))
        time.sleep(2.0)                             # the meter holds peaks about 1 s
        p = peaks([s, ref], seconds=2.5)
        diff = None if None in (p[s], p[ref]) else round(p[ref] - p[s], 2)
        log("8 audible send gain %s (%.0f dB)" % (s, SENDS_DB[i]), diff is not None and abs(diff - SENDS_DB[i]) <= 0.5,
            source_peak=p[s], return_peak=p[ref], measured_db=diff)
    for other in srcs:
        call("set_mixer", track=other, mute=False)
    call("set_device_on", track=ref, device="Echo", on=True)
    time.sleep(1.5)
    p = peaks(srcs + [ref, "master"], seconds=3.0)
    log("8 Echo return audible", p[ref] is not None and p[ref] > -60, peaks=p)
    # 9. disable the return: the wet contribution must leave the main. Measured on Live 12.4.16 (2026-11-10):
    # a track's own output meter reads BEFORE its mute, and solo overrides mute (a soloed, muted return still
    # plays), so the check is on the main, unsoloed: muting the return must drop the main by the same amount as
    # pulling the return's fader to -inf.
    call("set_mixer", track=ref, mute=True)
    time.sleep(2.0)                                 # the meter holds peaks about 1 s
    q = peaks(["master"], seconds=2.5)
    call("set_mixer", track=ref, mute=False, volume_db=-70.0)
    time.sleep(2.0)
    z = peaks(["master"], seconds=2.5)
    call("set_mixer", track=ref, volume_db=0.0)
    ok = None not in (p["master"], q["master"], z["master"]) and p["master"] - q["master"] >= 0.5 \
        and abs(q["master"] - z["master"]) <= 0.3
    log("9 return muted: wet leaves the main (same as fader -inf)", ok, main_on=p["master"], main_muted=q["master"],
        main_fader_inf=z["master"])
    call("transport", action="stop")
    call("transport", action="stop_all_clips")


if __name__ == "__main__":
    {"build": lambda: build(), "verify": lambda: verify("--reopened" in sys.argv)}[sys.argv[1]]()
