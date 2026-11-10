"""Live code-flow checks that need a person to read codes from Live's status bar (0.4.0). Run step by step:
  request             -> Live shows code 1
  replace             -> Live shows code 2 (code 1 replaced)
  confirm-old CODE1   -> must be refused (replaced code); the request is used up
  request             -> code 3
  confirm CODE3       -> must grant
  replay CODE3        -> must be refused (already used)
  switch-pending      -> asks for a code; then open ANOTHER Set in Live; then:
  confirm-dead CODE   -> must be refused (the Set switched; the pending code died with the old session)
  arm-and-revoke TRACK -> (authorized) arms TRACK, then revokes
  fire-armed TRACK SLOT -> must be refused unauthorized (launching an empty slot on an armed track records)
  record-on-play      -> with Arrangement Record switched on in Live: transport play must be refused unauthorized
Results append to tests/results/codeflow-live.json.
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from lt import call, Log, LiveError

log = Log(os.path.join(os.path.dirname(__file__), "results", "codeflow-live.json"))


def req():
    i = call("get_set_identity")
    r = call("authorize_set", file_path=i["file_path"], set_id=i["set_id"])
    print(json.dumps(r, indent=1))
    return r


def refused(cmd, **kw):
    try:
        call(cmd, **kw)
        return False, "ran"
    except LiveError as e:
        return "refused" in str(e), str(e)[:200]


step = sys.argv[1]
if step in ("request", "replace", "switch-pending"):
    r = req()
    log("%s: a code is shown, nothing granted" % step, r.get("approval_pending") and not r.get("authorized"))
elif step == "confirm-old":
    ok, msg = refused("confirm_authorization", code=sys.argv[2])
    log("a replaced (older) code is refused", ok, message=msg)
elif step == "confirm":
    r = call("confirm_authorization", code=sys.argv[2])
    log("the right code grants", r["authorized"])
elif step == "replay":
    ok, msg = refused("confirm_authorization", code=sys.argv[2])
    log("a replayed (already used) code is refused", ok, message=msg)
elif step == "confirm-dead":
    ok, msg = refused("confirm_authorization", code=sys.argv[2])
    log("a code requested before a Set switch is dead after it", ok, message=msg)
elif step == "arm-and-revoke":
    call("set_arm", track=sys.argv[2], arm=True)
    call("revoke_authorization")
    log("armed a track, then revoked", not call("write_status")["authorized"])
elif step == "fire-armed":
    ok, msg = refused("fire_clip", track=sys.argv[2], slot=int(sys.argv[3]))
    log("fire on an empty slot of an armed track is refused while unauthorized", ok, message=msg)
elif step == "record-on-stop":
    try:
        call("transport", action="stop")
        log("transport stop is allowed while recording, unauthorized (stopping never records)", True)
    except LiveError as e:
        log("transport stop is allowed while recording, unauthorized (stopping never records)", False, message=str(e)[:200])
elif step == "record-on-play":
    ok, msg = refused("transport", action="play")
    call("transport", action="stop") if not ok else None
    log("transport play with record on is refused while unauthorized", ok, message=msg)
