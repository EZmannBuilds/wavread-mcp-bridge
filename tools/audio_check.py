#!/usr/bin/env python3
"""Offline checks for a rendered or recorded file (the owner's Phase 2, section 8): duration, sample rate, channels, peak,
true peak (4x oversampled), integrated LUFS (ITU-R BS.1770 via pyloudnorm), silence, clipping, and loop continuity
(the jump between the last and first samples against the file's typical sample-to-sample step).
run: uv run -q --with numpy --with soundfile --with pyloudnorm --with scipy python tools/audio_check.py FILE [FILE...]
     [--target-lufs -15.4] [--loop]
Prints one JSON object per file. Never changes a file.
"""
import argparse, json, math, sys
import numpy as np, soundfile as sf, pyloudnorm as pyln
from scipy.signal import resample_poly

ap = argparse.ArgumentParser()
ap.add_argument("files", nargs="+")
ap.add_argument("--target-lufs", type=float)
ap.add_argument("--loop", action="store_true", help="also check the loop seam")
a = ap.parse_args()


def db(x):
    return round(20 * math.log10(x), 2) if x > 0 else None


for f in a.files:
    x, sr = sf.read(f, always_2d=True)
    info = sf.info(f)
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    tp = float(np.max(np.abs(resample_poly(x, 4, 1, axis=0)))) if x.size else 0.0
    out = {"file": f, "seconds": round(len(x) / sr, 4), "sample_rate": sr, "channels": x.shape[1],
           "subtype": info.subtype, "peak_dbfs": db(peak), "true_peak_dbtp": db(tp),
           "clipped_samples": int(np.sum(np.abs(x) >= 0.9999)), "silent": peak < 10 ** (-70 / 20)}
    if len(x) > sr * 0.4:
        out["lufs_integrated"] = round(float(pyln.Meter(sr).integrated_loudness(x)), 2)
        if a.target_lufs is not None:
            out["lufs_off_target"] = round(out["lufs_integrated"] - a.target_lufs, 2)
    # per-channel and per-second RMS: shows silent tracks or a dead side
    out["rms_dbfs_per_channel"] = [db(float(np.sqrt(np.mean(x[:, c] ** 2)))) for c in range(x.shape[1])]
    if a.loop and len(x) > 2:
        steps = np.abs(np.diff(x, axis=0))
        typical = float(np.percentile(steps, 99)) or 1e-9
        seam = float(np.max(np.abs(x[0] - x[-1])))
        out["loop_seam_jump"] = round(seam, 6)
        out["loop_seam_ratio_to_p99_step"] = round(seam / typical, 2)
        out["loop_seam_ok"] = seam <= typical * 2.0
    print(json.dumps(out))
