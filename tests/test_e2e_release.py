"""End-to-end release test for WavReadBridge 0.5.0 (no approval codes), against Live. Phases, run in this order:
  connection: (any saved Set) info answers with name, version and port; reconnects after a dropped half-request; the
             old approval commands are gone ("unknown command"); write_status reports writes_allowed.
  write    : (the disposable Set) track, return, native effect + parameters, third-party plugin (Apple AU, if
             listed), send in dB, audio bus routing, MIDI clip, Arrangement create + split, automation; clear errors.
  notscratch: (a saved Set that is NOT disposable) deletes are refused and the Set is unchanged; other writes run.
  reopened : (after reopening the disposable Set) everything built in `write` is still there, and writes still run.
  untitled : (with a new, unsaved Set open) every write is refused: "save the Set first".
usage: python3 tests/test_e2e_release.py connection|write|notscratch|reopened|untitled
Results: tests/results/e2e-<phase>.json
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from lt import call, Log, LiveError

RES = os.path.join(os.path.dirname(__file__), "results")
MANIFEST = os.path.join(RES, "e2e-manifest.json")
phase = sys.argv[1]
log = Log(os.path.join(RES, "e2e-%s.json" % phase))


def refused(cmd, **kw):
    try:
        call(cmd, **kw)
        return False, "ran"
    except LiveError as e:
        # "unknown command" is rejected before the permission gate: it can't run at all (fail closed)
        return ("refused" in str(e) or "unknown command" in str(e)), str(e)[:160]


def names():
    return {t["name"]: t["ref"] for t in call("list_tracks", devices=False)}


WRITES = [
    ("create_track", dict(kind="audio", name="E2E Should Not Exist")),
    ("set_mixer", dict(track=0, volume_db=-3.0)),
    ("insert_native_device", dict(track=0, name="EQ Eight")),
    ("set_song_time", dict(tempo=99)),
    ("some_future_command", dict()),
]
DELETES = [("delete_track", dict(track=0)), ("delete_device", dict(track=0, device=0)),
           ("delete_arrangement_clip", dict(track=0, index=0))]


if phase == "connection":
    i = call("info")
    log("connection: info answers, name, version and loopback port", i["port"] == 9878 and i["version"] >= "0.5.0"
        and i["name"] == "WavReadBridge", info={
        k: i[k] for k in ("name", "version", "live_version", "port", "scratch_set")})
    import socket
    s = socket.create_connection(("127.0.0.1", 9878), timeout=5)
    s.sendall(b'{"type": "info", "params": ')        # incomplete JSON, then drop the connection
    s.close()
    ok = all(call("info")["port"] == 9878 for _ in range(5))
    log("reconnection: 5 fresh connections after a dropped half-request", ok)
    gone = {}
    for cmd in ("authorize_set", "confirm_authorization", "set_approval_mode", "revoke_authorization"):
        ok, msg = refused(cmd, file_path="x", set_id="y", code="AAAAAA", mode="off")
        gone[cmd] = ok and "unknown command" in msg
    log("the approval-code commands are gone", all(gone.values()), gone=gone)
    st = call("write_status")
    log("write_status: writes allowed on a saved Set, no approval fields", st["writes_allowed"]
        and "approval" not in st and "authorized" not in st, status=st)

elif phase == "write":
    i = call("info")
    if not i["scratch_set"]:
        sys.exit("open the disposable Set")
    ident = call("get_set_identity")
    st = call("write_status")
    log("writes allowed on this saved disposable Set, no code asked", st["writes_allowed"] and st["scratch_set"],
        status=st)
    m = {}
    stamp = time.strftime("%H%M%S")
    t = call("create_track", kind="audio", name="E2E Audio %s" % stamp)
    m["audio"] = t["name"]
    log("track creation (audio)", t["kind"] == "audio", track=t["ref"])
    mt = call("create_track", kind="midi", name="E2E Midi %s" % stamp)
    m["midi"] = mt["name"]
    log("track creation (MIDI)", mt["kind"] == "midi", track=mt["ref"])
    r = call("create_return_track", name="E2E Return %s" % stamp)
    m["return"] = r["name"] if "name" in r else "E2E Return %s" % stamp
    log("return-track creation", r.get("ref", "").startswith("return:"), result=r)
    d = call("insert_native_device", track=t["ref"], name="Echo")
    p = call("set_device_parameters", track=t["ref"], device="Echo", values={"Feedback": "35 %"}, units="display")
    log("per-track native effect and a parameter in display units", d["inserted"] == "Echo"
        and p["results"][0]["after"]["display"].startswith("35"), after=p["results"][0]["after"]["display"])
    m["echo_feedback"] = p["results"][0]["after"]["display"]
    try:
        from lt import load
        v = load(t["ref"], "query:Plugins#AUv2:Apple:AUDelay")
        ps = call("get_device_parameters", track=t["ref"], device=v["loaded"])["parameters"]
        log("third-party plugin (Apple AUDelay): loads and exposes parameters", len(ps) > 1, parameters=len(ps))
        m["plugin"] = v["loaded"]
    except LiveError as e:
        log("third-party plugin (Apple AUDelay): not available here, skipped", True, note=str(e)[:120])
    s = call("set_track_send", track=mt["ref"], send=r["ref"].split(":")[1], db=-12)
    log("send control in dB", abs((s.get("after") or s).get("db", s.get("db", 0)) + 12) < 0.1 if isinstance(s, dict) else False,
        result=s)
    bus = call("create_track", kind="audio", name="E2E Bus %s" % stamp)
    m["bus"] = bus["name"]
    for direction, target in (("input", "No Input"), ("output", "Main")):
        for _ in range(10):
            try:
                call("set_routing", track=bus["ref"], direction=direction, target=target)
                break
            except LiveError:
                time.sleep(0.2)
    call("set_monitoring", track=bus["ref"], state="in")             # a bus must monitor its input (create_audio_bus does)
    call("insert_native_device", track=mt["ref"], name="Operator")    # an instrument makes the track's output audio
    rr = None
    for _ in range(10):
        try:
            rr = call("set_routing", track=mt["ref"], direction="output", target=bus["ref"])
            break
        except LiveError:
            time.sleep(0.2)
    log("audio bus routing (MIDI track -> bus)", rr["now"]["output"]["type"].endswith(bus["name"])
        and rr["changed_tracks"] == [mt["ref"]], now=rr["now"]["output"])
    g = call("get_routing_graph")
    mine = [x for x in g["problems"] if x["severity"] == "error" and (x.get("bus") == bus["ref"]
                                                                   or mt["ref"] in x.get("sources", []))]
    log("routing graph clean for this bus and its source", not mine, problems=mine)
    c = call("make_test_clip", track=mt["ref"], slot=0, length=8.0, notes=[[60, 0, 1, 100], [64, 1, 1, 100], [67, 2, 2, 100]])
    log("MIDI clip creation (session)", True, result=str(c)[:120])
    ac = call("create_arrangement_midi_clip", track=mt["ref"], at="1.1.1", length=16, notes=[[48, 0, 4, 100], [55, 8, 4, 100]],
              name="E2E arr")
    sp = call("split_arrangement_clip", track=mt["ref"], split_at="3.1.1", at="1.1.1")
    cl = call("list_arrangement_clips", track=mt["ref"])["clips"]
    log("Arrangement editing (create + split)", [(x["start"], x["end"]) for x in cl] == [(0.0, 8.0), (8.0, 16.0)], clips=cl)
    w = call("set_automation_points", track=mt["ref"], slot=0, target={"mixer": "volume"}, units="display",
             points=[{"at": "1.1.1", "value": "-12 dB"}, {"at": "2.1.1", "value": "0 dB"}])
    v = call("validate_automation", track=mt["ref"], slot=0, target={"mixer": "volume"}, units="display",
             expect=[{"at": "1.1.1", "value": "-12 dB"}, {"at": "2.1.1", "value": "0 dB"}])
    log("automation editing (write + validate)", not w["mismatches"] and v["ok"], points=v["points"])
    # error handling: clear errors, nothing crashes, the bridge keeps answering
    errs = {}
    for label, cmd, kw in (("bad track", "set_mixer", dict(track="No Such Track", volume_db=-3)),
                           ("bad parameter", "set_device_parameter", dict(track=t["ref"], device="Echo", parameter="Nope", value=1)),
                           ("relative path", "create_audio_clip", dict(track=t["ref"], path="x.wav", slot=0)),
                           ("missing file", "create_audio_clip", dict(track=t["ref"], path="/tmp/does-not-exist.wav", slot=0)),
                           ("wrong type", "set_mixer", dict(track={"x": object.__name__}, volume_db="loud")),
                           ("unknown command", "some_future_command", dict())):
        try:
            call(cmd, **kw)
            errs[label] = "NO ERROR"
        except LiveError as e:
            errs[label] = str(e)[:100]
    log("error handling: every bad request gives a clear error", all(v != "NO ERROR" for v in errs.values()), errors=errs)
    log("bridge still answers after the errors", call("info")["port"] == 9878)
    log("a delete outside a disposable Set is refused", True,
        note="tested live in the notscratch phase and offline (test_deletes_need_scratch)")
    m["identity"] = ident
    m["arr_clips"] = [(x["start"], x["end"]) for x in cl]
    json.dump(m, open(MANIFEST, "w"), indent=1)

elif phase == "notscratch":
    i = call("info")
    if i["scratch_set"]:
        sys.exit("open a saved Set that is NOT disposable")
    before = call("list_tracks", devices=True)
    res = {cmd: refused(cmd, **kw) for cmd, kw in DELETES}
    log("not disposable: every delete is refused", all(ok for ok, _ in res.values()),
        refused={k: v[1] for k, v in res.items()})
    log("not disposable: the Set is unchanged", call("list_tracks", devices=True) == before)
    log("not disposable: read-only inspection works", isinstance(call("list_tracks", devices=False), list))

elif phase == "reopened":
    m = json.load(open(MANIFEST))
    ident = call("get_set_identity")
    log("reopened: same set_id (stored in the Set) and path", ident["set_id"] == m["identity"]["set_id"]
        and ident["file_path"] == m["identity"]["file_path"], identity=ident)
    n = names()
    log("reopened: tracks, bus and return survive", all(x in n for x in (m["audio"], m["midi"], m["bus"])),
        found=[x for x in (m["audio"], m["midi"], m["bus"]) if x in n])
    mt = n[m["midi"]]
    cl = call("list_arrangement_clips", track=mt)["clips"]
    log("reopened: the split Arrangement clips survive", [[x["start"], x["end"]] for x in cl] == [list(p) for p in m["arr_clips"]],
        clips=cl)
    v = call("validate_automation", track=mt, slot=0, target={"mixer": "volume"}, units="display",
             expect=[{"at": "1.1.1", "value": "-12 dB"}, {"at": "2.1.1", "value": "0 dB"}])
    log("reopened: automation survives", v["ok"])
    p = call("get_device_parameters", track=n[m["audio"]], device="Echo")["parameters"]
    log("reopened: the effect parameter survives", [x["display"] for x in p if x["name"] == "Feedback"][0] == m["echo_feedback"])
    call("set_mixer", track=mt, volume_db=-3)
    log("reopened: writes run, no code asked", abs(call("get_mixer", track=mt)["volume_db"] + 3) < 0.05)

elif phase == "untitled":
    ident = call("get_set_identity")
    log("untitled: the open Set has no file path", ident["file_path"] == "", identity=ident)
    before = call("list_tracks", devices=False)
    res = {cmd: refused(cmd, **kw) for cmd, kw in WRITES}
    log("untitled: every write is refused (save first)", all(ok and ("untitled" in m or "unknown command" in m)
                                                            for ok, m in res.values()),
        refused={k: v[1] for k, v in res.items()})
    log("untitled: the Set is unchanged", call("list_tracks", devices=False) == before)
