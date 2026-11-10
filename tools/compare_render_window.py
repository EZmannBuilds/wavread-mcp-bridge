"""Compare a re-render against the same window of an earlier render (version checks: does a plugin update change a
part?). Aligns by cross-correlation, then reports LUFS, peak, RMS, band balance, and the null residual (raw and
gain-matched, per second). A patch with per-note randomness (random oscillator phase, unison) won't null against
ITSELF: null two re-renders before reading anything into the residual (Vital "Bass - 808 Glide" did not, 2026-11-10).
run: uv run -q --with numpy --with soundfile --with pyloudnorm --with scipy python tools/compare_render_window.py
     REFERENCE.wav NEW.wav   (edit the window a0/a1 below: seconds in the reference)
"""
import sys, json, math
import numpy as np, soundfile as sf, pyloudnorm as pyln
from scipy.signal import fftconvolve
ref_path, new_path = sys.argv[1], sys.argv[2]
info = sf.info(ref_path); sr = info.samplerate
a0, a1 = 841.69 - 1.0, 882.25 + 1.0
ref, _ = sf.read(ref_path, start=int(a0 * sr), stop=int(a1 * sr), always_2d=True)
new, sr2 = sf.read(new_path, always_2d=True)
assert sr == sr2, (sr, sr2)
# align: cross-correlate mono signals (first 20 s of new against the reference window)
rm, nm = ref.mean(1), new.mean(1)
seg = nm[: sr * 20]
c = fftconvolve(rm, seg[::-1], mode="valid")
off = int(np.argmax(c))
r = ref[off: off + len(new)]
n = new[: len(r)]
def db(x): return round(20 * math.log10(x), 2) if x > 1e-12 else None
def bands(x):
    m = x.mean(1); s = np.abs(np.fft.rfft(m * np.hanning(len(m)))) ** 2; f = np.fft.rfftfreq(len(m), 1 / sr); t = s.sum()
    return {k: round(10 * math.log10(max(s[(f >= lo) & (f < hi)].sum() / t, 1e-12)), 2) for k, lo, hi in
            (("sub<60", 20, 60), ("low60-250", 60, 250), ("mid250-2k", 250, 2000), ("high2k-8k", 2000, 8000), ("air>8k", 8000, 20000))}
meter = pyln.Meter(sr)
out = {"offset_into_ref_window_s": round(off / sr, 4), "expected_offset_s": 1.0, "seconds_compared": round(len(r) / sr, 3)}
for k, x in (("ref_1_0_7", r), ("new_1_6_4", n)):
    out[k] = {"lufs": round(meter.integrated_loudness(x), 2), "peak_dbfs": db(np.max(np.abs(x))),
              "rms_dbfs": db(np.sqrt(np.mean(x ** 2))), "bands": bands(x)}
res = r - n
out["null_residual_rms_dbfs"] = db(np.sqrt(np.mean(res ** 2)))
out["null_residual_vs_ref_db"] = round(out["null_residual_rms_dbfs"] - out["ref_1_0_7"]["rms_dbfs"], 2)
g = float(np.sum(r * n) / max(np.sum(n * n), 1e-12))
res2 = r - g * n
out["gain_matched_null"] = {"gain_db": db(abs(g)), "residual_vs_ref_db": round(db(np.sqrt(np.mean(res2 ** 2))) - out["ref_1_0_7"]["rms_dbfs"], 2)}
out["corr"] = round(float(np.corrcoef(r.mean(1), n.mean(1))[0, 1]), 5)
# residual over time (1 s windows), to see whether it's everywhere or only on glides/onsets
w = sr
out["residual_vs_ref_per_second_db"] = [round(db(np.sqrt(np.mean(res[i:i+w] ** 2))) - db(np.sqrt(np.mean(r[i:i+w] ** 2))), 1)
                                        if np.mean(r[i:i+w] ** 2) > 1e-10 else None for i in range(0, len(r) - w, w)]
print(json.dumps(out, indent=1))
