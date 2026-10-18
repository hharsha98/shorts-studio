#!/usr/bin/env python3
"""Build the interview Shorts: narration -> timeline and Remotion props -> render -> audio mix -> checks -> artifacts.

Run with the Python that has kokoro, edge-tts and faster-whisper installed (see README.md), for example:
  ~/.venvs/kokoro/bin/python tools/build.py all
  ~/.venvs/kokoro/bin/python tools/build.py voice short2 --lang de
  ~/.venvs/kokoro/bin/python tools/build.py check short1 --lang en
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
WORK = ROOT / "work"
VIDEO = ROOT / "video"
ARTIFACTS = Path("/opt/cursor/artifacts")

SR = 24000
FPS = 30
EN_VOICE = "af_heart"  # Kokoro-82M, the pipeline's English narrator
DE_VOICE = "de-DE-KatjaNeural"  # Microsoft neural voice via the Edge read-aloud service (edge-tts)
DE_RATE = "+7%"  # Katja's default pace made the German cuts 63-67 s; 7 % faster keeps them under a minute and still sounds natural
PAUSE_SAME_SCENE = 0.28
PAUSE_NEW_SCENE = 0.50
LEAD_IN = 0.15
END_HOLD = 2.5
SCENE_LEAD = 0.12
SHORTS = ("short1", "short2", "short3")
LANGS = ("en", "de")


# ---------------------------------------------------------------------------------------------------- small helpers

def run(cmd: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout[-4000:] + proc.stderr[-4000:])
        raise SystemExit(f"command failed ({proc.returncode}): {' '.join(cmd[:6])} ...")
    return proc.stdout


def load_script(short: str) -> dict:
    return json.loads((SCRIPTS / f"{short}.json").read_text(encoding="utf-8"))


def out_dir(short: str, lang: str) -> Path:
    d = WORK / short / lang
    d.mkdir(parents=True, exist_ok=True)
    return d


def decode_audio(path: Path, sr: int = SR) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def write_wav(path: Path, audio: np.ndarray, sr: int = SR) -> None:
    pcm = np.clip(audio, -1.0, 1.0)
    pcm = (pcm * 32767.0).round().astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def norm(word: str) -> str:
    return re.sub(r"[^0-9a-zäöüßéèàáâç]", "", word.lower())


# ---------------------------------------------------------------------------------------------------- speech

def synth_en(texts: list[str]) -> list[tuple[np.ndarray, list[tuple[str, float, float]]]]:
    import torch
    from kokoro import KPipeline

    pipe = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
    out = []
    for text in texts:
        torch.manual_seed(0)
        parts, toks, offset = [], [], 0.0
        for result in pipe(text, voice=EN_VOICE, speed=1.0):
            audio = result.audio.detach().cpu().numpy().reshape(-1).astype(np.float32)
            for tk in result.tokens or []:
                if tk.start_ts is not None and tk.end_ts is not None:
                    toks.append((tk.text, offset + float(tk.start_ts), offset + float(tk.end_ts)))
            parts.append(audio)
            offset += len(audio) / SR
        out.append((np.concatenate(parts), toks))
    return out


async def _edge_line(text: str, voice: str, mp3: Path) -> list[tuple[str, float, float]]:
    import edge_tts

    words: list[tuple[str, float, float]] = []
    comm = edge_tts.Communicate(text, voice, rate=DE_RATE, boundary="WordBoundary")
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append((chunk["text"], start, start + chunk["duration"] / 1e7))
    return words


def synth_de(texts: list[str], voice: str, tmp: Path) -> list[tuple[np.ndarray, list[tuple[str, float, float]]]]:
    out = []
    for i, text in enumerate(texts):
        mp3 = tmp / f"line{i:02d}.mp3"
        for attempt in range(4):
            try:
                words = asyncio.run(_edge_line(text, voice, mp3))
                break
            except Exception as exc:  # network hiccups: retry with a pause
                if attempt == 3:
                    raise
                print(f"  edge-tts retry {attempt + 1}: {exc}")
                import time

                time.sleep(2 * (attempt + 1))
        out.append((decode_audio(mp3), words))
    return out


def trim(audio: np.ndarray, toks: list[tuple[str, float, float]], level: float = 0.006, keep: float = 0.04):
    loud = np.flatnonzero(np.abs(audio) >= level)
    if loud.size == 0:
        return audio, toks
    a = max(0, int(loud[0]) - int(keep * SR))
    b = min(len(audio), int(loud[-1]) + 1 + int(keep * SR))
    shift, dur = a / SR, (b - a) / SR
    return audio[a:b], [(t, min(dur, max(0.0, s - shift)), min(dur, max(0.0, e - shift))) for t, s, e in toks]


def align(display: str, toks: list[tuple[str, float, float]], duration: float) -> tuple[list[dict], bool]:
    """Times for the words of the display text from the speech engine's tokens (which may split or spell words differently)."""
    words = display.split()
    split_toks: list[tuple[str, float, float]] = []
    for t, s, e in toks:
        parts = t.split()
        if len(parts) <= 1:
            split_toks.append((t, s, e))
            continue
        # one boundary for several words ("An 16 Maschinen"): share its time by letter count
        weights = [max(1, len(norm(p))) for p in parts]
        total_w, acc_t = sum(weights), s
        for p, wgt in zip(parts, weights):
            d = (e - s) * wgt / total_w
            split_toks.append((p, acc_t, acc_t + d))
            acc_t += d
    stream = [(norm(t), s, e) for t, s, e in split_toks if norm(t)]
    out: list[dict] = []
    j = 0
    ok = True
    for w in words:
        target = norm(w)
        if not target:
            continue
        acc, s0, e0 = "", None, None
        while j < len(stream) and acc != target:
            n, s, e = stream[j]
            if not target.startswith(acc + n):
                break
            acc += n
            s0 = s if s0 is None else s0
            e0 = e
            j += 1
        if acc != target or s0 is None:
            ok = False
            break
        out.append({"text": w, "start": round(s0, 3), "end": round(max(e0, s0 + 0.05), 3)})
    if ok and len(out) == len([w for w in words if norm(w)]):
        return out, True
    # proportional fallback by character count (reported, so the line can be fixed)
    chars = [max(1, len(norm(w))) for w in words]
    total = sum(chars)
    t, res = 0.05, []
    for w, c in zip(words, chars):
        d = (duration - 0.1) * c / total
        res.append({"text": w, "start": round(t, 3), "end": round(t + d, 3)})
        t += d
    return res, False


def voice_short(short: str, lang: str, force: bool = False) -> dict:
    script = load_script(short)
    lines = script[lang]["lines"]
    say = [ln.get("say", ln["text"]) for ln in lines]
    engine = f"kokoro:{EN_VOICE}" if lang == "en" else f"edge:{DE_VOICE}@{DE_RATE}"
    timing = [PAUSE_SAME_SCENE, PAUSE_NEW_SCENE, LEAD_IN, END_HOLD]
    key = hashlib.sha256(
        json.dumps({"engine": engine, "say": say, "text": [ln["text"] for ln in lines], "scenes": [ln["scene"] for ln in lines], "timing": timing}, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    d = out_dir(short, lang)
    timeline_path = d / "timeline.json"
    if not force and timeline_path.exists():
        cached = json.loads(timeline_path.read_text())
        if cached.get("key") == key and (d / "narration.wav").exists():
            print(f"{short}/{lang}: narration cached ({cached['audioSeconds']:.1f} s)")
            return cached
    print(f"{short}/{lang}: voicing {len(lines)} lines with {engine}")
    tmp = d / "voice"
    tmp.mkdir(exist_ok=True)
    results = synth_en(say) if lang == "en" else synth_de(say, DE_VOICE, tmp)

    pieces: list[np.ndarray] = [np.zeros(int(LEAD_IN * SR), np.float32)]
    t = LEAD_IN
    out_lines = []
    warnings = []
    for i, (ln, (audio, toks)) in enumerate(zip(lines, results)):
        audio, toks = trim(audio, toks)
        dur = len(audio) / SR
        words, aligned = align(ln["text"], toks, dur)
        if not aligned:
            warnings.append(f"line {i + 1}: word timing fell back to proportional ({ln['text'][:50]}...)")
        out_lines.append(
            {
                "i": i,
                "scene": ln["scene"],
                "text": ln["text"],
                "start": round(t, 3),
                "end": round(t + dur, 3),
                "words": [{"text": w["text"], "start": round(t + w["start"], 3), "end": round(t + w["end"], 3)} for w in words],
                "cues": ln.get("cues", {}),
            }
        )
        pieces.append(audio)
        t += dur
        if i + 1 < len(lines):
            gap = PAUSE_NEW_SCENE if lines[i + 1]["scene"] != ln["scene"] else PAUSE_SAME_SCENE
            pieces.append(np.zeros(int(gap * SR), np.float32))
            t += gap
    narration = np.concatenate(pieces)
    write_wav(d / "narration.wav", narration)
    timeline = {
        "key": key,
        "engine": engine,
        "audioSeconds": round(len(narration) / SR, 3),
        "totalSeconds": round(len(narration) / SR + END_HOLD, 3),
        "lines": out_lines,
        "warnings": warnings,
    }
    timeline_path.write_text(json.dumps(timeline, ensure_ascii=False, indent=1))
    for w in warnings:
        print("  WARNING", w)
    print(f"  narration {timeline['audioSeconds']:.1f} s, video {timeline['totalSeconds']:.1f} s")
    return timeline


# ---------------------------------------------------------------------------------------------------- props

FUNCTION_WORDS = {
    "a", "an", "the", "at", "to", "of", "in", "on", "for", "from", "with", "and", "or", "by", "as", "its", "their", "your", "each", "every", "no",
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "und", "oder", "mit", "von", "zu", "zur", "zum",
    "im", "in", "am", "an", "auf", "für", "bei", "aus", "ihre", "ihren", "ihrer", "jede", "jeder", "jedes", "nur",
}


def chunk_captions(words: list[dict], max_chars: int = 36, max_words: int = 7, max_gap: float = 0.35) -> list[dict]:
    """Phrases for the caption panel: break at sentence ends, pauses and commas; never end a phrase on 'the', 'mit', ..."""
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    text = lambda ws: " ".join(x["text"] for x in ws)
    for w in words:
        if cur:
            prev = cur[-1]
            ends_sentence = prev["text"][-1] in ".!?:;"
            soft_break = prev["text"][-1] == "," and len(text(cur)) >= 14
            if ends_sentence or soft_break or (w["start"] - prev["end"]) > max_gap:
                chunks.append(cur)
                cur = []
            elif len(text(cur + [w])) > max_chars or len(cur) >= max_words:
                carry: list[dict] = []
                while len(cur) > 1 and norm(cur[-1]["text"]) in FUNCTION_WORDS and cur[-1]["text"][-1] not in ",.:;!?":
                    carry.insert(0, cur.pop())
                chunks.append(cur)
                cur = carry
        cur.append(w)
    if cur:
        chunks.append(cur)
    # a lonely last word joins the chunk before it when that still fits
    merged: list[list[dict]] = []
    for c in chunks:
        if merged and len(c) == 1 and len(" ".join(x["text"] for x in merged[-1] + c)) <= max_chars + 8 and merged[-1][-1]["text"][-1] not in ".!?:":
            merged[-1] = merged[-1] + c
        else:
            merged.append(c)
    return [{"start": c[0]["start"], "end": c[-1]["end"], "words": c} for c in merged]


def build_props(short: str, lang: str, timeline: dict, voice: bool = True) -> Path:
    script = load_script(short)
    lines = timeline["lines"]
    total = timeline["totalSeconds"]
    scenes = []
    for ln in lines:
        if scenes and scenes[-1]["key"] == ln["scene"]:
            continue
        scenes.append({"key": ln["scene"], "start": 0.0 if not scenes else max(0.0, ln["start"] - SCENE_LEAD)})
    for a, b in zip(scenes, scenes[1:]):
        a["end"] = b["start"]
    scenes[-1]["end"] = total
    cues: dict[str, float] = {}
    for ln in lines:
        for name, word in ln.get("cues", {}).items():
            target = norm(word)
            hit = next((w for w in ln["words"] if norm(w["text"]).startswith(target)), None)
            if hit is None:
                raise SystemExit(f"{short}/{lang}: cue {name!r} word {word!r} not found in line {ln['i'] + 1}: {ln['text']}")
            cues[name] = round(max(0.0, hit["start"] - 0.05), 3)
    words = [w for ln in lines for w in ln["words"]]
    props = {
        "lang": lang,
        "voice": voice,
        "durationSeconds": total,
        "labels": script[lang]["labels"],
        "scenes": scenes,
        "cues": cues,
        "captions": chunk_captions(words),
    }
    path = out_dir(short, lang) / ("props.json" if voice else "props-silent.json")
    path.write_text(json.dumps(props, ensure_ascii=False, indent=1))
    return path


# ---------------------------------------------------------------------------------------------------- music

def make_music(path: Path, seconds: float = 80.0, sr: int = 48000) -> None:
    """A quiet, slow pad written for these videos (own composition: no licence needed). D major, four chords, 4 s each."""
    if path.exists():
        return
    rng = np.random.default_rng(7)
    n = int(seconds * sr)
    t = np.arange(n) / sr
    midi = lambda m: 440.0 * 2 ** ((m - 69) / 12)
    chords = [[50, 57, 61, 66], [47, 54, 57, 62], [43, 50, 54, 59], [45, 52, 57, 59]]  # Dmaj7, Bm7, Gmaj7, Asus2 (add9)
    bar = 4.0
    out = np.zeros((n, 2), np.float32)
    for k in range(int(seconds / bar) + 2):
        notes = chords[k % 4]
        t0 = k * bar - 1.0
        env_t = t - t0
        env = np.clip(env_t / 1.6, 0, 1) * np.clip((bar + 2.0 - env_t) / 1.6, 0, 1)
        env = np.sin(env * np.pi / 2) ** 2
        mask = env > 0
        if not mask.any():
            continue
        for j, m in enumerate(notes):
            f = midi(m)
            for side, detune in ((0, -0.0012), (1, 0.0012)):
                ph = rng.uniform(0, 2 * np.pi)
                wave_ = np.sin(2 * np.pi * f * (1 + detune) * t[mask] + ph) + 0.18 * np.sin(4 * np.pi * f * t[mask] + ph) + 0.06 * np.sin(6 * np.pi * f * t[mask])
                out[mask, side] += (0.16 / (1 + 0.25 * j)) * env[mask] * wave_.astype(np.float32)
    # gentle one-pole low-pass (applied in the frequency domain) and a soft room (exponential noise tail) for warmth
    freqs = np.fft.rfftfreq(n, 1 / sr)
    lowpass = 1.0 / (1.0 + 1j * freqs / 1800.0)
    out = np.stack([np.fft.irfft(np.fft.rfft(out[:, c]) * lowpass, n) for c in range(2)], axis=1).astype(np.float32)
    ir_len = int(1.8 * sr)
    ir = rng.standard_normal((ir_len, 2)).astype(np.float32) * np.exp(-np.arange(ir_len) / (0.45 * sr))[:, None]
    ir[0] = 1.0
    wet = np.stack([np.fft.irfft(np.fft.rfft(out[:, c], n + ir_len) * np.fft.rfft(ir[:, c], n + ir_len))[:n] for c in range(2)], axis=1)
    mix = 0.7 * out + 0.3 * wet / (np.abs(wet).max() + 1e-9) * np.abs(out).max()
    mix /= np.abs(mix).max() + 1e-9
    mix *= 0.5
    pcm = (mix * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


# ---------------------------------------------------------------------------------------------------- render and mix

def render(short: str, lang: str, props: Path, out: Path) -> None:
    print(f"{short}/{lang}: rendering {out.name}")
    run(
        [
            "npx", "remotion", "render", "src/index.ts", "InterviewShort", str(out),
            f"--props={props}", "--codec=h264", "--crf=18", "--pixel-format=yuv420p", "--concurrency=4", "--log=error",
        ],
        cwd=VIDEO,
    )


def mix(short: str, lang: str, timeline: dict, music: Path, out: Path) -> None:
    d = out_dir(short, lang)
    total = timeline["totalSeconds"]
    fade = total - 2.6
    filt = (
        f"[0:a]aresample=48000,aformat=channel_layouts=mono,apad=whole_dur={total},asplit=2[v][sc];"
        f"[1:a]atrim=0:{total},asetpts=N/SR/TB,volume=0.11,afade=t=in:st=0:d=1.2,afade=t=out:st={fade:.2f}:d=2.5[m];"
        f"[m][sc]sidechaincompress=threshold=0.02:ratio=5:attack=25:release=450[md];"
        f"[v]pan=stereo|c0=c0|c1=c0[vs];"
        f"[vs][md]amix=inputs=2:normalize=0:duration=first,loudnorm=I=-16:TP=-1.5:LRA=11[out]"
    )
    run(["ffmpeg", "-y", "-v", "error", "-i", str(d / "narration.wav"), "-i", str(music), "-filter_complex", filt, "-map", "[out]", "-ar", "48000", "-ac", "2", str(out)])


def mux(video: Path, audio: Path, out: Path) -> None:
    run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)])


def faststart(video: Path, out: Path) -> None:
    run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-map", "0:v:0", "-c:v", "copy", "-movflags", "+faststart", str(out)])


# ---------------------------------------------------------------------------------------------------- checks

NUMBER_WORDS = {
    "en": {"zero": "0", "five": "5", "eight": "8", "twelve": "12", "fifteen": "15", "sixteen": "16", "twenty": "20", "thirty": "30"},
    "de": {"null": "0", "fünf": "5", "acht": "8", "zwölf": "12", "fünfzehn": "15", "sechzehn": "16", "zwanzig": "20", "dreißig": "30"},
}

_whisper = None


def transcribe(path: Path, lang: str) -> list[tuple[str, float, float]]:
    global _whisper
    from faster_whisper import WhisperModel

    if _whisper is None:
        _whisper = WhisperModel("small", device="cpu", compute_type="int8")
    audio = decode_audio(path, 16000)
    # without conditioning on earlier text, one misheard stretch cannot snowball into a repetition loop ("a a a a ...")
    segments, _ = _whisper.transcribe(audio, language=lang, beam_size=5, word_timestamps=True, condition_on_previous_text=False)
    return [(w.word.strip(), w.start, w.end) for s in segments for w in (s.words or [])]


def check_voice(short: str, lang: str) -> list[dict]:
    d = out_dir(short, lang)
    timeline = json.loads((d / "timeline.json").read_text())
    heard = transcribe(d / "narration.wav", lang)
    nums = NUMBER_WORDS[lang]
    simple = lambda w: nums.get(norm(w), norm(w))
    report = []
    for ln in timeline["lines"]:
        said = [simple(w) for w, s, e in heard if ln["start"] - 0.25 <= (s + e) / 2 <= ln["end"] + 0.25]
        want = [simple(w["text"]) for w in ln["words"]]
        said, want = [w for w in said if w], [w for w in want if w]
        ratio = difflib.SequenceMatcher(a=want, b=said).ratio()
        diffs = [
            (" ".join(want[i1:i2]), " ".join(said[j1:j2]))
            for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=want, b=said).get_opcodes()
            if tag != "equal"
        ]
        report.append({"line": ln["i"] + 1, "ratio": round(ratio, 3), "diffs": diffs, "text": ln["text"]})
    (d / "voice-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    for r in report:
        flag = "ok " if r["ratio"] >= 0.92 else "CHECK"
        print(f"  {flag} line {r['line']:2d} {r['ratio']:.2f} {r['diffs'] if r['diffs'] else ''}")
    return report


def probe(path: Path) -> dict:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels", "-of", "json", str(path)])
    return json.loads(out)


def contact_sheet(video: Path, out: Path, every: float = 2.0, cols: int = 6) -> None:
    run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf", f"fps=1/{every},scale=270:-1,tile={cols}x5:padding=6:margin=6:color=0x222222", "-frames:v", "1", "-update", "1", str(out)])


def frames_at(video: Path, times: list[float], out_dir_: Path, prefix: str) -> list[Path]:
    out_dir_.mkdir(parents=True, exist_ok=True)
    paths = []
    for t in times:
        p = out_dir_ / f"{prefix}-{t:05.1f}.png"
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", str(p)])
        paths.append(p)
    return paths


# ---------------------------------------------------------------------------------------------------- pipeline

def build_one(short: str, lang: str, force_voice: bool = False, deliver: bool = True) -> dict:
    script = load_script(short)
    d = out_dir(short, lang)
    timeline = voice_short(short, lang, force=force_voice)
    props = build_props(short, lang, timeline, voice=True)
    props_silent = build_props(short, lang, timeline, voice=False)
    music = WORK / "music-pad.wav"
    make_music(music)
    render(short, lang, props, d / "video.mp4")
    render(short, lang, props_silent, d / "video-silent.mp4")
    mix(short, lang, timeline, music, d / "mix.wav")
    n = script["index"]
    final = d / f"rotpunkt_short_{n}_{lang}.mp4"
    silent = d / f"rotpunkt_short_{n}_{lang}_silent.mp4"
    mux(d / "video.mp4", d / "mix.wav", final)
    faststart(d / "video-silent.mp4", silent)
    contact_sheet(final, d / "sheet.png")
    info = probe(final)
    print(f"{short}/{lang}: {float(info['format']['duration']):.2f} s -> {final.name}")
    if deliver:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        shutil.copy2(final, ARTIFACTS / final.name)
        shutil.copy2(silent, ARTIFACTS / silent.name)
    return info


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["voice", "props", "render", "check", "all"])
    ap.add_argument("short", nargs="?", default=None, help="short1, short2 or short3 (default: all three)")
    ap.add_argument("--lang", default=None, help="en or de (default: both)")
    ap.add_argument("--force-voice", action="store_true", help="re-voice even if the narration is cached")
    ap.add_argument("--no-deliver", action="store_true", help="do not copy the finished files to /opt/cursor/artifacts")
    args = ap.parse_args(argv)
    shorts = [args.short] if args.short else list(SHORTS)
    langs = [args.lang] if args.lang else list(LANGS)
    for short in shorts:
        for lang in langs:
            if args.command == "voice":
                voice_short(short, lang, force=args.force_voice)
            elif args.command == "props":
                tl = voice_short(short, lang)
                print(build_props(short, lang, tl), build_props(short, lang, tl, voice=False))
            elif args.command == "check":
                check_voice(short, lang)
            elif args.command in ("render", "all"):
                build_one(short, lang, force_voice=args.force_voice, deliver=not args.no_deliver)
                if args.command == "all":
                    check_voice(short, lang)
    return 0


if __name__ == "__main__":
    sys.exit(main())
