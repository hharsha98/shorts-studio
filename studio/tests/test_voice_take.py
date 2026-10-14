"""Unit tests for studio/voice_take.py (the one-take voice) and the voice/loudness parts of studio/make_video.py.

No real VoiceStudio is used: FakeVoice makes "speech" out of sine bursts (one burst per word, silence between lines) and
answers the same questions the real backend does (speak, transcribe, pitch), so every gate runs on real audio arrays.

Run from /Users/harsha/shorts-studio:
    python3 -m unittest discover -s studio/tests -t .
"""

import array
import contextlib
import io
import json
import math
import re
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import make_video as mv  # noqa: E402
import voice_take as vt  # noqa: E402

SR = 24000
LINES = [
    "Your fridge does not make cold.",
    "It moves heat out of the box.",
    "A liquid called refrigerant soaks up the warmth.",
    "That is why the back feels warm.",
]
FULL = " ".join(LINES)


def tone(seconds, freq=150.0, amp=0.2, sr=SR):
    w = 2 * math.pi * freq / sr
    return array.array("h", (int(amp * 32767 * math.sin(w * i)) for i in range(round(seconds * sr))))


def gap(seconds, sr=SR):
    return vt.silence(seconds, sr)


def wav_bytes(samples, sr=SR):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(array.array("h", samples).tobytes())
    return buf.getvalue()


def burst_pitch(samples, sr=SR):
    """Pitch of a stretch made of sine bursts: split at silences, count rising zero crossings per burst, median."""
    bursts, current, quiet = [], [], 0
    for s in samples:
        quiet = quiet + 1 if abs(s) < 40 else 0
        if quiet > 300:
            if len(current) > 2000:
                bursts.append(current)
            current = []
        else:
            current.append(s)
    if len(current) > 2000:
        bursts.append(current)
    estimates = []
    for b in bursts:
        ups = [i for i in range(1, len(b)) if b[i - 1] < 0 <= b[i]]
        if len(ups) > 3:
            estimates.append(sr * (len(ups) - 1) / (ups[-1] - ups[0]))
    return sorted(estimates)[len(estimates) // 2] if estimates else None


class FakeVoice:
    """Stands in for VoiceStudioBackend. The knobs are functions of (take seed, line index) or (line index, patch seed)."""

    def __init__(self, lines=LINES, pitch=None, amp=None, pause=None, misheard=(), line_pitch=None, line_amp=None):
        self.lines = list(lines)
        self.pitch = pitch or (lambda seed, i: 150.0)
        self.amp = amp or (lambda seed, i: 0.2)
        self.pause = pause or (lambda seed, i: 0.8)
        self.misheard = set(misheard)  # (take seed, line) or ("patch", line, patch seed)
        self.line_pitch = line_pitch or (lambda i, seed: 150.0)
        self.line_amp = line_amp or (lambda i, seed: 0.2)
        self.synth_calls: list[tuple[str, int]] = []
        self.layout: list[dict] = []

    def synth(self, text, seed, instructions=None):
        self.synth_calls.append((text, seed))
        if text == vt.PROBE_TEXT:
            return wav_bytes(tone(0.2))
        if text == " ".join(self.lines):
            out, t, self.layout = gap(0.1), 0.1, []
            for i, line in enumerate(self.lines):
                words = line.split()
                for k, word in enumerate(words):
                    dur = 0.04 * len(word) + 0.12
                    out += tone(dur, self.pitch(seed, i), self.amp(seed, i))
                    self.layout.append({"start": t, "end": t + dur, "text": word})
                    t += dur
                    pause = (self.pause(seed, i) if i < len(self.lines) - 1 else 0.3) if k == len(words) - 1 else 0.08
                    out += gap(pause)
                    t += pause
            return wav_bytes(out)
        i = self.lines.index(text)
        out = gap(0.1)
        for word in text.split():
            out += tone(0.04 * len(word) + 0.12, self.line_pitch(i, seed), self.line_amp(i, seed)) + gap(0.08)
        return wav_bytes(out + gap(0.1))

    def transcribe_words(self, path):
        return [dict(w) for w in self.layout]

    def transcribe_text(self, path):
        name = Path(path).name
        line = re.match(r"line(\d+)\.wav", name)
        if line:
            seed = int(re.search(r"take-s(\d+)", str(path)).group(1))
            i = int(line.group(1))
            return "garbled nonsense words here" if (seed, i) in self.misheard else self.lines[i]
        patch = re.match(r"patch(\d+)-s(\d+)\.wav", name)
        i, seed = int(patch.group(1)), int(patch.group(2))
        return "garbled nonsense words here" if ("patch", i, seed) in self.misheard else self.lines[i]

    def measure_pitch(self, path, spans):
        samples, sr = vt.read_wav(path)
        return [burst_pitch(samples[round(a * sr):round(b * sr)], sr) for a, b in spans]


def simple_grade(text, heard):
    ok = text == heard
    return {"wer": 0.0 if ok else 1.0, "cer": 0.0 if ok else 1.0, "threshold": 0.15, "score": 0.0 if ok else 9.0, "ok": ok}


class TmpDirTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)


# --------------------------------------------------------------------------------------
# Silence search, boundaries, pacing
# --------------------------------------------------------------------------------------


class SilenceTests(unittest.TestCase):
    def test_finds_only_long_quiet_runs(self):
        x = tone(0.5) + gap(0.6) + tone(0.5) + gap(0.08) + tone(0.3) + gap(0.3)
        fr = vt.Framing(SR)
        found = vt.find_silences(vt.frame_db(x, fr), fr)
        self.assertEqual(len(found), 2)  # the 0.08 s gap is too short; the 0.6 s and the final 0.3 s count
        (a, b), (c, d) = found
        self.assertAlmostEqual(a, 0.5 + 0.02, delta=0.04)
        self.assertAlmostEqual(b - a, 0.6, delta=0.06)
        self.assertGreater(c, 1.9)

    def test_loud_audio_has_none(self):
        fr = vt.Framing(SR)
        self.assertEqual(vt.find_silences(vt.frame_db(tone(1.0), fr), fr), [])

    def test_speech_extent_and_loudness(self):
        x = gap(0.3) + tone(0.5, amp=0.2) + gap(0.4)
        fr = vt.Framing(SR)
        db = vt.frame_db(x, fr)
        start, end = vt.speech_extent(db, fr, 0.0, len(x) / SR)
        self.assertAlmostEqual(start, 0.3, delta=0.05)
        self.assertAlmostEqual(end, 0.8, delta=0.05)
        self.assertAlmostEqual(vt.active_loudness(db, fr, 0.0, len(x) / SR), 20 * math.log10(0.2 / math.sqrt(2)), delta=0.3)
        self.assertIsNone(vt.speech_extent(db, fr, 0.9, 1.1))
        self.assertIsNone(vt.active_loudness(db, fr, 0.9, 1.1))


class SnapTests(unittest.TestCase):
    def test_snaps_to_the_middle_of_the_longest_silence_in_reach(self):
        silences = [(4.0, 4.15), (4.5, 5.1), (9.0, 9.5)]
        t, ok = vt.snap_boundary(4.3, 5.0, silences)
        self.assertTrue(ok)
        self.assertAlmostEqual(t, 4.8)  # 4.5-5.1 is longer than 4.0-4.15, the far one is out of reach

    def test_no_silence_in_reach_uses_the_midpoint(self):
        t, ok = vt.snap_boundary(4.3, 4.5, [(9.0, 9.5), (0.0, 0.2)])
        self.assertFalse(ok)
        self.assertAlmostEqual(t, 4.4)

    def test_reach_is_plus_minus_the_slack(self):
        self.assertTrue(vt.snap_boundary(4.0, 4.0, [(4.3, 4.5)], slack=0.35)[1])  # starts 0.3 s after the boundary
        self.assertFalse(vt.snap_boundary(4.0, 4.0, [(4.4, 4.6)], slack=0.35)[1])  # starts 0.4 s after

    def test_cuts_are_increasing_and_inside_the_take(self):
        spans = [(0.1, 2.0), (2.1, 4.0), (4.1, 6.0)]
        cuts, snapped = vt.plan_cuts(spans, [(2.0, 2.1), (4.0, 4.2)], 6.2)
        self.assertEqual(len(cuts), 2)
        self.assertEqual(snapped, [True, True])
        self.assertTrue(0 < cuts[0] < cuts[1] < 6.2)
        cuts, snapped = vt.plan_cuts([(0.0, 3.0), (2.9, 3.0), (2.8, 3.0)], [], 3.0)  # overlapping words must not give equal cuts
        self.assertTrue(0 < cuts[0] < cuts[1] < 3.0)

    def test_a_very_short_line_between_two_silences_gets_a_silence_for_each_boundary(self):
        # line 1 is one 0.3 s word. Both silences reach into the window of both boundaries (+-0.35 s); each must serve only
        # the boundary it is nearest to, otherwise both cuts land in the first silence and line 1 becomes 0.05 s of nothing.
        spans = [(0.1, 2.0), (2.3, 2.6), (2.9, 5.0)]
        cuts, snapped = vt.plan_cuts(spans, [(2.0, 2.3), (2.6, 2.9)], 5.2)
        self.assertEqual(snapped, [True, True])
        self.assertAlmostEqual(cuts[0], 2.15)
        self.assertAlmostEqual(cuts[1], 2.75)
        self.assertGreater(cuts[1] - cuts[0], 0.5)  # the short line keeps its word

    def test_a_longer_silence_next_door_is_not_stolen_by_the_neighbouring_boundary(self):
        spans = [(0.1, 2.0), (2.3, 2.6), (2.9, 5.0)]
        cuts, snapped = vt.plan_cuts(spans, [(2.0, 2.2), (2.6, 3.0)], 5.2)  # the second silence is longer and in reach of boundary 0
        self.assertEqual(snapped, [True, True])
        self.assertAlmostEqual(cuts[0], 2.1)
        self.assertAlmostEqual(cuts[1], 2.8)

    def test_a_boundary_whose_only_silence_belongs_to_a_neighbour_falls_back_to_the_word_gap(self):
        spans = [(0.1, 2.0), (2.3, 2.6), (2.9, 5.0)]
        cuts, snapped = vt.plan_cuts(spans, [(2.6, 2.9)], 5.2)
        self.assertEqual(snapped, [False, True])
        self.assertAlmostEqual(cuts[0], 2.15)  # middle of the gap between the words
        self.assertAlmostEqual(cuts[1], 2.75)

    def test_equally_long_silences_prefer_the_one_nearest_the_gap(self):
        t, ok = vt.snap_boundary(4.0, 4.4, [(3.7, 4.0), (4.1, 4.4)])  # both 0.3 s; the second is centred on the gap
        self.assertTrue(ok)
        self.assertAlmostEqual(t, 4.25)


class PacingTests(unittest.TestCase):
    def test_long_silence_is_cut_to_the_target_and_short_ones_stay(self):
        x = tone(0.5) + gap(1.0) + tone(0.5) + gap(0.4) + tone(0.5)
        fr = vt.Framing(SR)
        sil = vt.find_silences(vt.frame_db(x, fr), fr)
        out, removed = vt.shorten_pauses(x, SR, sil)
        self.assertEqual(len(removed), 1)
        cut = removed[0][1] - removed[0][0]
        self.assertAlmostEqual(len(x) / SR - len(out) / SR, cut, places=3)
        self.assertGreater(cut, 0.5)  # a 1.0 s pause lost about 0.65 s
        db = vt.frame_db(out, fr)
        longest = max(b - a for a, b in vt.find_silences(db, fr))
        self.assertLessEqual(longest, vt.PAUSE_MAX_S)  # nothing above the limit is left
        self.assertGreater(longest, 0.3)  # the 0.4 s pause is untouched

    def test_nothing_to_shorten_returns_the_same_audio(self):
        x = tone(0.5) + gap(0.3) + tone(0.5)
        fr = vt.Framing(SR)
        out, removed = vt.shorten_pauses(x, SR, vt.find_silences(vt.frame_db(x, fr), fr))
        self.assertEqual(removed, [])
        self.assertEqual(out, x)

    def test_splice_is_faded(self):
        x = tone(0.5) + gap(1.0) + tone(0.5)
        fr = vt.Framing(SR)
        out, removed = vt.shorten_pauses(x, SR, vt.find_silences(vt.frame_db(x, fr), fr))
        k = round(removed[0][0] * SR)
        around = out[k - 400:k + 400]
        self.assertLess(max(abs(a - b) for a, b in zip(around, around[1:])), 200)  # no click: silence on both sides, faded

    def test_a_fade_really_ramps_the_edges_next_to_a_splice(self):
        loud = array.array("h", [10000] * 24000)  # a "silence" that is not silent, so the fade is visible
        out, removed = vt.shorten_pauses(loud, SR, [(0.1, 0.9)])
        self.assertEqual(len(removed), 1)
        k = round(removed[0][0] * SR)
        self.assertLess(abs(out[k - 1]), 200)  # last sample before the cut is almost zero ...
        self.assertLess(abs(out[k]), 200)  # ... and so is the first one after it
        self.assertEqual(out[k - 2000], 10000)  # far from the splice nothing changed

    def test_remap_time(self):
        removed = [(2.0, 3.0), (6.0, 6.5)]
        self.assertAlmostEqual(vt.remap_time(1.0, removed), 1.0)
        self.assertAlmostEqual(vt.remap_time(2.5, removed), 2.0)  # inside a removed stretch: where it was cut
        self.assertAlmostEqual(vt.remap_time(4.0, removed), 3.0)
        self.assertAlmostEqual(vt.remap_time(6.25, removed), 5.0)
        self.assertAlmostEqual(vt.remap_time(9.0, removed), 7.5)


class LineSpanTests(unittest.TestCase):
    def test_words_to_lines(self):
        aligned = [{"text": w, "start": float(k), "end": k + 0.5} for k, w in enumerate("a b c d e f".split())]
        self.assertEqual(vt.line_spans_from_words(aligned, ["a b", "c", "d e f"]), [(0.0, 1.5), (2.0, 2.5), (3.0, 5.5)])

    def test_a_lone_dash_joins_its_neighbour_and_does_not_shift_the_lines(self):
        texts = ["Hello there", "- wait what"]  # captions.script_units glues the lone "-" onto "there"
        from captions import script_units
        units = script_units(texts)
        aligned = [{"text": u, "start": float(k), "end": k + 0.5} for k, u in enumerate(units)]
        spans = vt.line_spans_from_words(aligned, texts)
        self.assertEqual(spans[0], (0.0, 1.5))  # line 0 = "Hello", "there -"
        self.assertEqual(spans[1], (2.0, 3.5))

    def test_a_line_without_words_rejects_the_take(self):
        with self.assertRaises(vt.TakeRejected):
            vt.line_spans_from_words([{"text": "a", "start": 0.0, "end": 0.5}], ["a", "b c"])


# --------------------------------------------------------------------------------------
# The gate maths (synthetic arrays)
# --------------------------------------------------------------------------------------


def hz(base, offsets_st):
    return [base * 2 ** (o / 12) for o in offsets_st]


class ContinuityGateTests(unittest.TestCase):
    def gate(self, offsets, loud=None, ref=None, base=150.0):
        f0s = hz(base, offsets)
        return vt.continuity_gate(f0s, loud if loud is not None else [-17.0] * len(f0s), ref)

    def test_a_steady_take_passes(self):
        g = self.gate([0, 0.5, -0.5, 1.0, -1.0, 0.3], ref=150.0)
        self.assertTrue(g["ok"], g["reasons"])
        self.assertAlmostEqual(g["take_median_hz"], 150.0, delta=3)
        self.assertLess(g["sd_st"], 1.0)

    def test_one_line_far_from_the_median_fails_and_names_the_line(self):
        g = self.gate([0, 0, 0, 5.6, 0, 0, 0])
        self.assertFalse(g["ok"])
        self.assertTrue(any("line 3" in r and "median" in r for r in g["reasons"]), g["reasons"])

    def test_the_five_semitone_limit_is_inclusive(self):
        g = self.gate([0, 0, 0, 0, 0, 0, 0, 0, 0, 4.9])  # one outlier of 4.9 st: the per-line limit holds
        self.assertLessEqual(g["max_line_offset_st"], 5.0)
        self.assertFalse(any("from the take's median" in r for r in g["reasons"]))

    def test_spread_too_large_fails_only_on_the_spread(self):
        g = self.gate([-4, -2, 0, 2, 4, 2, 0, -2, -4])  # SD 2.7, every line within 4, neighbours 2 apart
        self.assertFalse(g["ok"])
        self.assertEqual(len(g["reasons"]), 1)
        self.assertIn("spread", g["reasons"][0])

    def test_a_neighbour_jump_over_the_limit_fails_alone(self):
        jump = vt.MAX_JUMP_ST + 0.5  # a clean step in the middle of the take: the spread and the line offsets (jump / 2) stay inside their limits
        g = self.gate([0, 0, 0, jump, jump, jump])
        self.assertFalse(g["ok"])
        self.assertEqual(len(g["reasons"]), 1)
        self.assertIn("line 2 to line 3", g["reasons"][0])
        self.assertAlmostEqual(g["max_adjacent_jump_st"], jump, delta=0.01)

    def test_a_neighbour_jump_just_inside_the_limit_passes(self):
        jump = vt.MAX_JUMP_ST - 0.5
        g = self.gate([0, 0, 0, jump, jump, jump])
        self.assertTrue(g["ok"], g["reasons"])

    def test_a_loudness_jump_over_the_limit_fails_alone(self):
        jump = vt.MAX_JUMP_DB + 0.3
        g = self.gate([0, 0, 0, 0], loud=[-17.0, -17.2, -17.2 - jump, -17.3 - jump])
        self.assertFalse(g["ok"])
        self.assertEqual(len(g["reasons"]), 1)
        self.assertIn("dB from line 1 to line 2", g["reasons"][0])

    def test_exactly_the_loudness_limit_still_passes(self):
        self.assertTrue(self.gate([0, 0], loud=[-17.0, -17.0 - vt.MAX_JUMP_DB])["ok"])

    def test_reference_voice_register(self):
        inside = vt.MAX_REF_ST - 0.1
        outside = vt.MAX_REF_ST + 0.2
        self.assertTrue(self.gate([0, 0.2, -0.2], ref=150 * 2 ** (inside / 12))["ok"])  # just inside the limit, below the reference
        far = self.gate([0, 0.2, -0.2], ref=150 * 2 ** (outside / 12))
        self.assertFalse(far["ok"])
        self.assertIn("reference voice", far["reasons"][0])
        self.assertLess(far["ref_offset_st"], -vt.MAX_REF_ST)

    def test_no_reference_means_no_reference_check(self):
        self.assertTrue(self.gate([0, 0.2, -0.2], ref=None, base=400.0)["ok"])

    def test_unmeasurable_line_fails(self):
        g = vt.continuity_gate([150.0, None, 151.0], [-17.0, -17.0, -17.0])
        self.assertFalse(g["ok"])
        self.assertIn("line(s) 1", g["reasons"][0])

    def test_nothing_measurable(self):
        self.assertFalse(vt.continuity_gate([None, None], [None, None])["ok"])

    def test_single_line(self):
        self.assertTrue(vt.continuity_gate([150.0], [-17.0], 150.0)["ok"])


class PatchRuleTests(unittest.TestCase):
    def test_voice_check_is_required(self):
        self.assertFalse(vt.patch_accepts(False, 150.0, [150.0, 150.0]))

    def test_pitch_must_be_within_two_semitones_of_the_neighbours(self):
        near = hz(150.0, [0.0, 0.0])
        self.assertTrue(vt.patch_accepts(True, hz(150.0, [1.9])[0], near))
        self.assertTrue(vt.patch_accepts(True, hz(150.0, [-1.9])[0], near))
        self.assertFalse(vt.patch_accepts(True, hz(150.0, [2.1])[0], near))

    def test_target_is_the_median_of_the_neighbours(self):
        near = hz(150.0, [0.0, 3.0])  # median = halfway
        self.assertTrue(vt.patch_accepts(True, hz(150.0, [1.5])[0], near))

    def test_edge_lines_have_one_neighbour_and_missing_pitches_are_ignored(self):
        self.assertFalse(vt.patch_accepts(True, hz(150.0, [4])[0], [150.0, None]))
        self.assertTrue(vt.patch_accepts(True, 150.0, [None, None]))  # nothing to compare with: the voice check is enough
        self.assertFalse(vt.patch_accepts(True, None, [150.0]))

    def test_gain_matches_the_neighbours_and_is_capped(self):
        self.assertAlmostEqual(vt.patch_gain_db(-20.0, [-17.0, -17.0]), 3.0)
        self.assertAlmostEqual(vt.patch_gain_db(-14.0, [-17.0]), -3.0)
        self.assertAlmostEqual(vt.patch_gain_db(-30.0, [-17.0]), vt.PATCH_GAIN_CAP_DB)
        self.assertEqual(vt.patch_gain_db(None, [-17.0]), 0.0)
        self.assertEqual(vt.patch_gain_db(-20.0, [None]), 0.0)


# --------------------------------------------------------------------------------------
# Cache keys, cache files, the probe, HTTP helpers
# --------------------------------------------------------------------------------------


class CacheKeyTests(unittest.TestCase):
    def test_key_is_stable_and_depends_on_every_part(self):
        base = vt.cache_key(["hello world"], "Ryan", "model-a", 1)
        self.assertEqual(base, vt.cache_key(["hello world"], "Ryan", "model-a", 1))
        self.assertRegex(base, r"^[0-9a-f]{20}$")
        for other in (vt.cache_key(["hello world!"], "Ryan", "model-a", 1), vt.cache_key(["hello world"], "Aiden", "model-a", 1),
                      vt.cache_key(["hello world"], "Ryan", "model-b", 1), vt.cache_key(["hello world"], "Ryan", "model-a", 2),
                      vt.cache_key(["hello world"], "Ryan", "model-a", 1, "be warm")):
            self.assertNotEqual(base, other)

    def test_a_changed_script_gets_a_new_key(self):
        self.assertNotEqual(vt.cache_key(LINES, "Ryan", "m", 1), vt.cache_key([t.replace("fridge", "freezer") for t in LINES], "Ryan", "m", 1))

    def test_the_same_words_in_other_lines_get_another_key(self):
        # the take is cut at the line boundaries, so merging or splitting lines without changing a word is a different script
        merged = [LINES[0] + " " + LINES[1], *LINES[2:]]
        split = [LINES[0], "It moves heat", "out of the box.", *LINES[2:]]
        self.assertEqual(" ".join(merged), " ".join(LINES))
        self.assertEqual(" ".join(split), " ".join(LINES))
        keys = {vt.cache_key(lines, "Ryan", "m", 1) for lines in (LINES, merged, split)}
        self.assertEqual(len(keys), 3)
        self.assertEqual(len({vt.script_key(lines, "Ryan", "m") for lines in (LINES, merged, split)}), 3)

    def test_script_key_ignores_the_seed_but_not_voice_or_model(self):
        base = vt.script_key(LINES, "Ryan", "m")
        self.assertEqual(base, vt.script_key(list(LINES), "Ryan", "m"))
        self.assertNotEqual(base, vt.script_key(LINES, "Aiden", "m"))
        self.assertNotEqual(base, vt.script_key(LINES, "Ryan", "m2"))


class CacheFileTests(TmpDirTest):
    def meta(self, f0=150.0, ok=True):
        lines = [{"index": i, "text": f"line {i}", "ok": ok, "f0_hz": f0, "loudness_db": -17.0} for i in range(3)]
        return {"seed": 2, "lines": lines, "bounds": [0, 10, 20, 30], "sr": SR, "patches": [], "snapped": [True, True],
                "raw_seconds": 1.0, "pauses_shortened": 0, "pause_seconds_saved": 0.0}

    def test_stored_take_comes_back(self):
        wav = self.tmp / "n.wav"
        vt.write_wav(wav, tone(0.1))
        vt.store_take(self.tmp / "cache", "k", 2, wav, self.meta())
        got = vt.load_cached_take(self.tmp / "cache", "k", 2, 150.0)
        self.assertIsNotNone(got)
        self.assertTrue(got["continuity"]["ok"])
        self.assertTrue((got["folder"] / "narration.wav").is_file())
        self.assertIsNone(vt.load_cached_take(self.tmp / "cache", "k", 3, 150.0))  # other seed
        self.assertIsNone(vt.load_cached_take(self.tmp / "cache", "other", 2, 150.0))

    def test_a_hit_must_hold_exactly_the_current_lines(self):
        # the stored take is cut at ITS line boundaries; other text per line or another line count is a miss, even under the same key
        wav = self.tmp / "n.wav"
        vt.write_wav(wav, tone(0.1))
        vt.store_take(self.tmp / "cache", "k", 2, wav, self.meta())
        same = ["line 0", "line 1", "line 2"]
        self.assertIsNotNone(vt.load_cached_take(self.tmp / "cache", "k", 2, 150.0, same))
        self.assertIsNone(vt.load_cached_take(self.tmp / "cache", "k", 2, 150.0, ["line 0 line 1", "line 2"]))  # merged
        self.assertIsNone(vt.load_cached_take(self.tmp / "cache", "k", 2, 150.0, ["line 0", "line", "1", "line 2"]))  # split
        self.assertIsNone(vt.load_cached_take(self.tmp / "cache", "k", 2, 150.0, ["line 0", "line 1", "line two"]))  # reworded
        self.assertIsNone(vt.load_cached_take(self.tmp / "cache", "k", 2, 150.0, ["line 1", "line 0", "line 2"]))  # reordered

    def test_the_accepted_seed_is_remembered_per_script(self):
        cache = self.tmp / "cache"
        self.assertIsNone(vt.accepted_pointer(cache, "script"))
        vt.store_accepted_pointer(cache, "script", 7)
        self.assertEqual(vt.accepted_pointer(cache, "script"), 7)
        self.assertIsNone(vt.accepted_pointer(cache, "other-script"))
        vt.store_accepted_pointer(cache, "script", 2)
        self.assertEqual(vt.accepted_pointer(cache, "script"), 2)
        (cache / "script-accepted.json").write_text("{broken", encoding="utf-8")
        self.assertIsNone(vt.accepted_pointer(cache, "script"))
        (cache / "script-accepted.json").write_text('{"seed": "x"}', encoding="utf-8")
        self.assertIsNone(vt.accepted_pointer(cache, "script"))

    def test_stored_numbers_are_judged_again_with_todays_rules(self):
        wav = self.tmp / "n.wav"
        vt.write_wav(wav, tone(0.1))
        vt.store_take(self.tmp / "cache", "k", 2, wav, self.meta(f0=150.0))
        self.assertIsNone(vt.load_cached_take(self.tmp / "cache", "k", 2, 250.0))  # now the channel reference is far away

    def test_broken_cache_files_are_a_miss_not_a_crash(self):
        folder = vt.cache_dir_for(self.tmp / "cache", "k", 1)
        folder.mkdir(parents=True)
        (folder / "take.json").write_text("{not json", encoding="utf-8")
        self.assertIsNone(vt.load_cached_take(self.tmp / "cache", "k", 1, 150.0))

    def test_rejections_are_remembered_per_gate_version_and_transcription_engine(self):
        vt.store_rejection(self.tmp / "cache", "k", 1, "asr-a", "line 3 is off")
        self.assertEqual(vt.rejected_before(self.tmp / "cache", "k", 1, "asr-a"), "line 3 is off")
        self.assertIsNone(vt.rejected_before(self.tmp / "cache", "k", 1, "asr-b"))
        self.assertIsNone(vt.rejected_before(self.tmp / "cache", "k", 2, "asr-a"))
        with mock.patch.object(vt, "GATE_VERSION", vt.GATE_VERSION + 1):
            self.assertIsNone(vt.rejected_before(self.tmp / "cache", "k", 1, "asr-a"))

    def test_storing_a_take_forgets_an_old_rejection(self):
        vt.store_rejection(self.tmp / "cache", "k", 2, "asr-a", "old")
        wav = self.tmp / "n.wav"
        vt.write_wav(wav, tone(0.1))
        vt.store_take(self.tmp / "cache", "k", 2, wav, self.meta())
        self.assertIsNone(vt.rejected_before(self.tmp / "cache", "k", 2, "asr-a"))


class ProbeTests(TmpDirTest):
    class Engine:
        def __init__(self, mode):
            self.mode, self.calls = mode, 0

        def synth(self, text, seed, instructions=None):
            self.calls += 1
            if self.mode == "ignores":
                return b"same audio"
            if self.mode == "listens":
                return b"audio:" + (instructions or "").encode()
            return b"random:%d" % self.calls

    def run_probe(self, mode, cache=None):
        engine = self.Engine(mode)
        lines = []
        result = vt.probe_instructions(engine, "Ryan", "m", cache or self.tmp / "probe.json", "be warm", log=lines.append)
        return engine, result, lines

    def test_engine_that_ignores_instructions(self):
        _e, result, lines = self.run_probe("ignores")
        self.assertIs(result["instructions_ignored"], True)
        self.assertIn("IGNORES", lines[0])

    def test_engine_that_listens(self):
        _e, result, lines = self.run_probe("listens")
        self.assertIs(result["instructions_ignored"], False)
        self.assertIn("DOES change", lines[0])

    def test_engine_that_is_not_repeatable_cannot_be_judged(self):
        _e, result, _l = self.run_probe("random")
        self.assertIsNone(result["instructions_ignored"])

    def test_probe_runs_once_and_is_cached(self):
        engine, first, _ = self.run_probe("ignores")
        self.assertEqual(engine.calls, 3)
        again, second, lines = self.run_probe("ignores")
        self.assertEqual(again.calls, 0)
        self.assertEqual(lines, [])
        self.assertEqual(first["instructions_ignored"], second["instructions_ignored"])
        self.assertTrue(json.loads((self.tmp / "probe.json").read_text())["Ryan|m"]["instructions_ignored"])

    def test_probe_is_repeated_for_another_voice_or_model(self):
        self.run_probe("ignores")
        other = self.Engine("ignores")
        vt.probe_instructions(other, "Aiden", "m", self.tmp / "probe.json", "x", log=lambda m: None)
        self.assertEqual(other.calls, 3)
        third = self.Engine("ignores")
        vt.probe_instructions(third, "Ryan", "m2", self.tmp / "probe.json", "x", log=lambda m: None)
        self.assertEqual(third.calls, 3)

    def test_switching_back_and_forth_between_voices_probes_each_one_only_once(self):
        # English (Ryan) and German (Aiden) runs alternate: neither may cost 3 voice requests again
        cache = self.tmp / "probe.json"
        for voice, expected in (("Ryan", 3), ("Aiden", 3), ("Ryan", 0), ("Aiden", 0), ("Ryan", 0)):
            engine = self.Engine("ignores")
            result = vt.probe_instructions(engine, voice, "m", cache, "x", log=lambda m: None)
            self.assertEqual(engine.calls, expected, voice)
            self.assertIs(result["instructions_ignored"], True)
        self.assertEqual(sorted(json.loads(cache.read_text())), ["Aiden|m", "Ryan|m"])

    def test_the_old_single_voice_file_is_still_understood(self):
        cache = self.tmp / "probe.json"
        cache.write_text(json.dumps({"voice": "Ryan", "model": "m", "checked_at": "2026-10-14", "instructions_ignored": True}), encoding="utf-8")
        engine = self.Engine("ignores")
        self.assertIs(vt.probe_instructions(engine, "Ryan", "m", cache, "x", log=lambda m: None)["instructions_ignored"], True)
        self.assertEqual(engine.calls, 0)
        german = self.Engine("ignores")
        vt.probe_instructions(german, "Aiden", "m", cache, "x", log=lambda m: None)
        self.assertEqual(german.calls, 3)
        self.assertEqual(sorted(json.loads(cache.read_text())), ["Aiden|m", "Ryan|m"])  # the old entry was kept, not overwritten

    def test_a_garbled_probe_file_is_just_a_miss(self):
        cache = self.tmp / "probe.json"
        for junk in ("{broken", "[1, 2]", '{"Ryan|m": 5}'):
            cache.write_text(junk, encoding="utf-8")
            engine = self.Engine("ignores")
            vt.probe_instructions(engine, "Ryan", "m", cache, "x", log=lambda m: None)
            self.assertEqual(engine.calls, 3, junk)


class HttpHelperTests(unittest.TestCase):
    def test_multipart_repeats_list_fields(self):
        body, ctype = vt.build_multipart({"model": "m", "timestamp_granularities[]": ["word", "segment"]}, "a.wav", b"RIFFDATA")
        self.assertEqual(body.count(b'name="timestamp_granularities[]"'), 2)
        self.assertIn(b"word", body)
        self.assertIn(b"segment", body)
        self.assertIn(b"RIFFDATA", body)
        self.assertTrue(ctype.startswith("multipart/form-data; boundary="))

    def test_pitch_command_prefers_the_mpt_venv(self):
        with tempfile.TemporaryDirectory() as raw:
            venv = Path(raw) / ".venv" / "bin"
            venv.mkdir(parents=True)
            (venv / "python").write_text("")
            argv, cwd = vt.pitch_command(Path(raw))
            self.assertEqual(argv, [str(venv / "python")])
            self.assertIsNone(cwd)

    def test_pitch_command_without_numpy_python_says_what_is_missing(self):
        with tempfile.TemporaryDirectory() as raw, mock.patch.object(vt.shutil, "which", return_value=None):
            with self.assertRaises(vt.VoiceTakeError) as caught:
                vt.pitch_command(Path(raw))
        self.assertIn("numpy", str(caught.exception))

    def test_backend_turns_http_errors_into_plain_messages(self):
        backend = vt.VoiceStudioBackend("http://127.0.0.1:9", "Ryan", "asr", "en")
        with mock.patch.object(vt.time, "sleep"), mock.patch.object(vt.urllib.request, "urlopen", side_effect=vt.urllib.error.URLError("refused")):
            with self.assertRaises(vt.VoiceTakeError) as caught:
                backend.synth("hi", 1)
        self.assertIn("VoiceStudio", str(caught.exception))
        self.assertIn("running", str(caught.exception))

    def test_backend_synth_sends_seed_and_never_a_language(self):
        backend = vt.VoiceStudioBackend("http://x", "Ryan", "asr", "en", "be warm")
        sent = {}

        def fake_request(path, data, content_type, timeout, what):
            sent.update(path=path, body=json.loads(data))
            return b"x" * 200

        with mock.patch.object(backend, "_request", side_effect=fake_request):
            backend.synth("Hello there.", 7)
            self.assertEqual(sent["path"], "/v1/audio/speech")
            self.assertEqual(sent["body"], {"input": "Hello there.", "voice": "Ryan", "response_format": "wav", "seed": 7, "instructions": "be warm"})
            backend.synth("Hello there.", 8, instructions="")
            self.assertNotIn("instructions", sent["body"])
            self.assertNotIn("language", sent["body"])

    def test_backend_asks_for_word_timestamps(self):
        backend = vt.VoiceStudioBackend("http://x", "Ryan", "asr", "de")
        with tempfile.TemporaryDirectory() as raw:
            wav = Path(raw) / "a.wav"
            vt.write_wav(wav, tone(0.1))
            seen = {}

            def fake_request(path, data, content_type, timeout, what):
                seen.update(path=path, data=data)
                return json.dumps({"text": "hi", "words": [{"word": " hi", "start": 0.1, "end": 0.4}]}).encode()

            with mock.patch.object(backend, "_request", side_effect=fake_request):
                words = backend.transcribe_words(wav)
        self.assertEqual(words, [{"start": 0.1, "end": 0.4, "text": "hi"}])
        self.assertEqual(seen["path"], "/v1/audio/transcriptions")
        for needle in (b'name="response_format"\r\n\r\nverbose_json', b"word", b"segment", b'name="language"\r\n\r\nde', b'name="model"\r\n\r\nasr'):
            self.assertIn(needle, seen["data"])

    def test_backend_without_word_timestamps_says_so(self):
        backend = vt.VoiceStudioBackend("http://x", "Ryan", "asr", "en")
        with tempfile.TemporaryDirectory() as raw:
            wav = Path(raw) / "a.wav"
            vt.write_wav(wav, tone(0.1))
            with mock.patch.object(backend, "_request", return_value=b'{"text": "hi"}'):
                with self.assertRaises(vt.VoiceTakeError) as caught:
                    backend.transcribe_words(wav)
        self.assertIn("word timestamps", str(caught.exception))


@unittest.skipUnless((vt.MPT_DIR / ".venv" / "bin" / "python").is_file(), "MoneyPrinterTurbo's venv (numpy) is not available")
class PitchSubprocessTests(TmpDirTest):
    def test_voice_pitch_measures_a_harmonic_tone(self):
        w = 2 * math.pi * 120.0 / SR
        x = array.array("h", (int(8000 * (math.sin(w * i) + 0.5 * math.sin(2 * w * i) + 0.3 * math.sin(3 * w * i))) for i in range(SR * 2)))
        wav = self.tmp / "t.wav"
        vt.write_wav(wav, x)
        for value in vt.measure_pitch_file(wav, [(0.0, 1.0), (1.0, 2.0)]):
            self.assertAlmostEqual(value, 120.0, delta=2.5)
        self.assertAlmostEqual(vt.measure_pitch_file(wav)[0], 120.0, delta=2.5)

    def test_silence_has_no_pitch(self):
        wav = self.tmp / "s.wav"
        vt.write_wav(wav, gap(1.5))
        self.assertEqual(vt.measure_pitch_file(wav, [(0.0, 1.5)]), [None])


# --------------------------------------------------------------------------------------
# produce_narration with a fake VoiceStudio
# --------------------------------------------------------------------------------------


class ProduceNarrationTests(TmpDirTest):
    def produce(self, fake, **kw):
        args = dict(backend=fake, grade=simple_grade, voice="Ryan", model="m1", asr_model="asr1", ref_f0=150.0, work_dir=self.tmp / "work",
                    cache_root=self.tmp / "cache", start_seed=1, log=lambda m: None)
        args.update(kw)
        return vt.produce_narration(LINES, **args)

    def test_happy_path_one_request_pacing_timings_and_measures(self):
        fake = FakeVoice()
        take = self.produce(fake)
        self.assertEqual(fake.synth_calls, [(FULL, 1)])  # the whole script in ONE request
        self.assertEqual(take["seed"], 1)
        self.assertTrue(take["continuity"]["ok"])
        self.assertEqual(len(take["lines"]), 4)
        for line in take["lines"]:
            self.assertTrue(line["ok"])
            self.assertAlmostEqual(line["f0_hz"], 150.0, delta=3.0)
            self.assertAlmostEqual(line["loudness_db"], 20 * math.log10(0.2 / math.sqrt(2)), delta=0.6)
        self.assertEqual(take["snapped"], [True, True, True])
        self.assertEqual(take["pauses_shortened"], 3)  # the three 0.8 s pauses between lines
        samples, sr = vt.read_wav(take["narration"])
        self.assertAlmostEqual(take["duration"], len(samples) / sr, places=3)
        raw, _ = vt.read_wav(self.tmp / "work" / "take-s1" / "take-raw.wav")
        self.assertGreater(len(raw) - len(samples), 3 * 0.35 * sr)  # about 3 x 0.45 s were cut

    def test_timings_have_the_old_shape_and_follow_the_sound(self):
        take = self.produce(FakeVoice())
        timings = take["timings"]
        self.assertEqual([t["index"] for t in timings], [0, 1, 2, 3])
        self.assertEqual([t["text"] for t in timings], LINES)
        self.assertEqual(set(timings[0]), {"index", "start", "end", "text"})
        for a, b in zip(timings, timings[1:]):
            self.assertLess(a["start"], a["end"])
            self.assertGreater(b["start"] - a["end"], 0.2)  # a real pause between lines ...
            self.assertLess(b["start"] - a["end"], 0.55)  # ... shortened from 0.8 s
        self.assertAlmostEqual(timings[0]["start"], 0.1, delta=0.06)
        samples, sr = vt.read_wav(take["narration"])
        self.assertLessEqual(timings[-1]["end"], len(samples) / sr)
        self.assertEqual(take["bounds"][0], 0)
        self.assertEqual(take["bounds"][-1], len(samples))

    def test_second_run_with_the_same_script_is_instant(self):
        a = self.produce(FakeVoice())
        second = FakeVoice()
        b = self.produce(second, work_dir=self.tmp / "work2")
        self.assertEqual(second.synth_calls, [])  # nothing voiced
        self.assertTrue(b["cache"]["hit"])
        self.assertFalse(a["cache"]["hit"])
        self.assertEqual(vt.read_wav(b["narration"])[0], vt.read_wav(a["narration"])[0])
        self.assertEqual(b["timings"], a["timings"])
        self.assertEqual(b["seed"], a["seed"])
        self.assertEqual(b["attempts"], a["attempts"])  # the report still shows the tries of the run that made the take

    def test_cache_hit_keeps_the_history_of_rejected_seeds(self):
        pitch = lambda seed, i: 150.0 * (2 ** (6 / 12) if (seed == 1 and i == 2) else 1)
        first = self.produce(FakeVoice(pitch=pitch))
        again = self.produce(FakeVoice(), work_dir=self.tmp / "work2")
        self.assertTrue(again["cache"]["hit"])
        self.assertEqual([a["accepted"] for a in again["attempts"]], [False, True])
        self.assertEqual(again["seed"], first["seed"])

    def test_a_changed_script_is_voiced_again(self):
        self.produce(FakeVoice())
        changed = LINES[:3] + ["That is why the back stays warm."]
        fake = FakeVoice(lines=changed)
        vt.produce_narration(changed, backend=fake, grade=simple_grade, voice="Ryan", model="m1", asr_model="asr1", ref_f0=150.0,
                             work_dir=self.tmp / "work3", cache_root=self.tmp / "cache", log=lambda m: None)
        self.assertEqual(len(fake.synth_calls), 1)

    def produce_lines(self, lines, **kw):
        fake = FakeVoice(lines=lines)
        args = dict(backend=fake, grade=simple_grade, voice="Ryan", model="m1", asr_model="asr1", ref_f0=150.0,
                    work_dir=self.tmp / "work-lines", cache_root=self.tmp / "cache", log=lambda m: None)
        args.update(kw)
        return fake, vt.produce_narration(lines, **args)

    def test_merging_two_lines_without_changing_a_word_is_voiced_again(self):
        # the joined text is the same, but the old take is cut at the old boundaries: reusing it would put every later line's
        # timing (and footage + diagram panel) one line off
        old = self.produce(FakeVoice())
        merged = [LINES[0] + " " + LINES[1], *LINES[2:]]
        self.assertEqual(" ".join(merged), FULL)
        fake, new = self.produce_lines(merged)
        self.assertFalse(new["cache"]["hit"])
        self.assertEqual(fake.synth_calls, [(FULL, 1)])  # voiced again
        self.assertEqual([t["text"] for t in new["timings"]], merged)
        self.assertEqual(len(new["timings"]), 3)
        self.assertEqual(len(new["lines"]), 3)
        self.assertEqual(len(new["bounds"]), 4)
        self.assertNotEqual(new["cache"]["key"], old["cache"]["key"])
        # merged line 0 holds the words of the old lines 0 AND 1, so it must end well after the old line 0 did (the stale take
        # would end it at the old line 0), and the next line is the old line 2 starting after it
        self.assertGreater(new["timings"][0]["end"], old["timings"][0]["end"] + 1.0)
        self.assertLess(new["timings"][0]["end"], new["timings"][1]["start"])
        self.assertAlmostEqual(new["duration"], old["duration"], delta=0.8)  # the same words are spoken
        # the old script is still cached under its own key
        again = FakeVoice()
        self.assertTrue(self.produce(again, work_dir=self.tmp / "work-again")["cache"]["hit"])
        self.assertEqual(again.synth_calls, [])

    def test_splitting_a_line_without_changing_a_word_is_voiced_again_and_does_not_crash(self):
        self.produce(FakeVoice())
        split = [LINES[0], "It moves heat", "out of the box.", *LINES[2:]]
        self.assertEqual(" ".join(split), FULL)
        fake, new = self.produce_lines(split)
        self.assertFalse(new["cache"]["hit"])
        self.assertEqual(len(fake.synth_calls), 1)
        self.assertEqual([t["text"] for t in new["timings"]], split)
        self.assertEqual(len(new["timings"]), 5)
        for a, b in zip(new["timings"], new["timings"][1:]):
            self.assertLess(a["end"], b["start"])

    def test_rejections_are_not_reused_for_another_split_of_the_same_words(self):
        pitch = lambda seed, i: 150.0 * (2 ** (6 / 12) if (seed == 1 and i == 2) else 1)
        self.produce(FakeVoice(pitch=pitch))  # seed 1 rejected ("line 2 is ..."), seed 2 accepted
        merged = [LINES[0] + " " + LINES[1], *LINES[2:]]
        fake, new = self.produce_lines(merged)  # the remembered verdict named line numbers of the OLD split: seed 1 must be tried again
        self.assertEqual(new["seed"], 1)
        self.assertEqual([c[1] for c in fake.synth_calls], [1])

    def test_another_voice_or_model_is_voiced_again(self):
        self.produce(FakeVoice())
        for kw in ({"voice": "Aiden"}, {"model": "m2"}):
            fake = FakeVoice()
            self.produce(fake, work_dir=self.tmp / "work-x", **kw)
            self.assertEqual(len(fake.synth_calls), 1, kw)

    def test_no_cache_flag_voices_again_and_stores_nothing(self):
        self.produce(FakeVoice(), use_cache=False)
        self.assertFalse((self.tmp / "cache").exists())
        fake = FakeVoice()
        self.produce(fake, use_cache=False)
        self.assertEqual(len(fake.synth_calls), 1)

    def test_a_take_with_a_pitch_jump_is_rerolled_with_the_next_seed(self):
        fake = FakeVoice(pitch=lambda seed, i: 150.0 * (2 ** (6 / 12) if (seed == 1 and i == 2) else 1))
        take = self.produce(fake)
        self.assertEqual(take["seed"], 2)
        self.assertEqual([c[1] for c in fake.synth_calls], [1, 2])
        self.assertEqual([a["accepted"] for a in take["attempts"]], [False, True])
        self.assertIn("line 2", take["attempts"][0]["reason"])
        self.assertTrue(take["continuity"]["ok"])

    def test_a_take_in_the_wrong_register_is_rejected_against_the_reference(self):
        fake = FakeVoice(pitch=lambda seed, i: 220.0 if seed <= 2 else 150.0)  # seeds 1-2 come out far too high
        take = self.produce(fake)
        self.assertEqual(take["seed"], 3)
        self.assertIn("reference voice", take["attempts"][0]["reason"])

    def test_loudness_jump_between_neighbours_is_rejected(self):
        fake = FakeVoice(amp=lambda seed, i: (0.07 if (seed == 1 and i == 1) else 0.2))
        take = self.produce(fake)
        self.assertEqual(take["seed"], 2)
        self.assertIn("dB", take["attempts"][0]["reason"])

    def test_a_misheard_line_is_patched_with_a_seed_that_matches_the_neighbours(self):
        fake = FakeVoice(misheard={(1, 1)},
                         line_pitch=lambda i, seed: 150.0 * (2 ** (4 / 12) if seed == 1 else 1.0),  # patch seed 1 is 4 st off, seed 2 fits
                         line_amp=lambda i, seed: 0.14)  # about 3 dB quieter than the take
        take = self.produce(fake)
        self.assertEqual(take["seed"], 1)  # the whole take stays
        self.assertEqual(len(take["patches"]), 1)
        self.assertEqual((take["patches"][0]["line"], take["patches"][0]["seed"]), (1, 2))
        self.assertEqual(take["lines"][1]["patched_seed"], 2)
        self.assertTrue(all(line["ok"] for line in take["lines"]))
        self.assertEqual([c for c in fake.synth_calls if c[0] == LINES[1]], [(LINES[1], 1), (LINES[1], 2)])
        self.assertAlmostEqual(take["lines"][1]["loudness_db"], take["lines"][0]["loudness_db"], delta=1.0)  # loudness-matched
        self.assertAlmostEqual(take["lines"][1]["f0_hz"], 150.0, delta=3.0)
        self.assertEqual(take["timings"][1]["text"], LINES[1])
        for a, b in zip(take["timings"], take["timings"][1:]):
            self.assertLess(a["end"], b["start"])

    def test_patch_keeps_the_pause_around_the_line(self):
        plain = self.produce(FakeVoice(), work_dir=self.tmp / "w-plain", cache_root=self.tmp / "c-plain")
        patched = self.produce(FakeVoice(misheard={(1, 1)}), work_dir=self.tmp / "w-patch", cache_root=self.tmp / "c-patch")
        for a, b in zip(plain["timings"], patched["timings"]):
            self.assertAlmostEqual(a["start"], b["start"], delta=0.12)  # same words, same pauses: everything stays in place

    def test_when_no_patch_seed_works_the_whole_take_is_dropped_for_the_next_seed(self):
        fake = FakeVoice(misheard={(1, 1)} | {("patch", 1, s) for s in range(1, vt.PATCH_SEEDS + 1)})
        take = self.produce(fake)
        self.assertEqual(take["seed"], 2)
        self.assertIn("no patch worked", take["attempts"][0]["reason"])
        self.assertEqual(len([c for c in fake.synth_calls if c[0] == LINES[1]]), vt.PATCH_SEEDS)

    def test_too_many_failed_lines_to_patch_rerolls_without_patching(self):
        fake = FakeVoice(misheard={(1, 0), (1, 1), (1, 2), (1, 3)})
        take = self.produce(fake)
        self.assertEqual(take["seed"], 2)
        self.assertIn("too many to patch", take["attempts"][0]["reason"])
        self.assertEqual([c for c in fake.synth_calls if c[0] != FULL], [])  # not one patch was tried

    def test_all_rejected_takes_fail_in_plain_words_and_are_remembered(self):
        fake = FakeVoice(pitch=lambda seed, i: 150.0 * (2 ** (6 / 12) if i == 2 else 1))
        with self.assertRaises(vt.VoiceTakeError) as caught:
            self.produce(fake)
        message = str(caught.exception)
        self.assertEqual(len(fake.synth_calls), vt.MAX_TAKES)
        for seed in range(1, vt.MAX_TAKES + 1):
            self.assertIn(f"seed {seed}:", message)
        self.assertIn(f"--voice-seed {vt.MAX_TAKES + 1}", message)
        self.assertIn("steady", message)
        again = FakeVoice()
        with self.assertRaises(vt.VoiceTakeError) as second:
            self.produce(again)  # same script: all the verdicts are remembered, nothing is voiced again
        self.assertEqual(again.synth_calls, [])
        self.assertIn("remembered", str(second.exception))
        beyond = vt.MAX_TAKES + 1
        self.assertEqual(self.produce(FakeVoice(), start_seed=beyond)["seed"], beyond)  # --voice-seed beyond the rejected ones

    def failing_then_accepted_after_the_last_default_seed(self):
        """Seeds 1..MAX_TAKES come out in a wrong pitch for line 2 (all rejected), then --voice-seed MAX_TAKES + 1 is accepted."""
        accepted_seed = vt.MAX_TAKES + 1
        bad = lambda seed, i: 150.0 * (2 ** (6 / 12) if i == 2 and seed < accepted_seed else 1)
        with self.assertRaises(vt.VoiceTakeError):
            self.produce(FakeVoice(pitch=bad))
        return bad, self.produce(FakeVoice(pitch=bad), start_seed=accepted_seed)

    def test_an_accepted_take_found_with_a_later_seed_is_reused_by_the_next_default_run(self):
        bad, later = self.failing_then_accepted_after_the_last_default_seed()
        self.assertEqual(later["seed"], vt.MAX_TAKES + 1)
        fake = FakeVoice(pitch=bad)
        again = self.produce(fake, work_dir=self.tmp / "work-again")  # no --voice-seed: starts at 1, but 1..MAX_TAKES were all rejected
        self.assertEqual(fake.synth_calls, [])  # nothing is voiced
        self.assertTrue(again["cache"]["hit"])
        self.assertEqual(again["seed"], vt.MAX_TAKES + 1)
        self.assertEqual(vt.read_wav(again["narration"])[0], vt.read_wav(later["narration"])[0])
        self.assertEqual(again["timings"], later["timings"])
        rejected = [a["seed"] for a in again["attempts"] if not a["accepted"]]
        self.assertEqual(rejected, list(range(1, vt.MAX_TAKES + 1)))  # the report still shows why seeds 1..MAX_TAKES lost
        self.assertTrue(again["attempts"][-1]["accepted"])

    def test_the_accepted_seed_pointer_is_only_a_last_resort(self):
        # an explicit new seed still gets its own fresh take; the pointer is not looked at while the range works
        self.produce(FakeVoice())  # seed 1 accepted
        fake = FakeVoice()
        other = self.produce(fake, start_seed=2, work_dir=self.tmp / "w2")
        self.assertEqual(other["seed"], 2)
        self.assertFalse(other["cache"]["hit"])
        self.assertEqual([c[1] for c in fake.synth_calls], [2])

    def test_the_accepted_seed_pointer_belongs_to_one_script(self):
        bad, _later = self.failing_then_accepted_after_the_last_default_seed()
        merged = [LINES[0] + " " + LINES[1], *LINES[2:]]
        failing = FakeVoice(lines=merged, pitch=lambda seed, i: 150.0 * (2 ** (6 / 12) if i == 1 else 1))
        with self.assertRaises(vt.VoiceTakeError):  # the merged split has no accepted take, so the other script's later seed is not used
            vt.produce_narration(merged, backend=failing, grade=simple_grade, voice="Ryan", model="m1", asr_model="asr1", ref_f0=150.0,
                                 work_dir=self.tmp / "w-merged", cache_root=self.tmp / "cache", log=lambda m: None)

    def test_a_pointed_take_that_fails_todays_gate_does_not_save_the_run(self):
        _bad, _later = self.failing_then_accepted_after_the_last_default_seed()
        with self.assertRaises(vt.VoiceTakeError):
            self.produce(FakeVoice(), ref_f0=250.0, work_dir=self.tmp / "w-ref")  # the channel reference moved: the pointed seed is wrong now

    def test_no_cache_flag_ignores_and_writes_no_pointer(self):
        accepted_seed = vt.MAX_TAKES + 1
        bad = lambda seed, i: 150.0 * (2 ** (6 / 12) if i == 2 and seed < accepted_seed else 1)
        with self.assertRaises(vt.VoiceTakeError):
            self.produce(FakeVoice(pitch=bad), use_cache=False)
        self.produce(FakeVoice(pitch=bad), start_seed=accepted_seed, use_cache=False)
        self.assertFalse((self.tmp / "cache").exists())

    def test_script_of_4096_characters_or_more_is_refused(self):
        class Marker(FakeVoice):
            def synth(self, text, seed, instructions=None):
                raise vt.VoiceTakeError("reached VoiceStudio")

        def run(characters):
            line = ("x" * 99 + " ") * (characters // 100)
            texts = [line.strip(), "y" * (characters - len(line.strip()) - 1)]  # joined with one space: exactly `characters` long
            self.assertEqual(len(" ".join(texts)), characters)
            vt.produce_narration(texts, backend=Marker(), grade=simple_grade, voice="Ryan", model="m", asr_model="a", ref_f0=None,
                                 work_dir=self.tmp / "w", cache_root=self.tmp / "c", log=lambda m: None)

        with self.assertRaises(vt.VoiceTakeError) as caught:
            run(4096)
        self.assertIn("4096", str(caught.exception))
        self.assertNotIn("reached VoiceStudio", str(caught.exception))
        with self.assertRaises(vt.VoiceTakeError) as caught:
            run(4095)  # one character less is fine: it gets as far as VoiceStudio
        self.assertIn("reached VoiceStudio", str(caught.exception))

    def test_backend_failures_are_not_rerolled(self):
        class Down(FakeVoice):
            def synth(self, text, seed, instructions=None):
                raise vt.VoiceTakeError("VoiceStudio could not do to voice the text: refused")

        with self.assertRaises(vt.VoiceTakeError) as caught:
            self.produce(Down())
        self.assertIn("refused", str(caught.exception))

    def test_no_reference_in_voices_json_skips_the_register_check(self):
        take = self.produce(FakeVoice(pitch=lambda seed, i: 250.0), ref_f0=None)
        self.assertEqual(take["seed"], 1)

    def test_line_table_prints_every_line(self):
        take = self.produce(FakeVoice())
        table = vt.format_line_table(take["lines"])
        self.assertEqual(len(table.splitlines()), 5)
        self.assertIn("150", table)


# --------------------------------------------------------------------------------------
# make_video.py: the line check, the voice step, the loudness step
# --------------------------------------------------------------------------------------


class GradeLineTests(unittest.TestCase):
    def test_same_rules_as_before(self):
        good = mv.grade_line("Your fridge does not make cold.", "your fridge does not make cold")
        self.assertTrue(good["ok"])
        self.assertEqual(good["wer"], 0.0)
        bad = mv.grade_line("Your fridge does not make cold.", "your fridge dose nuts make bold")
        self.assertFalse(bad["ok"])
        self.assertGreater(bad["score"], 1.0)
        self.assertEqual(bad["threshold"], mv.WER_LIMIT_LONG)
        self.assertEqual(mv.grade_line("Hello there", "hello there")["threshold"], mv.WER_LIMIT_SHORT)

    def test_letter_error_rescues_spelling_variants(self):
        self.assertTrue(mv.grade_line("a non-stop ride on the earcup test today", "a nonstop ride on the ear cup test today")["ok"])


class NumberLinesInTheTakeTests(TmpDirTest):
    """The voice said "thirty" and "twenty thousand"; the transcriber wrote "30" and "20,000". With make_video.grade_line as the
    line check the take must be accepted without a single patch (it used to reject every seed)."""

    SCRIPT = [
        "Your phone never talks to the satellites.",
        "About thirty GPS satellites circle the Earth, twenty thousand kilometers up.",
        "Overall, they gain thirty-eight millionths of a second a day.",
        "That is why the clocks are set slower before launch.",
    ]
    WRITTEN = {
        SCRIPT[1]: "About 30 GPS satellites circle the Earth, 20,000 kilometers up.",
        SCRIPT[2]: "Overall, they gain 38 millionths of a second a day.",
    }

    class DigitWriter(FakeVoice):
        def __init__(self, lines, written):
            super().__init__(lines=lines)
            self.written = written

        def transcribe_text(self, path):
            heard = super().transcribe_text(path)
            return self.written.get(heard, heard)

    def produce(self, grade, **kw):
        fake = self.DigitWriter(self.SCRIPT, self.WRITTEN)
        args = dict(backend=fake, grade=grade, voice="Ryan", model="m1", asr_model="asr1", ref_f0=150.0, work_dir=self.tmp / "work",
                    cache_root=self.tmp / "cache", start_seed=1, log=lambda m: None)
        args.update(kw)
        return vt.produce_narration(self.SCRIPT, **args), fake

    def test_the_take_is_accepted_and_nothing_is_patched(self):
        take, fake = self.produce(mv.grade_line)
        self.assertEqual(take["seed"], 1)
        self.assertEqual(take["patches"], [])
        self.assertTrue(all(line["ok"] for line in take["lines"]))
        self.assertEqual([line["wer"] for line in take["lines"]], [0.0, 0.0, 0.0, 0.0])
        self.assertEqual(fake.synth_calls, [(" ".join(self.SCRIPT), 1)])  # the whole script voiced once, no patch request

    def test_a_check_that_compares_the_words_literally_would_have_rejected_it(self):
        with self.assertRaises(vt.VoiceTakeError):
            self.produce(simple_grade, work_dir=self.tmp / "w-literal", cache_root=self.tmp / "c-literal")


class ArgsAndHelpTests(unittest.TestCase):
    def test_new_length_defaults_and_voice_flags(self):
        args = mv.parse_args(["x.json"])
        self.assertEqual((args.min_seconds, args.max_seconds), (45.0, 75.0))
        self.assertIsNone(args.voice_seed)
        self.assertFalse(args.no_voice_cache)
        args = mv.parse_args(["x.json", "--voice-seed", "7", "--no-voice-cache"])
        self.assertEqual(args.voice_seed, 7)
        self.assertTrue(args.no_voice_cache)

    def test_help_explains_the_tiktok_rule(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit):
            mv.parse_args(["--help"])
        text = " ".join(buf.getvalue().split())
        self.assertIn("TikTok", text)
        self.assertIn("10,000 followers", text)
        self.assertIn("default 45", text)

    def test_negative_voice_seed_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            mv.parse_args(["x.json", "--voice-seed", "-1"])

    def test_forty_five_second_narration_passes_the_length_gate(self):
        ok, _msg = mv.length_gate(46.0, 110, 45, 75)
        self.assertTrue(ok)


class VoiceStepTests(TmpDirTest):
    def make_ctx(self, *argv):
        ctx = mv.Ctx(mv.parse_args(["content/x/script.json", *argv]))
        ctx.script = {"id": "x", "language": "en", "lines": [{"text": t, "visual": None} for t in LINES]}
        ctx.work = self.tmp / "work" / "x"
        ctx.report["voice"] = {"voice": "Ryan"}
        return ctx

    def setup_dict(self, **cfg):
        merged = {"voice": "Ryan", "instructions": "be warm", "ref_f0_hz": 150.0, **cfg}
        return {"voice_cfg": merged, "ref_f0": merged["ref_f0_hz"], "asr_model": "asr1", "tts_model": "m1"}

    def run_step(self, ctx, fake, setup):
        made = {}

        def factory(url, voice, asr_model, language, instructions="", **kw):
            made.update(url=url, voice=voice, asr=asr_model, language=language, instructions=instructions)
            return fake

        with mock.patch.object(mv.voice_take, "VoiceStudioBackend", side_effect=factory), mock.patch.object(mv, "WORK_ROOT", self.tmp / "work"), \
                mock.patch.object(mv, "find_tool", return_value="/bin/true"), contextlib.redirect_stdout(io.StringIO()) as out:
            take = mv.step_voice(ctx, setup)
        return take, made, out.getvalue()

    def test_step_voice_fills_the_report_and_the_checks(self):
        ctx = self.make_ctx()
        take, made, printed = self.run_step(ctx, FakeVoice(), self.setup_dict())
        self.assertEqual(made["instructions"], "be warm")
        self.assertEqual(made["language"], "en")
        names = {c["name"]: c["ok"] for c in ctx.checks}
        self.assertTrue(names["voice accuracy"])
        self.assertTrue(names["voice continuity"])
        voice = ctx.report["voice"]
        self.assertEqual(voice["mode"], "one take")
        self.assertEqual(voice["seed"], 1)
        self.assertIs(voice["instructions_ignored"], True)
        self.assertEqual(len(voice["lines"]), 4)
        self.assertLessEqual({"f0_hz", "loudness_db", "wer", "cer", "ok"}, set(voice["lines"][0]))
        self.assertTrue(voice["continuity"]["ok"])
        self.assertIn("pause_rule", voice["take"])
        self.assertIn("[ok] line 0", printed)
        self.assertTrue((self.tmp / "work" / "_voice_probe.json").is_file())
        self.assertTrue(json.dumps(ctx.report))  # the report stays JSON-serialisable

    def test_voice_seed_flag_and_voices_json_seed(self):
        take, _made, _out = self.run_step(self.make_ctx("--voice-seed", "5"), FakeVoice(), self.setup_dict())
        self.assertEqual(take["seed"], 5)
        take2, _m, _o = self.run_step(self.make_ctx("--no-voice-cache"), FakeVoice(), self.setup_dict(seed=9))
        self.assertEqual(take2["seed"], 9)

    def test_voice_failure_becomes_a_plain_gate_error(self):
        fake = FakeVoice(pitch=lambda seed, i: 150.0 * (2 ** (6 / 12) if i == 2 else 1))
        ctx = self.make_ctx()
        with self.assertRaises(mv.GateError) as caught:
            self.run_step(ctx, fake, self.setup_dict())
        self.assertIn("steady", str(caught.exception))
        self.assertIn("--voice-seed", str(caught.exception))
        self.assertFalse(any(c["ok"] for c in ctx.checks if c["name"] == "voice take"))

    def test_step_join_writes_timings_and_the_narration_report(self):
        ctx = self.make_ctx()
        ctx.work.mkdir(parents=True)
        wav = ctx.work / "narration.wav"
        vt.write_wav(wav, tone(2.0))
        timings = [{"index": 0, "start": 0.1, "end": 1.0, "text": "a"}, {"index": 1, "start": 1.3, "end": 1.9, "text": "b"}]
        take = {"narration": wav, "timings": timings, "bounds": [0, 36000, 48000], "sr": SR, "seed": 3}
        with mock.patch.object(mv, "find_tool", return_value="ffprobe"), mock.patch.object(mv, "ffprobe_info", return_value={"duration": 2.0}), \
                contextlib.redirect_stdout(io.StringIO()):
            path, got, total = mv.step_join(ctx, take)
        self.assertEqual((path, got, total), (wav, timings, 2.0))
        self.assertEqual(json.loads((ctx.work / "timings.json").read_text()), timings)
        self.assertEqual(ctx.report["narration"]["line_durations"], [1.5, 0.5])
        self.assertEqual(ctx.report["narration"]["mode"], "one take")


class LoudnormHelperTests(unittest.TestCase):
    STDERR = """ffmpeg version 8.0 Copyright
[Parsed_loudnorm_1 @ 0x600001234]
{
\t"input_i" : "-20.36",
\t"input_tp" : "-4.68",
\t"input_lra" : "7.30",
\t"input_thresh" : "-30.84",
\t"output_i" : "-16.12",
\t"output_tp" : "-1.50",
\t"output_lra" : "5.90",
\t"output_thresh" : "-26.53",
\t"normalization_type" : "dynamic",
\t"target_offset" : "0.12"
}
size=N/A time=00:01:05.57 bitrate=N/A speed=250x
"""

    def test_parse(self):
        m = mv.parse_loudnorm_json(self.STDERR)
        self.assertEqual(m, {"input_i": -20.36, "input_tp": -4.68, "input_lra": 7.3, "input_thresh": -30.84, "target_offset": 0.12})

    def test_parse_nothing_or_garbage(self):
        self.assertIsNone(mv.parse_loudnorm_json(""))
        self.assertIsNone(mv.parse_loudnorm_json("no json here"))
        self.assertIsNone(mv.parse_loudnorm_json('{"input_i" : "x"}'))

    def test_silent_file_gives_minus_infinity_not_a_crash(self):
        m = mv.parse_loudnorm_json(self.STDERR.replace('"-20.36"', '"-inf"'))
        self.assertEqual(m["input_i"], float("-inf"))
        self.assertTrue(mv.loudness_problems(m))

    def test_filters(self):
        first = mv.loudnorm_filter(-1.5)
        self.assertTrue(first.startswith("highpass=f=70,acompressor=threshold=0.1:ratio=2.5:attack=5:release=90:knee=4:makeup=1.5,loudnorm="))
        self.assertIn("I=-14", first)
        self.assertIn("TP=-1.5", first)
        self.assertIn("print_format=json", first)
        second = mv.loudnorm_filter(-1.5, mv.parse_loudnorm_json(self.STDERR))
        self.assertIn("measured_I=-20.36", second)
        self.assertIn("measured_TP=-4.68", second)
        self.assertIn("measured_LRA=7.3", second)
        self.assertIn("measured_thresh=-30.84", second)
        self.assertIn("offset=0.12", second)
        self.assertTrue(second.endswith("linear=true"))
        self.assertNotIn("print_format", second)
        self.assertNotIn("acompressor", mv.loudness_analysis_filter())  # a finished file is measured as it is

    def test_limits(self):
        self.assertEqual(mv.loudness_problems({"input_i": -14.0, "input_tp": -1.5}), [])
        self.assertEqual(mv.loudness_problems({"input_i": -13.0, "input_tp": -1.0}), [])  # both limits are inclusive
        self.assertEqual(mv.loudness_problems({"input_i": -15.0, "input_tp": -2.0}), [])
        self.assertTrue(mv.loudness_problems({"input_i": -15.2, "input_tp": -2.0}))
        self.assertTrue(mv.loudness_problems({"input_i": -12.8, "input_tp": -2.0}))
        peak = mv.loudness_problems({"input_i": -14.0, "input_tp": -0.9})
        self.assertEqual(len(peak), 1)
        self.assertIn("true peak", peak[0])


class LoudnessStepTests(TmpDirTest):
    def block(self, i, tp):
        return ('{"input_i": "%s", "input_tp": "%s", "input_lra": "6.0", "input_thresh": "-25.0", "output_i": "0", "output_tp": "0", '
                '"output_lra": "0", "output_thresh": "0", "normalization_type": "linear", "target_offset": "0.1"}' % (i, tp))

    def run_step(self, measurements):
        ctx = mv.Ctx(mv.parse_args(["x.json"]))
        ctx.work = self.tmp
        calls = []
        queue = list(measurements)

        def fake_run(cmd, timeout, what, cwd=None):
            calls.append(cmd)
            if "print_format=json" in " ".join(cmd):
                i, tp = queue.pop(0)
                return subprocess.CompletedProcess(cmd, 0, "", self.block(i, tp))
            (self.tmp / "final-loudness.mp4").write_bytes(b"mp4")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with mock.patch.object(mv, "run_cmd", side_effect=fake_run), mock.patch.object(mv, "find_tool", return_value="ffmpeg"), \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                out = mv.step_loudness(ctx, self.tmp / "final-visuals.mp4")
            except mv.GateError as exc:
                return ctx, calls, exc
        return ctx, calls, out

    def test_two_passes_video_copied_aac_192k_and_the_output_is_measured(self):
        ctx, calls, out = self.run_step([("-20.4", "-4.7"), ("-14.1", "-1.6")])
        self.assertEqual(out, self.tmp / "final-loudness.mp4")
        self.assertEqual(len(calls), 3)  # measure the input, encode, measure the output
        joined = " ".join(calls[1])
        for needle in ("-c:v copy", "-c:a aac", "-b:a 192k", "-ar 48000", "linear=true", "measured_I=-20.4", "highpass=f=70"):
            self.assertIn(needle, joined)
        self.assertNotIn("acompressor", " ".join(calls[2]))  # the output is measured without the chain
        report = ctx.report["loudness"]
        self.assertTrue(report["ok"])
        self.assertAlmostEqual(report["integrated_lufs"], -14.1)
        self.assertAlmostEqual(report["true_peak_dbtp"], -1.6)
        self.assertTrue({c["name"]: c["ok"] for c in ctx.checks}["final loudness"])

    def test_true_peak_over_the_limit_retries_with_a_lower_target(self):
        ctx, calls, out = self.run_step([("-20.4", "-4.7"), ("-14.0", "-0.4"), ("-20.4", "-4.7"), ("-14.2", "-1.9")])
        self.assertEqual(out, self.tmp / "final-loudness.mp4")
        self.assertEqual(len(calls), 6)
        self.assertIn("TP=-2.5", " ".join(calls[3]))
        self.assertEqual(len(ctx.report["loudness"]["tries"]), 2)
        self.assertEqual(ctx.report["loudness"]["true_peak_target_dbtp"], -2.5)

    def test_missing_the_target_twice_fails_loudly(self):
        ctx, calls, error = self.run_step([("-20.4", "-4.7"), ("-17.0", "-3.0"), ("-20.4", "-4.7"), ("-17.0", "-3.0")])
        self.assertIsInstance(error, mv.GateError)
        self.assertIn("final loudness", str(error))
        self.assertFalse(ctx.report["loudness"]["ok"])

    def test_ffmpeg_failure_is_a_plain_gate_error(self):
        ctx = mv.Ctx(mv.parse_args(["x.json"]))
        ctx.work = self.tmp
        with mock.patch.object(mv, "run_cmd", return_value=subprocess.CompletedProcess([], 1, "", "boom")), \
                mock.patch.object(mv, "find_tool", return_value="ffmpeg"):
            with self.assertRaises(mv.GateError) as caught:
                mv.step_loudness(ctx, self.tmp / "v.mp4")
        self.assertIn("could not measure", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
