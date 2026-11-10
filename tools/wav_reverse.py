#!/usr/bin/env python3
"""Reverse an audio file into a NEW file (Live's API has no clip reverse; this is the alternate workflow: reverse
offline, then create_audio_clip from the new file). Keeps sample rate, channels and bit depth.
run: uv run -q --with numpy --with soundfile python tools/wav_reverse.py IN.wav OUT.wav
"""
import os, sys
import soundfile as sf
src, dst = sys.argv[1], sys.argv[2]
if os.path.exists(dst):
    sys.exit("refused: %s exists" % dst)
info = sf.info(src)
x, sr = sf.read(src, always_2d=True)
sf.write(dst, x[::-1], sr, subtype=info.subtype)
print({"written": dst, "seconds": round(len(x) / sr, 4), "sample_rate": sr, "subtype": info.subtype})
