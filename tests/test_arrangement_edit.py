"""Arrangement clip editing proven by sound. The source is an AUDIO clip (an 8-bar Vital render with a filter sweep, so
every beat sounds different): audio playback is deterministic, so identical playback nulls. (Operator didn't null against
itself: its oscillators free-run.) Also checks create_arrangement_midi_clip on a MIDI track.
  1. load the audio file at bar 1;
  2. render bars 1-5 (A);
  3. split at bar 3 -> two clips [0,8) and [8,16); render again (B); A - B must null;
  4. move the second half to bar 9; its render must null against A's bars 3-4;
  5. trim the first clip's head to bar 2; bar 2 must still null against A's bar 2, bar 1 must be silent;
  6. copy the first clip to bar 13 on the same track; positions read back.
usage: python3 tests/test_arrangement_edit.py SOURCE.wav   (scratch set; results tests/results/arrangement-edit.json)
"""
import math, os, subprocess, sys, time, json
sys.path.insert(0, os.path.dirname(__file__))
from lt import call, Log, LiveError
from lt import authorize
authorize()   # tests run only in disposable Sets; writes need the Set authorized (0.3.0)

RES = os.path.join(os.path.dirname(__file__), "results")
log = Log(os.path.join(RES, "arrangement-edit.json"))
if not call("info")["scratch_set"]:
    sys.exit("open the scratch set")
NAME = "Tool Arr Audio"
SRC = sys.argv[1] if len(sys.argv) > 1 else None
names = {t["name"]: t["ref"] for t in call("list_tracks", devices=False)}
M = names["Tool Arr Test"] if "Tool Arr Test" in names else call("create_track", kind="midi", name="Tool Arr Test")["ref"]
for c in reversed(call("list_arrangement_clips", track=M)["clips"]):
    call("delete_arrangement_clip", track=M, index=c["index"])
r = call("create_arrangement_midi_clip", track=M, at="1.1.1", length=16, notes=[[60, 0, 1, 100]], name="Arr midi")
log("create a MIDI clip in the Arrangement", r["start"] == 0.0 and r["end"] == 16.0, result=r)
T = names.get(NAME) or call("create_track", kind="audio", name=NAME)["ref"]
for c in reversed(call("list_arrangement_clips", track=T)["clips"]):
    call("delete_arrangement_clip", track=T, index=c["index"])
call("set_song_time", tempo=120)
r = call("create_audio_clip", track=T, path=SRC, at="1.1.1")
cl0 = call("list_arrangement_clips", track=T)["clips"]
if cl0[0]["end"] > 16.0:          # keep the first 4 bars as the test clip
    call("trim_arrangement_clip", track=T, at="1.1.1", end="5.1.1")
log("audio clip at bar 1 (4 bars)", [(c["start"], c["end"]) for c in call("list_arrangement_clips", track=T)["clips"]] == [(0.0, 16.0)],
    clips=call("list_arrangement_clips", track=T)["clips"])
call("set_song_time", tempo=120, numerator=4, denominator=4, loop=False)
REND = call("create_track", kind="audio", name="Tool Arr Render %d" % int(time.time() % 100000))["ref"]   # fresh slots
slot = [0]


def render(beat, bars):
    call("transport", action="stop")
    call("transport", action="stop_all_clips")
    time.sleep(0.6)
    call("back_to_arrangement")
    call("set_mixer", track=T, solo=True)
    call("set_song_time", position=beat)
    time.sleep(0.4)
    call("record_track_audio", dst=REND, source="Resampling", slot=slot[0], bars=bars)
    slot[0] += 1
    st = None
    for _ in range(80):
        time.sleep(0.5)
        st = call("record_track_audio_status")
        if st["done"]:
            break
    call("transport", action="stop")
    call("set_mixer", track=T, solo=False)
    return st["file"]


def null_db(fa, sa, fb, sb, beats):
    """Residual of A[sa:sa+beats] - B[sb:sb+beats] relative to A, in dB (beats at 120 BPM = 0.5 s)."""
    code = r'''
import sys, numpy as np, soundfile as sf, math
fa, sa, fb, sb, n = sys.argv[1], float(sys.argv[2]), sys.argv[3], float(sys.argv[4]), float(sys.argv[5])
a, sr = sf.read(fa, always_2d=True); b, _ = sf.read(fb, always_2d=True)
i, j, k = int(sa * 0.5 * sr), int(sb * 0.5 * sr), int(n * 0.5 * sr)
x, y = a[i:i + k], b[j:j + k]
ra = math.sqrt(float(np.mean(x ** 2))) + 1e-12; rr = math.sqrt(float(np.mean((x - y) ** 2))) + 1e-12
rb = math.sqrt(float(np.mean(y ** 2))) + 1e-12
print(round(20 * math.log10(rr / ra), 1), round(20 * math.log10(ra), 1), round(20 * math.log10(rb), 1))
'''
    out = subprocess.run(["/opt/homebrew/bin/uv", "run", "-q", "--with", "numpy", "--with", "soundfile", "python", "-c", code,
                          fa, str(sa), fb, str(sb), str(beats)], capture_output=True, text=True)
    return [float(v) for v in out.stdout.split()] if out.returncode == 0 else out.stderr[-300:]


A = render(0, 4)
r = call("split_arrangement_clip", track=T, split_at="3.1.1", at="1.1.1")
cl = call("list_arrangement_clips", track=T)["clips"]
log("split at bar 3: two clips [0,8) and [8,16)", [(c["start"], c["end"]) for c in cl] == [(0.0, 8.0), (8.0, 16.0)], clips=cl)
B = render(0, 4)
n = null_db(A, 0, B, 0, 16)
log("split plays exactly as before (null)", isinstance(n, list) and n[0] < -40, residual_db=n)
r = call("move_arrangement_clip", track=T, to="9.1.1", at="3.1.1")
cl = call("list_arrangement_clips", track=T)["clips"]
log("move the second half to bar 9", [(c["start"], c["end"]) for c in cl] == [(0.0, 8.0), (32.0, 40.0)], clips=cl)
C = render(32, 2)
n = null_db(A, 8, C, 0, 8)
log("moved clip plays A's bars 3-4 (null, allowing the edge fade)", isinstance(n, list) and n[0] < -35, residual_db=n)
r = call("trim_arrangement_clip", track=T, at="1.1.1", start="2.1.1")
cl = call("list_arrangement_clips", track=T)["clips"]
log("trim the head to bar 2", [(c["start"], c["end"]) for c in cl][0] == (4.0, 8.0), clips=cl)
D = render(0, 2)
n1 = null_db(A, 4, D, 4, 4)
n0 = null_db(D, 0, D, 0, 4)
# A new clip edge gets Live's short automatic edge fade (a few ms), so a trimmed head nulls to about -39 dB, not -200
log("bar 2 unchanged after trimming (null, allowing Live's clip-edge fade)", isinstance(n1, list) and n1[0] < -35,
    residual_db=n1)
log("bar 1 now silent", isinstance(n0, list) and n0[1] < -60, levels=n0)
r = call("copy_arrangement_clip", track=T, to="13.1.1", at="2.1.1")
cl = call("list_arrangement_clips", track=T)["clips"]
log("copy to bar 13", (48.0, 52.0) in [(c["start"], c["end"]) for c in cl], clips=cl)
