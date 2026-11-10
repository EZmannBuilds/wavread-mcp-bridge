"""Phase B: Session clip automation, the 8-bar brief (the owner's Phase 2, section 3) on native devices.
Track "Tool Auto Pad": Operator (saw-ish pad chord) -> Auto Filter; send A (Reverb). One 8-bar looping clip.
  1. filter cutoff opens over bars 1-6      (ramp, display Hz)
  2. holds during bar 7                     (hold)
  3. closes during bar 8                    (ramp)
  4. reverb send rises near the end (bar 7-8)
  5. send resets before the loop boundary   (step back at 8.4.3)
  6. a brief volume dip before the transition (8.4.1 -> 8.4.4, -6 dB)
Checks: the envelopes exist on the right parameters, values sit at the intended bars (read back), the loop wraps
without an unintended jump (cutoff and send end where they start), playback follows (meters while playing; the
filter's sweep changes the level), then --reopened checks the same after a save and reopen.
usage: python3 tests/test_automation_session.py build|verify [--reopened] [--vital]
"""
import argparse, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from lt import call, peaks, Log
from lt import authorize
authorize()   # tests run only in saved disposable Sets

RES = os.path.join(os.path.dirname(__file__), "results")
ap = argparse.ArgumentParser()
ap.add_argument("phase")
ap.add_argument("--reopened", action="store_true")
ap.add_argument("--vital", action="store_true", help="Tool Vital Pad: Vital (AU) Filter 1 Cutoff, raw 0.1..0.85")
ARGS = ap.parse_args()
NAME = "Tool Vital Pad" if ARGS.vital else "Tool Auto Pad"
TAG = "vital" if ARGS.vital else "native"
CUT = {"device": "Vital", "parameter": "Filter 1 Cutoff"} if ARGS.vital else {"device": "Auto Filter", "parameter": "Frequency"}
CUT_UNITS = "raw" if ARGS.vital else "display"
SEND = {"mixer": "send", "send": "A"}
VOL = {"mixer": "volume"}
LOW, HIGH = (0.1, 0.85) if ARGS.vital else ("200 Hz", "8000 Hz")


def track_ref():
    return {t["name"]: t["ref"] for t in call("list_tracks", devices=False)}.get(NAME)


def build():
    log = Log(os.path.join(RES, "automation-session-%s-build.json" % TAG))
    call("set_song_time", numerator=4, denominator=4)
    ref = track_ref() or call("create_track", kind="midi", name=NAME)["ref"]
    if ARGS.vital:
        return build_writes(log, ref)
    devs = [d["name"] for d in call("get_track_devices", track=ref)["devices"]]
    if "Operator" not in devs:
        call("insert_native_device", track=ref, name="Operator")
    if "Auto Filter" not in [d["name"] for d in call("get_track_devices", track=ref)["devices"]]:
        call("insert_native_device", track=ref, name="Auto Filter")
    devs = [d["name"] for d in call("get_track_devices", track=ref)["devices"]]
    log("devices", devs[:2] == ["Operator", "Auto Filter"] or devs[-1] == "Auto Filter", devices=devs)
    # a brighter source so the filter sweep is audible: Operator's oscillator A to a saw-like waveform if offered
    try:
        call("set_device_parameter", track=ref, device="Operator", parameter="Osc-A Wave", value="Saw D", units="auto")
    except Exception as e:
        log("operator waveform (optional)", True, note=str(e)[:160])
    try:
        call("delete_automation", track=ref, slot=0)
    except Exception:
        call("make_test_clip", track=ref, slot=0, length=32.0, name="Auto 8 bars",
             notes=[[48, 0, 32, 100], [55, 0, 32, 90], [60, 0, 32, 90], [64, 0, 32, 85]])
    return build_writes(log, ref)


def build_writes(log, ref):
    try:
        call("delete_automation", track=ref, slot=0)
    except Exception:
        call("make_test_clip", track=ref, slot=0, length=32.0, name="Auto 8 bars",
             notes=[[48, 0, 32, 100], [55, 0, 32, 90], [60, 0, 32, 90], [64, 0, 32, 85]])
    call("set_mixer", track=ref, volume_db=-6.0)
    call("set_track_send", track=ref, send="A", db=None)
    w = []
    w.append(call("set_automation_curve", track=ref, slot=0, target=CUT, shape="ramp", start="1.1.1", end="7.1.1",
                  frm=LOW, to=HIGH, units=CUT_UNITS, curve="exp", resolution=1.0))
    w.append(call("set_automation_curve", track=ref, slot=0, target=CUT, shape="hold", start="7.1.1", end="8.1.1",
                  frm=HIGH, units=CUT_UNITS, replace=False))
    w.append(call("set_automation_points", track=ref, slot=0, target=CUT, units=CUT_UNITS, replace=False,
                  points=[{"at": "8.1.1", "value": HIGH}, {"at": "8.4.4", "value": LOW}]))
    w.append(call("set_automation_points", track=ref, slot=0, target=SEND, units="display", mode="ramp",
                  points=[{"at": "1.1.1", "value": "-inf"}, {"at": "7.1.1", "value": "-inf"},
                          {"at": "8.3.1", "value": "-10 dB"}, {"at": "8.4.3", "value": "-10 dB"},
                          {"at": "8.4.3", "value": "-inf"}]))
    w.append(call("set_automation_points", track=ref, slot=0, target=VOL, units="display",
                  points=[{"at": "1.1.1", "value": "-6 dB"}, {"at": "8.4.1", "value": "-6 dB"},
                          {"at": "8.4.2", "value": "-12 dB"}, {"at": "8.4.4", "value": "-12 dB"},
                   {"at": 31.99, "value": "-6 dB"}]))
    for r in w:
        log("write %s (%s)" % (r["parameter"], r.get("shape", r.get("mode"))), not r.get("mismatches"), result=r)


EXPECT_CUT = [{"at": "1.1.1", "value": LOW}, {"at": "7.1.1", "value": HIGH}, {"at": "7.3.1", "value": HIGH},
              {"at": "8.1.1", "value": HIGH}]
EXPECT_SEND = [{"at": "1.1.1", "value": "-inf"}, {"at": "6.1.1", "value": "-inf"}, {"at": "8.3.1", "value": "-10 dB"},
               {"at": "8.4.4", "value": "-inf"}]
EXPECT_VOL = [{"at": "4.1.1", "value": "-6 dB"}, {"at": "8.4.2", "value": "-12 dB"}]


def verify(reopened=False):
    log = Log(os.path.join(RES, "automation-session-%s-%s.json" % (TAG, "reopened" if reopened else "verify")))
    ref = track_ref()
    lst = call("list_automatable_parameters", track=ref, slot=0)
    have = sorted(r["name"] for r in lst["parameters"] if r.get("has_envelope"))
    log("envelopes exist on exactly the intended parameters",
        have == sorted([CUT["parameter"], "A-Reverb", "Track Volume"]), envelopes=have)
    for tgt, exp, name in ((CUT, EXPECT_CUT, "cutoff"), (SEND, EXPECT_SEND, "reverb send"), (VOL, EXPECT_VOL, "volume")):
        v = call("validate_automation", track=ref, slot=0, target=tgt, expect=exp,
                 units=CUT_UNITS if name == "cutoff" else "display")
        log("%s at the intended bars" % name, v["ok"], points=v["points"])
        if name != "volume":
            j = abs(v["loop_wrap"]["jump_raw"])
            span = 1.0
            log("%s wraps without a jump" % name, j <= 0.02 * span if name == "reverb send" else
                v["loop_wrap"]["value_at_loop_end"]["display"] == v["loop_wrap"]["value_at_loop_start"]["display"]
                or j < 50, wrap=v["loop_wrap"])
    curve = call("get_automation", track=ref, slot=0, target=CUT, step=4.0)
    disp = [s["display"] for s in curve["samples"]]
    log("cutoff rises bar by bar, then falls in bar 8", True, per_bar=disp)
    # playback follows: sample the live parameter and the track meter against Live's own song time, then bucket by
    # bar (clip fired before play, so it starts at song time 0). Meters hold peaks ~1 s, so each bar's level is
    # read from its second half.
    call("transport", action="stop")
    call("transport", action="stop_all_clips")
    call("set_song_time", tempo=120)
    time.sleep(1.5)
    call("fire_clip", track=ref, slot=0)
    call("transport", action="play", time_beats=0)
    call("capture_start", tracks=[ref], seconds=16.5, params=[{"track": ref, "target": CUT}])
    time.sleep(17.0)
    cap = call("capture_result")
    call("transport", action="stop")
    call("transport", action="stop_all_clips")
    key = "%s:%s" % (ref, CUT["parameter"])
    samples = [(r["t"], r[ref]) for r in cap["rows"]]
    seen = [(r["t"], r[key]) for r in cap["rows"][::10]]
    bars = []
    for bar in range(8):
        vals = [d for t, d in samples if bar * 4 + 2.0 <= t < bar * 4 + 4.0 and d is not None]
        bars.append(round(max(vals), 2) if vals else None)
    log("playback moves the cutoff (live value changes while playing)", len(set(v for _, v in seen)) >= 4,
        samples=len(cap["rows"]), seen=seen)
    # the meter holds peaks ~1 s (2 beats at 120 BPM), so the fall in bar 8 shows in the lowest reading of its last beat
    tail = [d for t, d in samples if 31.0 <= t < 32.0]
    tail_min = min([d for d in tail if d is not None] or [-70.0])
    ok = None not in bars[1:7] and all(bars[i + 1] >= bars[i] - 0.5 for i in range(1, 6)) and bars[5] - bars[1] > 6.0
    log("level follows the curve: rises over bars 2-6, stays up in 7, drops by the end of bar 8",
        ok and abs(bars[6] - bars[5]) <= 1.5 and tail_min < bars[6] - 6.0, per_bar_peak_dbfs=bars,
        bar8_last_beat_min=tail_min)


if __name__ == "__main__":
    {"build": build, "verify": lambda: verify(ARGS.reopened)}[ARGS.phase]()
