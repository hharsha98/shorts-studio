#!/usr/bin/env python3
"""voice_pitch.py - median pitch (F0) of stretches of a narration wav. NEEDS numpy.

Only MoneyPrinterTurbo's virtual environment has numpy, so studio/voice_take.py runs this file as a subprocess:

    MoneyPrinterTurbo/.venv/bin/python studio/voice_pitch.py narration.wav --spans "[[0, 4.2], [4.2, 9.0]]"

and reads one JSON line from stdout:  {"sr": 24000, "segments": [{"start", "end", "f0_med", "voiced_frames"}, ...]}.
f0_med is null when a stretch has no voiced frames. Without --spans the whole file is one stretch.

The tracker is the YIN method (de Cheveigne and Kawahara, 2002), ported from the audio expert's check
(work/_expert/audio/pitchlib.py): 40 ms windows every 10 ms, pitch searched between 60 and 400 Hz, silent frames
(below -45 dBFS) skipped, and frames that are probably octave errors (more than 1.9x or less than 0.52x the stretch's
own median) dropped before the median is taken.
"""

from __future__ import annotations

import argparse
import json
import sys
import wave

import numpy as np

FMIN, FMAX = 60.0, 400.0
SILENCE_DBFS = -45.0
YIN_THRESHOLD = 0.15


def read_wav(path):
    """(samples as floats in -1..1, sample rate) of a 16-bit PCM wav; several channels are averaged."""
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise SystemExit(f"{path}: need a 16-bit PCM wav")
        sr, channels = w.getframerate(), w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, sr


def frames(x, size, hop):
    n = 1 + max(0, (len(x) - size) // hop)
    idx = np.arange(size)[None, :] + hop * np.arange(n)[:, None]
    return x[idx]


def yin(x, sr, threshold=YIN_THRESHOLD):
    """(times, f0) with f0 = nan for unvoiced frames. Vectorised YIN; 40 ms windows, 10 ms hop."""
    hop, win = round(sr * 0.010), round(sr * 0.040)
    tmin, tmax = int(sr / FMAX), int(sr / FMIN)
    size = win + tmax
    if len(x) < size:
        return np.array([]), np.array([])
    fr = frames(x, size, hop)
    n = fr.shape[0]
    nfft = 1 << int(np.ceil(np.log2(size + win)))
    a = np.fft.rfft(fr[:, :win], nfft)
    b = np.fft.rfft(fr, nfft)
    r = np.fft.irfft(np.conj(a) * b, nfft)[:, : tmax + 1]
    sq = np.concatenate([np.zeros((n, 1)), np.cumsum(fr ** 2, axis=1)], axis=1)
    e0 = sq[:, win][:, None]
    taus = np.arange(tmax + 1)
    etau = sq[:, taus + win] - sq[:, taus]
    d = e0 + etau - 2 * r
    d[:, 0] = 0
    cs = np.cumsum(d[:, 1:], axis=1)
    cmnd = np.ones_like(d)
    cmnd[:, 1:] = d[:, 1:] * taus[1:] / np.maximum(cs, 1e-12)
    f0 = np.full(n, np.nan)
    rms = np.sqrt((fr[:, :win] ** 2).mean(axis=1))
    for i in range(n):
        if rms[i] < 10 ** (SILENCE_DBFS / 20):
            continue
        c = cmnd[i]
        below = np.nonzero(c[tmin:tmax] < threshold)[0]
        if not below.size:
            continue
        t = below[0] + tmin
        while t + 1 < tmax and c[t + 1] < c[t]:
            t += 1
        if 1 <= t < tmax:
            y0, y1, y2 = c[t - 1], c[t], c[t + 1]
            den = y0 - 2 * y1 + y2
            shift = 0.5 * (y0 - y2) / den if den != 0 else 0.0
            tt = t + max(-1, min(1, shift))
        else:
            tt = t
        f0[i] = sr / tt
    times = (np.arange(n) * hop + win / 2) / sr
    return times, f0


def clean_octaves(f0, ref):
    out = f0.copy()
    out[(out > ref * 1.9) | (out < ref * 0.52)] = np.nan
    return out


def segment_f0(x, sr, start, end):
    """{"f0_med", "voiced_frames"} for x[start:end] (seconds); f0_med is None without voiced frames."""
    seg = x[max(0, int(start * sr)): max(0, int(end * sr))]
    _t, f0 = yin(seg, sr)
    voiced = f0[~np.isnan(f0)]
    if voiced.size:
        f0 = clean_octaves(f0, float(np.median(voiced)))
        voiced = f0[~np.isnan(f0)]
    return {"start": round(start, 3), "end": round(end, 3),
            "f0_med": round(float(np.median(voiced)), 2) if voiced.size else None, "voiced_frames": int(voiced.size)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="median pitch of stretches of a wav (needs numpy)")
    ap.add_argument("wav")
    ap.add_argument("--spans", help='JSON list of [start, end] seconds; default: the whole file')
    args = ap.parse_args(argv)
    x, sr = read_wav(args.wav)
    spans = json.loads(args.spans) if args.spans else [[0.0, len(x) / sr]]
    print(json.dumps({"sr": sr, "segments": [segment_f0(x, sr, float(a), float(b)) for a, b in spans]}))


if __name__ == "__main__":
    sys.exit(main())
