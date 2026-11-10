#!/usr/bin/env python3
"""Compare two renders for an A/B decision (the owner's Phase 2, section 10). Measures each file and the difference, and
writes loudness-matched copies (both at the quieter file's integrated LUFS) so the comparison is by ear at equal
loudness. It reports measurements, never a verdict: which version serves the music is a listening decision.
run: uv run -q --with numpy --with soundfile --with pyloudnorm --with scipy python tools/ab_analyze.py A.wav B.wav
     [--out-dir DIR]
"""
import argparse, json, math, os
import numpy as np, soundfile as sf, pyloudnorm as pyln
from scipy.signal import resample_poly

ap = argparse.ArgumentParser()
ap.add_argument("a")
ap.add_argument("b")
ap.add_argument("--out-dir")
a = ap.parse_args()
BANDS = [("sub <60", 20, 60), ("low 60-250", 60, 250), ("mid 250-2k", 250, 2000), ("high 2k-8k", 2000, 8000),
         ("air >8k", 8000, 20000)]


def db(x):
    return round(20 * math.log10(x), 2) if x > 1e-12 else None


def measure(path):
    x, sr = sf.read(path, always_2d=True)
    mono = x.mean(axis=1)
    peak = float(np.max(np.abs(x)))
    rms = float(np.sqrt(np.mean(x ** 2)))
    spec = np.abs(np.fft.rfft(mono * np.hanning(len(mono)))) ** 2
    f = np.fft.rfftfreq(len(mono), 1.0 / sr)
    tot = float(spec.sum()) or 1e-12
    bands = {n: round(10 * math.log10(max(float(spec[(f >= lo) & (f < hi)].sum()) / tot, 1e-12)), 2)
             for n, lo, hi in BANDS}
    corr = float(np.corrcoef(x[:, 0], x[:, 1])[0, 1]) if x.shape[1] == 2 and np.std(x[:, 0]) > 0 and np.std(x[:, 1]) > 0 else None
    return x, sr, {
        "file": path, "seconds": round(len(x) / sr, 3), "sample_rate": sr,
        "lufs": round(float(pyln.Meter(sr).integrated_loudness(x)), 2),
        "peak_dbfs": db(peak), "true_peak_dbtp": db(float(np.max(np.abs(resample_poly(x, 4, 1, axis=0))))),
        "rms_dbfs": db(rms), "crest_db": round(db(peak) - db(rms), 2) if peak > 0 and rms > 0 else None,
        "spectral_centroid_hz": round(float((f * spec).sum() / tot), 1),
        "band_share_db": bands, "lr_correlation": round(corr, 3) if corr is not None else None}


xa, sra, ma = measure(a.a)
xb, srb, mb = measure(a.b)
diff = {k: round(mb[k] - ma[k], 2) for k in ("lufs", "peak_dbfs", "true_peak_dbtp", "rms_dbfs", "crest_db",
                                             "spectral_centroid_hz") if ma.get(k) is not None and mb.get(k) is not None}
diff["band_share_db"] = {k: round(mb["band_share_db"][k] - ma["band_share_db"][k], 2) for k in ma["band_share_db"]}
target = min(ma["lufs"], mb["lufs"])
out_dir = a.out_dir or os.path.dirname(os.path.abspath(a.a))
matched = {}
for label, x, sr, m, src in (("A", xa, sra, ma, a.a), ("B", xb, srb, mb, a.b)):
    g = 10 ** ((target - m["lufs"]) / 20.0)
    dst = os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0] + " (matched %s).wav" % label)
    if not os.path.exists(dst):
        sf.write(dst, x * g, sr, subtype="PCM_24")
    matched[label] = {"file": dst, "gain_db": round(20 * math.log10(g), 2)}
print(json.dumps({"A": ma, "B": mb, "B_minus_A": diff, "loudness_matched_to_lufs": target, "matched": matched,
                  "note": "measurements only; choose by listening to the matched files"}, indent=1))
