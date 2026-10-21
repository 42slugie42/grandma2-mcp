"""Song analysis (tempo, beats, bars, sections, energy) and synced playback."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np

HOP = 512


def _norm(x: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(x, 5), np.percentile(x, 95)
    if hi - lo < 1e-9:
        return np.zeros_like(x)
    return np.clip((x - lo) / (hi - lo), 0, 1)


def _env_at(env: np.ndarray, times: np.ndarray, sr: int) -> float:
    frames = np.round(times * sr / HOP).astype(int)
    frames = frames[(frames >= 0) & (frames < len(env))]
    if not len(frames):
        return 0.0
    # tolerate +-2 frames of jitter
    return float(np.mean([env[max(f - 2, 0):f + 3].max() for f in frames]))


def _beat_grid(tracked: np.ndarray, bpm: float, onset_env: np.ndarray, bass_onset: np.ndarray,
               sr: int, duration: float) -> tuple[np.ndarray, float, float]:
    """Fit a constant-tempo grid to the tracked beats and put it on the kicks.

    Returns (beat_times, bpm, fit) where fit is the share of tracked beats that lie
    within 70 ms of the grid. With a poor fit (live/rubato music) the tracked
    beats are returned unchanged."""
    if len(tracked) < 8 or bpm <= 0:
        return tracked, bpm, 0.0
    env = _norm(onset_env) + 1.5 * _norm(bass_onset)
    fps = sr / HOP
    p0 = 60.0 / bpm
    # comb search: which constant period/phase puts the most (bass-weighted) onsets on the grid?
    best = (-1.0, p0, 0.0)
    for period in np.arange(p0 * 0.97, p0 * 1.03, 0.0002):
        grid_f = np.arange(0, duration, period) * fps
        for phase in np.arange(0, period, 1 / fps):
            f = np.round(grid_f + phase * fps).astype(int)
            f = f[f < len(env)]
            score = float(env[f].mean())
            if score > best[0]:
                best = (score, period, phase)
    _, period, phase = best
    # double-time lock (e.g. 186 instead of 93): halve fast tempos and keep the
    # half of the beats that carries the kicks
    if 60.0 / period > 160:
        bass = _norm(bass_onset)
        candidates = [phase, phase + period]
        scores = [_env_at(bass, np.arange(p, duration, 2 * period), sr) for p in candidates]
        phase, period = candidates[int(np.argmax(scores))], 2 * period
    grid = np.arange(phase, duration, period)
    # fit: share of tracked beats on the grid (or exactly between, i.e. off-beat locked)
    rel = ((tracked - phase) / period) % 1.0
    on_beat = np.minimum(rel, 1 - rel) * period < 0.07
    off_beat = np.abs(rel - 0.5) * period < 0.07
    fit = float(np.mean(on_beat | off_beat))
    if fit < 0.6:
        return tracked, bpm, fit
    return grid, 60.0 / period, fit


def analyze(path: str, sections: int | None = None) -> dict:
    """Analyse a song file and return tempo, bars, sections and accents."""
    import librosa

    y, sr = librosa.load(path, sr=22050, mono=True)
    duration = float(len(y) / sr)

    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP)
    bass_onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP, fmax=200, n_mels=16)
    tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr, hop_length=HOP)
    tracked = librosa.frames_to_time(beat_frames, sr=sr, hop_length=HOP)
    beat_times, bpm, grid_fit = _beat_grid(tracked, float(np.atleast_1d(tempo)[0]),
                                           onset_env, bass_onset, sr, duration)
    beat_frames = librosa.time_to_frames(beat_times, sr=sr, hop_length=HOP)

    rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=HOP)[0]
    # bass energy (< ~150 Hz) for kick/drop detection
    S = np.abs(librosa.stft(y, hop_length=HOP))
    freqs = librosa.fft_frequencies(sr=sr)
    bass = S[freqs < 150].mean(axis=0)
    n = min(len(rms), len(centroid), len(bass), len(onset_env))
    rms, centroid, bass, onset_env = rms[:n], centroid[:n], bass[:n], onset_env[:n]
    energy_n, bright_n, bass_n = _norm(rms), _norm(centroid), _norm(bass)

    # downbeat phase: the beat offset (0..3) whose beats carry the most bass onsets
    phase = 0
    if len(beat_times) >= 8:
        score = [_env_at(bass_onset, beat_times[p::4], sr) for p in range(4)]
        phase = int(np.argmax(score))
    downbeats = beat_times[phase::4]

    # per-bar features
    bars = []
    for i, start in enumerate(downbeats):
        end = downbeats[i + 1] if i + 1 < len(downbeats) else duration
        a, b = librosa.time_to_frames([start, end], sr=sr, hop_length=HOP)
        b = max(b, a + 1)
        bars.append({
            "bar": i + 1,
            "t": round(float(start), 3),
            "energy": round(float(energy_n[a:b].mean()), 2),
            "bass": round(float(bass_n[a:b].mean()), 2),
            "bright": round(float(bright_n[a:b].mean()), 2),
        })

    # structural sections from timbre + harmony, snapped to bar starts
    if sections is None:
        sections = int(np.clip(round(duration / 25), 4, 12))
    mfcc = librosa.feature.mfcc(y=y, sr=sr, hop_length=HOP, n_mfcc=13)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=HOP)
    m = min(mfcc.shape[1], chroma.shape[1])
    feats = np.vstack([librosa.util.normalize(mfcc[:, :m], axis=1), chroma[:, :m]])
    # sync features to bars so section boundaries fall on downbeats
    bar_frames = librosa.time_to_frames(downbeats, sr=sr, hop_length=HOP)
    bar_frames = bar_frames[bar_frames < m]
    sync = librosa.util.sync(feats, bar_frames, aggregate=np.median)
    k = int(min(sections, max(2, sync.shape[1] - 1)))
    bounds_idx = librosa.segment.agglomerative(sync, k)
    # sync() puts the audio before the first bar into segment 0, so segment i starts at bar i-1
    sec_starts = sorted({float(downbeats[min(i - 1, len(downbeats) - 1)])
                         for i in bounds_idx if i > 1})
    sec_starts = [0.0] + [s for s in sec_starts if s > 2.0]
    if len(downbeats) and downbeats[0] > 2.0 and downbeats[0] not in sec_starts:
        sec_starts = sorted({*sec_starts, float(downbeats[0])})

    sec_list = []
    for i, s in enumerate(sec_starts):
        e = sec_starts[i + 1] if i + 1 < len(sec_starts) else duration
        a, b = librosa.time_to_frames([s, e], sr=sr, hop_length=HOP)
        b = max(b, a + 1)
        en = float(energy_n[a:b].mean())
        sec_list.append({
            "section": i + 1,
            "start": round(s, 3),
            "end": round(float(e), 3),
            "bars": int(sum(1 for d in downbeats if s <= d < e)),
            "energy": round(en, 2),
            "bass": round(float(bass_n[a:b].mean()), 2),
            "level": "low" if en < 0.35 else "mid" if en < 0.65 else "high",
        })
    for i in range(1, len(sec_list)):
        d = sec_list[i]["energy"] - sec_list[i - 1]["energy"]
        sec_list[i]["change"] = "drop/lift" if d > 0.2 else "breakdown" if d < -0.2 else "steady"

    # accents: bars where energy or bass jumps sharply (drops, hits)
    accents = []
    for i in range(1, len(bars)):
        jump = bars[i]["energy"] - bars[i - 1]["energy"]
        bjump = bars[i]["bass"] - bars[i - 1]["bass"]
        if jump > 0.3 or bjump > 0.35:
            accents.append({"t": bars[i]["t"], "bar": bars[i]["bar"],
                            "type": "drop" if bjump > 0.35 else "lift"})

    return {
        "file": str(Path(path).resolve()),
        "duration": round(duration, 2),
        "bpm": round(bpm, 2),
        "bpm_double": round(bpm * 2, 2),  # use for double-time chases / if the feel is faster
        "beat_period": round(60 / bpm, 4) if bpm else None,
        "grid_fit": round(grid_fit, 2),
        "first_beat": round(float(beat_times[0]), 3) if len(beat_times) else 0.0,
        "first_downbeat": round(float(downbeats[0]), 3) if len(downbeats) else 0.0,
        "beats": len(beat_times),
        "beat_times": [round(float(t), 3) for t in beat_times],
        "sections": sec_list,
        "accents": accents,
        "bars": bars,
    }


class Player:
    """Plays an audio file and fires a callback at given song times."""

    def __init__(self) -> None:
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.started_at: float | None = None
        self.path: str | None = None

    def play(self, path: str, events: list[tuple[float, callable]], start: float = 0.0) -> None:
        import sounddevice as sd
        import soundfile as sf

        self.stop()
        data, sr = sf.read(path, dtype="float32", always_2d=True)
        data = data[int(start * sr):]
        self.stop_event.clear()
        self.path = path

        def run():
            sd.play(data, sr)
            self.started_at = time.perf_counter() - start
            for t, fn in sorted(events, key=lambda e: e[0]):
                if t < start:
                    continue
                while not self.stop_event.is_set():
                    remaining = self.started_at + t - time.perf_counter()
                    if remaining <= 0:
                        break
                    time.sleep(min(remaining, 0.005))
                if self.stop_event.is_set():
                    return
                try:
                    fn()
                except Exception:
                    pass

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def position(self) -> float | None:
        if self.started_at is None:
            return None
        return time.perf_counter() - self.started_at

    def stop(self) -> None:
        import sounddevice as sd

        self.stop_event.set()
        sd.stop()
        self.started_at = None
