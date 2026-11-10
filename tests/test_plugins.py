"""Priority 3: load every plugin in the inventory on a scratch track, record its parameters, then remove it.
Needs the open scratch set. Only plugins whose URI Live's browser actually lists are tried (read from the browser
first, so no URI is guessed). Authorization can't be read through the LOM: a plugin can load in demo mode. That column
stays for the owner to confirm by eye.
usage: python3 tests/test_plugins.py --uris docs/plugin_uris.json [--vendor MeldaProduction] [--format VST3|AUv2|VST|any]
       [--via tooling|mcp]
--via mcp loads through the working AbletonMCP (port 9877, load_browser_item by song.tracks index) and verifies
through WavReadBridge; use it while WavReadBridge's own browser lookup is the 0.1.0 build (it missed every plugin
URI, fixed in 0.1.1). Effects load on an audio bench track; anything that won't load there is retried on a MIDI
bench track (instruments).
Results: tests/results/plugins.json
"""
import argparse, json, os, socket, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from lt import call, load, LiveError
from lt import authorize
authorize()   # tests run only in disposable Sets; writes need the Set authorized (0.3.0)

ap = argparse.ArgumentParser()
ap.add_argument("--vendor")
ap.add_argument("--format", default="VST3")
ap.add_argument("--uris", required=True, help="JSON list of browser URIs (from the ableton server's browser)")
ap.add_argument("--via", default="tooling", choices=["tooling", "mcp"])
a = ap.parse_args()
if not call("info")["scratch_set"]:
    sys.exit("open the scratch set")
uris = json.load(open(a.uris))
if a.vendor:
    uris = [u for u in uris if (":" + a.vendor.replace(" ", "%20") + ":") in u]
uris = [u for u in uris if ("#" + a.format + ":") in u or a.format == "any"]


def mcp(cmd, params):
    s = socket.create_connection(("127.0.0.1", 9877), timeout=60)
    s.sendall(json.dumps({"type": cmd, "params": params}).encode())
    buf = b""
    while True:
        c = s.recv(65536)
        if not c:
            break
        buf += c
        try:
            r = json.loads(buf.decode())
            break
        except ValueError:
            pass
    s.close()
    if r.get("status") == "error":
        raise LiveError(r.get("message"))
    return r.get("result", r)


def snapshot():
    return {t["ref"]: [d["name"] if isinstance(d, dict) else d for d in t["devices"]] for t in call("list_tracks")}


def load_mcp(track, uri):
    before = snapshot()
    mcp("load_browser_item", {"track_index": int(track.split(":")[1]), "item_uri": uri})
    v = None
    for _ in range(60):
        time.sleep(0.25)
        v = call("verify_load", track=track, before=before)
        if v.get("ok"):
            return v
    raise LiveError("load did not verify: %s" % v)


def bench(name, kind):
    names = {t["name"]: t["ref"] for t in call("list_tracks", devices=False)}
    return names.get(name) or call("create_track", kind=kind, name=name)["ref"]


audio = bench("Tool Plugin Bench", "audio")
midi = bench("Tool Plugin Bench MIDI", "midi")
out_path = os.path.join(os.path.dirname(__file__), "results", "plugins.json")
results = json.load(open(out_path)) if os.path.exists(out_path) else {}
for uri in uris:
    if uri in results and results[uri].get("loads"):
        continue
    row = {"uri": uri, "tested": time.strftime("%Y-%m-%d %H:%M"), "via": a.via}
    errors = []
    for track, kind in ((audio, "effect"), (midi, "instrument")):
        try:
            v = load_mcp(track, uri) if a.via == "mcp" else load(track, uri)
            devs = call("get_track_devices", track=track)["devices"]
            d = len(devs) - 1
            ps = call("get_device_parameters", track=track, device=d)["parameters"]
            row.update(loads=True, loaded_as=kind, device=v["loaded"], class_name=v["class_name"],
                       parameter_count=len(ps),
                       parameters=[{k: p.get(k) for k in ("name", "min", "max", "display", "quantized", "items")}
                                   for p in ps])
            call("delete_device", track=track, device=d)
            break
        except LiveError as e:
            errors.append("%s: %s" % (kind, str(e)[:300]))
    if not row.get("loads"):
        row.update(loads=False, error=errors)
    results[uri] = row
    json.dump(results, open(out_path, "w"), indent=1)
    print(("OK   " if row.get("loads") else "FAIL ") + uri, row.get("loaded_as", ""),
          row.get("parameter_count", row.get("error")), flush=True)
