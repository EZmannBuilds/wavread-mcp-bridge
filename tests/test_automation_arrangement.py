"""Phase B: Arrangement automation by real-time recording (the LOM can't draw arrangement lanes).
On "Tool Vital Pad" (Vital AU with Filter 1 Cutoff configured, an 8-bar plain clip in the Arrangement at bar 1):
record Filter 1 Cutoff opening over bars 1-6 (0.1 -> 0.85), holding in bar 7, closing in bar 8 (-> 0.1 at 8.4.4),
then play the Arrangement back and capture the live value at points inside each section.
usage: python3 tests/test_automation_arrangement.py record|verify [--reopened]
Measured 2026-11-10: recording only shows up once the track follows the Arrangement (the recorder presses Back to
Arrangement first); a track still playing a session clip records but plays the session clip instead.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from lt import call, Log
from lt import authorize
authorize()   # tests run only in disposable Sets; writes need the Set authorized (0.3.0)

RES = os.path.join(os.path.dirname(__file__), "results")
NAME = "Tool Vital Pad"
CUT = {"device": "Vital", "parameter": "Filter 1 Cutoff"}
POINTS = [{"at": "1.1.1", "value": 0.1}, {"at": "7.1.1", "value": 0.85}, {"at": "8.1.1", "value": 0.85},
          {"at": "8.4.4", "value": 0.1}]
# (beat, expected): linear 0.1 -> 0.85 over beats 0-24, 0.85 to 28, then down to 0.1 at 31.75
CHECKS = [(2.0, 0.1625), (12.0, 0.475), (20.0, 0.725), (26.0, 0.85), (29.875, 0.475)]


def ref():
    return {t["name"]: t["ref"] for t in call("list_tracks", devices=False)}[NAME]


def record():
    log = Log(os.path.join(RES, "automation-arrangement-record.json"))
    r = ref()
    call("transport", action="stop")
    call("set_song_time", tempo=120, numerator=4, denominator=4, loop=False)
    s = call("record_arrangement_automation", track=r, target=CUT, units="raw", preroll_bars=1, points=POINTS)
    for _ in range(60):
        time.sleep(1)
        st = call("record_arrangement_status")
        if st["done"]:
            break
    log("recording pass ran with record mode and playback on", st["done"] and not st["error"] and st.get("record_mode_seen")
        and st["written"] > 100, status=st, started=s)
    log("the parameter now has arrangement automation (state 1)", call("param_state", track=r, target=CUT)["automation_state"] == 1)


def verify(reopened=False):
    log = Log(os.path.join(RES, "automation-arrangement-%s.json" % ("reopened" if reopened else "verify")))
    r = ref()
    call("transport", action="stop")
    call("transport", action="stop_all_clips")
    call("set_song_time", tempo=120, loop=False)
    call("back_to_arrangement")        # stopping session clips detaches tracks from the Arrangement
    time.sleep(0.5)
    log("automation state 1 (playing) once the track follows the Arrangement",
        call("param_state", track=r, target=CUT)["automation_state"] == 1)
    call("transport", action="play", time_beats=0)
    call("capture_start", tracks=[r], seconds=16.5, params=[{"track": r, "target": CUT}])
    time.sleep(17.0)
    rows = call("capture_result")["rows"]
    call("transport", action="stop")
    key = "%s:%s" % (r, CUT["parameter"])
    got = []
    def expected(b):   # the intended curve at song beat b
        if b <= 24:
            return 0.1 + 0.75 * b / 24.0
        if b <= 28:
            return 0.85
        return 0.85 - 0.75 * min(b - 28, 3.75) / 3.75
    for beat, _ in CHECKS:
        near = min(rows, key=lambda x: abs(x["t"] - beat))
        want = expected(near["t"])
        got.append({"beat": beat, "at": near["t"], "want": round(want, 4), "got": near[key],
                    "ok": abs(near["t"] - beat) < 0.3 and abs(near[key] - want) < 0.03})
    log("playback follows the recorded curve (open, hold, close)", all(g["ok"] for g in got), checks=got)


if __name__ == "__main__":
    {"record": record, "verify": lambda: verify("--reopened" in sys.argv)}[sys.argv[1]]()
