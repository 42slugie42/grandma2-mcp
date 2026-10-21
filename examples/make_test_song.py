"""Generate a 92 s test track at 128 BPM with a known structure.

    python examples/make_test_song.py testsong.wav

Structure (seconds): intro pad 0.5-15.5, build (kick + hats) 15.5-45.5,
breakdown 45.5-60.5, drop (kick + bass) 60.5-90.5. Useful to check that
song_analyze finds BPM, downbeats and sections correctly without a real song.
"""

import sys

import numpy as np
import soundfile as sf

sr = 22050
bpm = 128
beat = 60 / bpm


def tone(f, d, a=0.2):
    t = np.arange(int(d * sr)) / sr
    return a * np.sin(2 * np.pi * f * t)


def kick():
    t = np.arange(int(0.25 * sr)) / sr
    return 0.9 * np.sin(2 * np.pi * (50 + 80 * np.exp(-t * 30)) * t) * np.exp(-t * 12)


def hat():
    t = np.arange(int(0.05 * sr)) / sr
    return 0.2 * np.random.randn(len(t)) * np.exp(-t * 80)


parts = [("intro", 8, 0), ("build", 16, 1), ("break", 8, 0), ("drop", 16, 2)]
total = sum(p[1] for p in parts) * 4 * beat + 2
y = np.zeros(int(total * sr))
pos = 0.5
for name, bars, lvl in parts:
    for b in range(bars * 4):
        i = int(pos * sr)
        pad = tone(220 * (1 + (b // 4) % 2 * 0.25), beat, 0.08 if lvl == 0 else 0.05)
        y[i:i + len(pad)] += pad
        if lvl >= 1:
            k = kick()
            y[i:i + len(k)] += k
            h = hat()
            j = int((pos + beat / 2) * sr)
            y[j:j + len(h)] += h
        if lvl == 2:
            bs = tone(55, beat * 0.9, 0.4)
            y[i:i + len(bs)] += bs
        pos += beat

out = sys.argv[1] if len(sys.argv) > 1 else "testsong.wav"
sf.write(out, np.clip(y, -1, 1), sr)
print(f"written {out} ({total:.1f} s)")
