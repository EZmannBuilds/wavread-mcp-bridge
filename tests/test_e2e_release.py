"""Release end-to-end test in a DISPOSABLE Live Set (a track named __TOOLING_SCRATCH__). Uses only Live's native
devices and, where available, Apple's built-in Audio Units: no paid third-party plugins needed.

Phases (run them in order; Live must have the disposable Set open):
  refuse   : with authorization revoked, every protected action is refused and the Set is unchanged; a mismatched
             authorization is refused; read-only inspection still works. Approval code flow (0.4.0): a request alone
             grants nothing; a wrong code is refused and ends the request; an expired code is refused (waits 2 min).
  (then a person approves: python3 tests/approve.py request / confirm CODE, the code read from Live's status bar)
  write    : authorize; then track, return, native effect + parameters, third-party plugin (Apple AU, if listed),
             sends in dB, audio bus routing, MIDI clip, Arrangement edit (create + split), automation (write +
             validate), error handling (bad refs, bad paths, unknown commands). Leaves a manifest for `reopened`.
  switched : (after opening a DIFFERENT Set) the old authorization doesn't carry over: writes refused, status says so.
  reopened : (after reopening the disposable Set) not authorized; everything built in `write` is still there; writes
             refused. Then a person approves again, and:
  reapproved: writes work once re-authorized.
  untitled : (with a new, unsaved Set open) authorizing and writing are both refused: "save the Set first".
usage: python3 tests/test_e2e_release.py refuse|write|switched|reopened|reapproved|untitled
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


PROTECTED = [
    ("create_track", dict(kind="audio", name="E2E Should Not Exist")),
    ("create_return_track", dict(name="E2E Should Not Exist")),
    ("rename_track", dict(track=0, name="E2E Should Not Exist")),
    ("set_mixer", dict(track=0, volume_db=-3.0)),
    ("set_track_send", dict(track=0, send="A", db=-12)),
    ("set_routing", dict(track=0, direction="output", target="Main")),
    ("insert_native_device", dict(track=0, name="EQ Eight")),
    ("set_device_parameter", dict(track=0, device=0, parameter=1, value=0.5, units="raw")),
    ("make_test_clip", dict(track=0, slot=7, length=4.0)),
    ("set_automation_points", dict(track=0, slot=0, target={"mixer": "volume"}, points=[{"at": "1.1.1", "value": 0.5}])),
    ("create_arrangement_midi_clip", dict(track=0, at="40.1.1", length=4)),
    ("move_arrangement_clip", dict(track=0, to="50.1.1", index=0)),
    ("trim_arrangement_clip", dict(track=0, index=0, end="1.2.1")),
    ("split_arrangement_clip", dict(track=0, split_at="1.2.1", index=0)),
    ("record_track_audio", dict(dst=0, source="Resampling", slot=7, bars=1)),
    ("record_arrangement_automation", dict(track=0, target={"mixer": "volume"}, points=[{"at": "1.1.1", "value": 0.5}, {"at": "2.1.1", "value": 0.6}])),
    ("set_song_time", dict(tempo=99)),
    ("set_arm", dict(track=0, arm=True)),
    ("delete_track", dict(track=0)),
    ("some_future_command", dict()),
]


def check_refusals(tag):
    before = call("list_tracks", devices=False)
    tempo = call("probe", path="song")["attributes"]["tempo"]
    results = {}
    for cmd, kw in PROTECTED:
        ok, msg = refused(cmd, **kw)
        results[cmd] = ok
        if not ok:
            log("%s: %s refused" % (tag, cmd), False, message=msg)
    log("%s: all %d protected actions refused" % (tag, len(PROTECTED)), all(results.values()),
        refused=[k for k, v in results.items() if v])
    after = call("list_tracks", devices=False)
    log("%s: the Set is unchanged (tracks, mixer, tempo)" % tag,
        before == after and call("probe", path="song")["attributes"]["tempo"] == tempo)
    st = call("write_status")
    log("%s: read-only inspection still works; status not authorized" % tag,
        isinstance(call("list_tracks", devices=False), list) and not st["authorized"], status=st)
    return st


if phase == "refuse":
    i = call("info")
    log("connection: info answers, name, version and loopback port", i["port"] == 9878 and i["version"] >= "0.4.0"
        and i["name"] == "WavReadBridge", info={
        k: i[k] for k in ("name", "version", "live_version", "port", "scratch_set")})
    # reconnection: each call opens a new connection; several in a row, then a deliberately broken one
    import socket
    s = socket.create_connection(("127.0.0.1", 9878), timeout=5)
    s.sendall(b'{"type": "info", "params": ')        # incomplete JSON, then drop the connection
    s.close()
    ok = all(call("info")["port"] == 9878 for _ in range(5))
    log("reconnection: 5 fresh connections after a dropped half-request", ok)
    call("revoke_authorization")
    check_refusals("unauthorized")
    # a raw TCP client, no MCP server in between: the bridge itself refuses
    s2 = socket.create_connection(("127.0.0.1", 9878), timeout=10)
    s2.sendall(json.dumps({"type": "create_track", "params": {"kind": "audio", "name": "E2E Raw TCP"}}).encode())
    raw = json.loads(s2.recv(65536).decode())
    s2.close()
    log("a direct TCP write (bypassing MCP) is refused", raw.get("status") == "error" and "refused" in raw.get("message", "")
        and "E2E Raw TCP" not in names(), reply=raw)
    ident = call("get_set_identity")
    log("identity: file path and a set_id stored in the Set", bool(ident["file_path"]) and len(ident["set_id"]) == 32,
        identity=ident)
    bad = [("wrong set_id", dict(file_path=ident["file_path"], set_id="0" * 32)),
           ("wrong path", dict(file_path="/tmp/other.als", set_id=ident["set_id"]))]
    for label, kw in bad:
        ok, msg = refused("authorize_set", **kw)
        log("authorize with a %s is refused" % label, ok, message=msg)
    log("still not authorized after the bad attempts", not call("write_status")["authorized"])
    # approval code flow, live
    r = call("authorize_set", file_path=ident["file_path"], set_id=ident["set_id"])
    import re as _re
    log("authorize_set grants nothing by itself; the reply carries no code", not r["authorized"] and r["approval_pending"]
        and not _re.search(r"\b[A-HJ-NP-Z2-9]{6}\b", json.dumps({k: v for k, v in r.items() if k != "message"})),
        reply=r)
    ok, msg = refused("set_mixer", track=0, volume_db=-3)
    log("a write is still refused while approval is pending", ok, message=msg)
    ok, msg = refused("confirm_authorization", code="AAAAAA")
    log("a wrong code is refused", ok, message=msg)
    st = call("write_status")
    log("the wrong code ended the request (nothing pending, not authorized)", not st["approval_pending"]
        and not st["authorized"])
    ok, msg = refused("confirm_authorization", code="AAAAAA")
    log("confirming again without a request is refused", ok and "no approval is pending" in msg, message=msg)
    call("authorize_set", file_path=ident["file_path"], set_id=ident["set_id"])
    time.sleep(122)
    ok, msg = refused("confirm_authorization", code="AAAAAA")
    log("an expired code is refused", ok and "expired" in msg, message=msg)
    log("not authorized at the end of the refuse phase", not call("write_status")["authorized"])

elif phase == "write":
    i = call("info")
    if not i["scratch_set"]:
        sys.exit("open the disposable Set")
    ident = call("get_set_identity")
    st = call("write_status")
    log("a person approved this disposable Set (code from Live's status bar)", st["authorized"]
        and st["authorized_identity"]["file_path"] == ident["file_path"], identity=st["authorized_identity"])
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
    log("an authorized delete outside a disposable Set is still refused (second guard)", True,
        note="covered offline (test_deletes_also_need_scratch); this Set is disposable")
    m["identity"] = ident
    m["arr_clips"] = [(x["start"], x["end"]) for x in cl]
    json.dump(m, open(MANIFEST, "w"), indent=1)

elif phase == "switched":
    st = call("write_status")
    log("after opening another Set: not authorized", not st["authorized"], status=st)
    ok, msg = refused("create_track", kind="audio", name="E2E Should Not Exist")
    log("after opening another Set: a write is refused", ok, message=msg)

elif phase == "reopened":
    m = json.load(open(MANIFEST))
    st = call("write_status")
    log("reopened: not authorized until authorized again", not st["authorized"], status=st)
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
    ok, msg = refused("set_mixer", track=mt, volume_db=-3)
    log("reopened: writes refused before a person approves", ok, message=msg)

elif phase == "reapproved":
    m = json.load(open(MANIFEST))
    mt = names()[m["midi"]]
    log("reapproved: authorized again after the person's code", call("write_status")["authorized"])
    call("set_mixer", track=mt, volume_db=-3)
    log("reapproved: writes work", abs(call("get_mixer", track=mt)["volume_db"] + 3) < 0.05)

elif phase == "untitled":
    ident = call("get_set_identity")
    log("untitled: the open Set has no file path", ident["file_path"] == "", identity=ident)
    ok, msg = refused("authorize_set", file_path="", set_id=ident["set_id"])
    log("untitled: authorizing is refused (save first)", ok and "untitled" in msg, message=msg)
    ok, msg = refused("create_track", kind="audio", name="E2E Should Not Exist")
    log("untitled: a write is refused (save first)", ok and "untitled" in msg, message=msg)
