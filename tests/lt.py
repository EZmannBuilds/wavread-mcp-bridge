"""Tiny client for the Faderhand Remote Script (127.0.0.1:9878), shared by the tests."""
import json, socket, time


class LiveError(RuntimeError):
    pass


def call(command, timeout=30.0, **params):
    params = {k: v for k, v in params.items() if v is not None}
    with socket.create_connection(("127.0.0.1", 9878), timeout=5) as s:
        s.settimeout(timeout)
        s.sendall(json.dumps({"type": command, "params": params}).encode())
        buf, dec = b"", json.JSONDecoder()
        while True:
            chunk = s.recv(1 << 20)
            if not chunk:
                raise LiveError("connection closed")
            buf += chunk
            try:
                reply, _ = dec.raw_decode(buf.decode())
                break
            except ValueError:
                continue
    if reply.get("status") != "success":
        raise LiveError(reply.get("message"))
    return reply["result"]


def retry(command, tries=8, wait=0.25, **params):
    for k in range(tries):
        try:
            return call(command, **params)
        except LiveError as e:
            if k == tries - 1 or not any(w in str(e) for w in ("not ready", "not offered", "cannot route")):
                raise
            time.sleep(wait)


def peaks(tracks, seconds=3.0, interval=0.08):
    """Peak dBFS per track over the window (None = at or below -70)."""
    out = {t: None for t in tracks}
    t0 = time.time()
    while time.time() - t0 < seconds:
        m = call("get_meters", tracks=tracks)["meters"]
        for ref, v in m.items():
            d = v.get("dbfs")
            if d is not None and (out.get(ref) is None or d > out[ref]):
                out[ref] = d
        time.sleep(interval)
    return out


def load(track, uri, position=None):
    started = call("load_browser_item", track=track, uri=uri)
    for _ in range(60):
        time.sleep(0.25)
        v = call("verify_load", track=track, before=started["before"], position=position)
        if v.get("ok"):
            return v
    raise LiveError("load did not verify: %s" % v)


class Log:
    def __init__(self, path):
        self.path, self.rows = path, []

    def __call__(self, step, ok, **detail):
        row = dict(step=step, ok=bool(ok), **detail)
        self.rows.append(row)
        print(("PASS " if ok else "FAIL ") + step, json.dumps(detail, default=str)[:400], flush=True)
        json.dump(self.rows, open(self.path, "w"), indent=1, default=str)
        return ok


def authorize():
    """Tests run only in a saved disposable Set (a track named __TOOLING_SCRATCH__). No approval code (0.5.0)."""
    i = call("info")
    if not i.get("scratch_set"):
        raise SystemExit("refused: tests run only in a disposable Set (a track named __TOOLING_SCRATCH__)")
    st = call("write_status")
    if not st["writes_allowed"]:
        raise SystemExit("this Set is untitled: save it first")
    return st
