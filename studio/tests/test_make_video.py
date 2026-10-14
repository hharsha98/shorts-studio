"""Unit tests for studio/make_video.py: only the pure helper functions (no network, no ffmpeg).

Run from /Users/harsha/shorts-studio:
    python3 -m unittest discover -s studio/tests -t .
"""

import contextlib
import copy
import datetime
import io
import json
import math
import os
import sys
import tempfile
import time
import unicodedata
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import make_video as mv  # noqa: E402


def good_script():
    return {
        "id": "2026-10-14-en-fridge",
        "language": "en",
        "series": "How things work",
        "title": "How your fridge really works",
        "caption": "Your fridge moves heat out. Here is how.",
        "hashtags": ["#science", "#fridge", "#shorts"],
        "video_terms": ["refrigerator", "kitchen", "cooling", "heat pump"],
        "lines": [
            {"text": "Your fridge does not make cold.", "visual": None},
            {"text": "It moves heat out of the box.", "visual": {"type": "stat", "value": "-18 °C", "label": "Typical freezer"}},
        ],
        "sources": [
            {"title": "Refrigerator", "url": "https://en.wikipedia.org/wiki/Refrigerator"},
            {"title": "Vapor-compression", "url": "https://en.wikipedia.org/wiki/Vapor-compression_refrigeration"},
        ],
    }


def errors_of(script):
    return mv.validate_script(script)[0]


class ValidateScriptTests(unittest.TestCase):
    def test_good_script_passes_without_warnings(self):
        errors, warnings = mv.validate_script(good_script())
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_not_an_object(self):
        self.assertTrue(errors_of([1, 2]))

    def test_each_required_field_is_reported_when_missing(self):
        for key in ("id", "language", "series", "title", "caption", "hashtags", "video_terms", "lines", "sources"):
            s = good_script()
            del s[key]
            self.assertTrue(any(key in e for e in errors_of(s)), key)

    def test_id_rules(self):
        for bad in ("Fridge", "has space", "../x", "a_b", "", "2026/10"):
            s = good_script()
            s["id"] = bad
            self.assertTrue(any(e.startswith("id ") for e in errors_of(s)), bad)
        for good in ("_test-en", "2026-10-14-de-kuehlschrank", "abc"):
            s = good_script()
            s["id"] = good
            self.assertEqual(errors_of(s), [], good)

    def test_language_must_be_en_or_de(self):
        s = good_script()
        s["language"] = "fr"
        self.assertTrue(any("language" in e for e in errors_of(s)))

    def test_title_limit_70(self):
        # YouTube cuts longer titles off in the Shorts feed (the upload pack shows the title)
        s = good_script()
        s["title"] = "x" * 70
        self.assertEqual(errors_of(s), [])
        s["title"] = "x" * 71
        self.assertTrue(any("title" in e and "70" in e for e in errors_of(s)))

    def test_long_caption_only_warns(self):
        s = good_script()
        s["caption"] = "One. Two. Three. Four."
        errors, warnings = mv.validate_script(s)
        self.assertEqual(errors, [])
        self.assertTrue(any("caption" in w for w in warnings))

    def test_hashtag_count_and_shape(self):
        s = good_script()
        s["hashtags"] = ["#a", "#b"]
        self.assertTrue(any("hashtags" in e for e in errors_of(s)))
        s["hashtags"] = ["#a"] * 9
        self.assertTrue(any("hashtags" in e for e in errors_of(s)))
        s["hashtags"] = ["#a", "#b", "c"]
        self.assertTrue(any("hashtags[2]" in e for e in errors_of(s)))

    def test_video_terms_count_and_characters(self):
        s = good_script()
        s["video_terms"] = ["a", "b", "c"]
        self.assertTrue(any("video_terms" in e for e in errors_of(s)))
        s["video_terms"] = ["term"] * 11
        self.assertTrue(any("video_terms" in e for e in errors_of(s)))
        for bad in ("Küche", "4k video", "a,b", "", "   ", "wow!"):
            s["video_terms"] = ["one", "two", "three", bad]
            self.assertTrue(any("video_terms[3]" in e for e in errors_of(s)), bad)
        s["video_terms"] = ["hot-air balloon", "ice cube", "Fridge", "x-ray machine"]
        self.assertEqual(errors_of(s), [])

    def test_line_text_rules(self):
        s = good_script()
        s["lines"][0]["text"] = "   "
        self.assertTrue(any("lines[0].text" in e for e in errors_of(s)))
        s["lines"][0]["text"] = "x" * 400
        self.assertEqual(errors_of(s), [])
        s["lines"][0]["text"] = "x" * 401
        self.assertTrue(any("lines[0].text" in e and "401" in e for e in errors_of(s)))
        s["lines"] = []
        self.assertTrue(any("lines" in e for e in errors_of(s)))
        s["lines"] = ["just a string"]
        self.assertTrue(any("lines[0]" in e for e in errors_of(s)))

    def test_digits_in_line_text_warn_but_do_not_fail(self):
        s = good_script()
        s["lines"][0]["text"] = "It is 18 degrees cold."
        errors, warnings = mv.validate_script(s)
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("lines[0]", warnings[0])

    def test_sources_need_two_with_urls(self):
        s = good_script()
        s["sources"] = s["sources"][:1]
        self.assertTrue(any("sources" in e for e in errors_of(s)))
        s = good_script()
        s["sources"][1]["url"] = "ftp://nope"
        self.assertTrue(any("sources[1].url" in e for e in errors_of(s)))

    def test_source_urls_must_be_https_with_one_message(self):
        messages = set()
        for bad in ("http://example.com/a", "ftp://x", "https://", "https://a b", "example.com", "https://example.com/a\n", ""):
            s = good_script()
            s["sources"][0]["url"] = bad
            found = [e for e in errors_of(s) if e.startswith("sources[0].url")]
            self.assertEqual(len(found), 1, repr(bad))
            messages.add(found[0].split(" (got")[0])
        self.assertEqual(messages, {"sources[0].url must start with https:// and contain no spaces"})

    def test_trailing_newline_is_rejected_everywhere(self):
        s = good_script()
        s["id"] = "2026-10-14-en-fridge\n"
        self.assertTrue(any(e.startswith("id ") for e in errors_of(s)))
        s = good_script()
        s["video_terms"][0] = "refrigerator\n"
        self.assertTrue(any("video_terms[0]" in e for e in errors_of(s)))
        s = good_script()
        s["sources"][1]["url"] = "https://en.wikipedia.org/wiki/Refrigerator\n"
        self.assertTrue(any("sources[1].url" in e for e in errors_of(s)))
        s = good_script()
        s["hashtags"][0] = "#science\n"
        self.assertTrue(any("hashtags[0]" in e for e in errors_of(s)))

    def test_long_sentence_warns_but_does_not_fail(self):
        s = good_script()
        s["lines"][0]["text"] = ("word " * 28).strip() + "."  # 139 characters + dot = 140: allowed
        self.assertEqual(mv.validate_script(s)[1], [])
        s["lines"][0]["text"] = ("word " * 29).strip() + "."  # 145 characters
        errors, warnings = mv.validate_script(s)
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("lines[0]", warnings[0])
        self.assertIn("140", warnings[0])

    def test_long_text_made_of_short_sentences_does_not_warn(self):
        s = good_script()
        s["lines"][0]["text"] = " ".join(["This is a short sentence."] * 8)  # 200+ characters in total
        self.assertEqual(mv.validate_script(s)[1], [])
        s = good_script()
        s["sources"][0]["title"] = ""
        self.assertTrue(any("sources[0].title" in e for e in errors_of(s)))

    # ---- visuals -------------------------------------------------------------------

    def visual_errors(self, visual):
        s = good_script()
        s["lines"][0]["visual"] = visual
        return errors_of(s)

    def test_flow_visual(self):
        ok = {"type": "flow", "title": "Heat path", "steps": ["Inside", "Pipe", "Coil"]}
        self.assertEqual(self.visual_errors(ok), [])
        self.assertTrue(self.visual_errors({**ok, "steps": ["only one"]}))
        self.assertTrue(self.visual_errors({**ok, "steps": ["a"] * 6}))
        self.assertTrue(self.visual_errors({**ok, "steps": ["a", "x" * 23]}))
        self.assertTrue(self.visual_errors({**ok, "title": "t" * 33}))
        self.assertEqual(self.visual_errors({**ok, "title": "t" * 32, "steps": ["x" * 22, "b"]}), [])

    def test_stat_visual(self):
        ok = {"type": "stat", "value": "-18 °C", "label": "Freezer"}
        self.assertEqual(self.visual_errors(ok), [])
        self.assertTrue(self.visual_errors({**ok, "value": "x" * 11}))
        self.assertTrue(self.visual_errors({**ok, "label": "x" * 41}))
        self.assertTrue(self.visual_errors({"type": "stat", "value": "5"}))

    def test_compare_visual(self):
        side = {"heading": "Old", "text": "Uses more power"}
        ok = {"type": "compare", "title": "Old vs new", "left": side, "right": side}
        self.assertEqual(self.visual_errors(ok), [])
        self.assertTrue(self.visual_errors({**ok, "left": {"heading": "h" * 13, "text": "t"}}))
        self.assertTrue(self.visual_errors({**ok, "right": {"heading": "h", "text": "t" * 49}}))
        broken = dict(ok)
        del broken["right"]
        self.assertTrue(self.visual_errors(broken))

    def test_unknown_or_non_object_visual(self):
        self.assertTrue(self.visual_errors({"type": "pie"}))
        self.assertTrue(self.visual_errors("stat"))
        self.assertEqual(self.visual_errors(None), [])


class WerTests(unittest.TestCase):
    def test_identical_is_zero(self):
        self.assertEqual(mv.word_error_rate("Your fridge moves heat.", "your fridge moves heat"), 0.0)

    def test_one_substitution_in_ten_words(self):
        ref = "one two three four five six seven eight nine ten"
        hyp = "one two three four five six seven eight nine tin"
        self.assertAlmostEqual(mv.word_error_rate(ref, hyp), 0.1)

    def test_deletion_and_insertion(self):
        self.assertAlmostEqual(mv.word_error_rate("a b c d", "a b d"), 0.25)
        self.assertAlmostEqual(mv.word_error_rate("a b c d", "a b x c d"), 0.25)

    def test_empty_reference(self):
        self.assertEqual(mv.word_error_rate("", ""), 0.0)
        self.assertEqual(mv.word_error_rate("...", "something"), 1.0)

    def test_everything_wrong_is_one(self):
        self.assertEqual(mv.word_error_rate("a b c", "x y z"), 1.0)

    def test_punctuation_and_case_are_ignored(self):
        self.assertEqual(mv.word_error_rate("Doesn't it?", "DOESN'T IT"), 0.0)
        self.assertEqual(mv.word_error_rate("Hello, world!", "hello world"), 0.0)

    def test_nfc_normalisation_for_umlauts(self):
        composed = "Kühlschrank für Wärme"
        decomposed = unicodedata.normalize("NFD", composed)
        self.assertNotEqual(composed, decomposed)
        self.assertEqual(mv.word_error_rate(composed, decomposed), 0.0)

    def test_dash_equals_space(self):
        self.assertEqual(mv.word_error_rate("an ice-cold drink", "an ice cold drink"), 0.0)

    def test_threshold_depends_on_word_count(self):
        self.assertEqual(mv.wer_threshold("one two three four five"), 0.15)
        self.assertEqual(mv.wer_threshold("one two three four"), 0.34)
        self.assertEqual(mv.wer_threshold("Hi."), 0.34)

    def test_levenshtein(self):
        self.assertEqual(mv.levenshtein([], []), 0)
        self.assertEqual(mv.levenshtein(["a"], []), 1)
        self.assertEqual(mv.levenshtein(list("kitten"), list("sitting")), 3)

    def test_five_words_one_wrong_exceeds_limit(self):
        wer = mv.word_error_rate("one two three four five", "one two three four six")
        self.assertGreater(wer, mv.wer_threshold("one two three four five"))


class LengthGateTests(unittest.TestCase):
    def test_inside_range_including_edges(self):
        for d in (61.0, 68.0, 75.0):
            ok, msg = mv.length_gate(d, 150, 61, 75)
            self.assertTrue(ok, d)
            self.assertIn("inside", msg)

    def test_too_short_says_how_many_words_to_add(self):
        ok, msg = mv.length_gate(52.0, 130, 61, 75)  # 2.5 words/s, aim for 63 s -> 11 s * 2.5
        self.assertFalse(ok)
        self.assertIn("too short", msg)
        self.assertIn("52.0 s", msg)
        self.assertIn("130 words", msg)
        self.assertIn("2.50 words/s", msg)
        self.assertIn("Add about 28 words", msg)

    def test_too_long_says_how_many_words_to_remove(self):
        ok, msg = mv.length_gate(80.0, 200, 61, 75)  # aim for 73 s -> 7 s * 2.5
        self.assertFalse(ok)
        self.assertIn("too long", msg)
        self.assertIn("Remove about 18 words", msg)

    def test_zero_minimum_accepts_short_narration(self):
        ok, _ = mv.length_gate(16.2, 52, 0, 999)
        self.assertTrue(ok)

    def test_at_least_one_word_is_suggested(self):
        ok, msg = mv.length_gate(60.9, 150, 61, 75)
        self.assertFalse(ok)
        self.assertRegex(msg, r"Add about [1-9]\d* words")


SRT_GOOD = """1
00:00:00,000 --> 00:00:02,500
Your fridge does not make cold.

2
00:00:02,500 --> 00:00:05,000
It moves heat out
of the box.

3
00:00:05,100 --> 00:00:07,000
Last cue without trailing blank line
"""


class SrtTests(unittest.TestCase):
    def test_parse(self):
        cues = mv.parse_srt(SRT_GOOD)
        self.assertEqual(len(cues), 3)
        self.assertEqual(cues[0]["start"], 0.0)
        self.assertEqual(cues[1]["start"], 2.5)
        self.assertEqual(cues[1]["end"], 5.0)
        self.assertEqual(cues[1]["text"], "It moves heat out of the box.")
        self.assertEqual(cues[2]["end"], 7.0)

    def test_parse_windows_line_endings(self):
        self.assertEqual(len(mv.parse_srt(SRT_GOOD.replace("\n", "\r\n"))), 3)

    def test_good_file_has_no_problems(self):
        self.assertEqual(mv.srt_problems(mv.parse_srt(SRT_GOOD)), [])

    def test_empty_file_is_a_problem(self):
        self.assertTrue(mv.srt_problems(mv.parse_srt("")))

    def test_zero_length_cue(self):
        bad = "1\n00:00:00,000 --> 00:00:00,000\nx\n\n2\n00:00:01,000 --> 00:00:02,000\ny\n"
        problems = mv.srt_problems(mv.parse_srt(bad))
        self.assertTrue(any("zero length" in p for p in problems))

    def test_overlapping_cues(self):
        bad = "1\n00:00:00,000 --> 00:00:03,000\nx\n\n2\n00:00:02,000 --> 00:00:04,000\ny\n"
        problems = mv.srt_problems(mv.parse_srt(bad))
        self.assertTrue(any("overlap" in p for p in problems))

    def test_non_increasing_start_times(self):
        bad = "1\n00:00:05,000 --> 00:00:06,000\nx\n\n2\n00:00:01,000 --> 00:00:02,000\ny\n"
        problems = mv.srt_problems(mv.parse_srt(bad))
        self.assertTrue(any("not after the previous cue" in p for p in problems))

    def test_issues_carry_the_start_second_and_match_the_problem_texts(self):
        cues = mv.parse_srt("1\n00:00:01,000 --> 00:00:01,000\nIt\n\n2\n00:00:01,000 --> 00:00:02,000\nmoves\n")
        issues = mv.srt_issues(cues)
        self.assertEqual([start for start, _ in issues], [1.0, 1.0])
        self.assertEqual([msg for _, msg in issues], mv.srt_problems(cues))

    def test_timing_hint_names_the_line_and_the_file_to_delete(self):
        timings = [{"index": 0, "start": 0.0, "end": 2.0}, {"index": 1, "start": 2.25, "end": 6.0}]
        self.assertEqual(mv.lines_at_seconds([2.14], timings), [0])  # a gap belongs to the line before it
        self.assertEqual(mv.lines_at_seconds([2.3, 5.0, 2.4], timings), [1])
        hint = mv.subtitle_timing_hint([2.14, 4.0], timings, Path("/w/id"))
        self.assertIn("line(s) 0, 1", hint)
        self.assertIn("/w/id/lines/00.json", hint)
        self.assertIn("/w/id/lines/01.json", hint)
        self.assertIn("running again will not help", hint)
        self.assertEqual(mv.subtitle_timing_hint([], timings, Path("/w/id")), "")

    def test_touching_cues_are_fine(self):
        ok = "1\n00:00:00,000 --> 00:00:01,000\nx\n\n2\n00:00:01,000 --> 00:00:02,000\ny\n"
        self.assertEqual(mv.srt_problems(mv.parse_srt(ok)), [])


class MptHelperTests(unittest.TestCase):
    def test_command_for_pexels(self):
        cmd = mv.build_mpt_command("/bin/uv", "Line one. Line two.", ["a b", "c"], Path("/w/narration.wav"), "T-ID")
        self.assertEqual(cmd[:4], ["/bin/uv", "run", "python", "cli.py"])
        pairs = dict(zip(cmd[4:], cmd[5:]))
        self.assertEqual(pairs["--video-script"], "Line one. Line two.")
        self.assertEqual(pairs["--video-terms"], "a b,c")
        self.assertEqual(pairs["--custom-audio-file"], "/w/narration.wav")
        self.assertEqual(pairs["--bgm-type"], "none")
        self.assertEqual(pairs["--font-name"], "BeVietnamPro-Bold.ttf")
        self.assertEqual(pairs["--subtitle-position"], "custom")
        self.assertIn("--custom-position", pairs)
        self.assertTrue(0 < float(pairs["--custom-position"]) < 100)
        self.assertIn("--subtitle-enabled", cmd)
        self.assertIn("--no-subtitle-background-enabled", cmd)  # a background saved by the MPT WebUI must never apply
        self.assertNotIn("--subtitle-background-enabled", cmd)
        self.assertEqual(pairs["--subtitle-display-mode"], "word_by_word")
        self.assertEqual(pairs["--subtitle-animation"], "pop_spring")
        self.assertEqual(pairs["--font-size"], str(mv.CAPTION_FONT_MAX))
        self.assertEqual(pairs["--stroke-width"], str(mv.caption_stroke_width(mv.CAPTION_FONT_MAX)))
        self.assertEqual(pairs["--stroke-color"], "#000000")
        self.assertEqual(pairs["--text-fore-color"], "#FFFFFF")
        self.assertEqual(pairs["--video-aspect"], "9:16")
        self.assertEqual(pairs["--task-id"], "T-ID")
        self.assertNotIn("--video-source", cmd)
        self.assertNotIn("--video-materials", cmd)

    def test_command_for_local_materials(self):
        cmd = mv.build_mpt_command("uv", "x", ["t"], Path("/n.wav"), "id", [Path("/m/a.mp4"), Path("/m/b.mp4")])
        pairs = dict(zip(cmd[4:], cmd[5:]))
        self.assertEqual(pairs["--video-source"], "local")
        self.assertEqual(pairs["--video-materials"], "/m/a.mp4,/m/b.mp4")

    def test_command_passes_the_footage_source(self):
        cmd = mv.build_mpt_command("uv", "x", ["t"], Path("/n.wav"), "id", source="pixabay")
        pairs = dict(zip(cmd[4:], cmd[5:]))
        self.assertEqual(pairs["--video-source"], "pixabay")
        self.assertNotIn("--video-materials", cmd)

    def test_local_materials_win_over_a_footage_source(self):
        cmd = mv.build_mpt_command("uv", "x", ["t"], Path("/n.wav"), "id", [Path("/m/a.mp4")], source="pexels")
        self.assertEqual(dict(zip(cmd[4:], cmd[5:]))["--video-source"], "local")
        self.assertEqual(cmd.count("--video-source"), 1)

    def test_pick_footage_source(self):
        self.assertEqual(mv.pick_footage_source({"pexels_api_keys": ["p"], "pixabay_api_keys": ["x"]}), "pexels")
        self.assertEqual(mv.pick_footage_source({"pexels_api_keys": [], "pixabay_api_keys": ["x"]}), "pixabay")
        self.assertEqual(mv.pick_footage_source({"pexels_api_keys": ["  "], "pixabay_api_keys": ["x"]}), "pixabay")  # blank key ignored
        self.assertIsNone(mv.pick_footage_source({"pexels_api_keys": [""], "pixabay_api_keys": []}))
        self.assertIsNone(mv.pick_footage_source({}))

    def test_command_takes_the_given_caption_size(self):
        cmd = mv.build_mpt_command("uv", "x", ["t"], Path("/n.wav"), "id", font_size=90, stroke_width=7)
        pairs = dict(zip(cmd[4:], cmd[5:]))
        self.assertEqual(pairs["--font-size"], "90")
        self.assertEqual(pairs["--stroke-width"], "7")

    def test_command_takes_the_given_caption_position(self):
        cmd = mv.build_mpt_command("uv", "x", ["t"], Path("/n.wav"), "id", position_percent=74.57)
        pairs = dict(zip(cmd[4:], cmd[5:]))
        self.assertEqual(pairs["--custom-position"], "74.57")

    def test_script_text_keeps_only_sentence_punctuation_in_sentence_mode(self):
        texts = ["Then a compressor squeezes it, and the heat escapes: that is why; it works.", "Is it cold? Yes!"]
        self.assertEqual(
            mv.mpt_script_text(texts, subtitle_mode="sentence"),
            "Then a compressor squeezes it and the heat escapes that is why it works. Is it cold? Yes!",
        )

    def test_script_text_is_kept_as_written_in_word_by_word_mode(self):
        # MPT's whisper path never reads the script in word_by_word mode (no subtitle.correct step)
        texts = ["Then a compressor squeezes it, and the heat escapes: that is why; it works.", "Is  it cold?\n Yes!"]
        self.assertEqual(
            mv.mpt_script_text(texts),
            "Then a compressor squeezes it, and the heat escapes: that is why; it works. Is it cold? Yes!",
        )
        self.assertEqual(mv.mpt_script_text(["First line", "Second line."]), "First line. Second line.")

    def test_script_text_adds_a_period_when_a_line_has_none(self):
        self.assertEqual(mv.mpt_script_text(["First line", "Second line."], subtitle_mode="sentence"), "First line. Second line.")

    def test_script_text_handles_dashes_ellipsis_and_number_commas(self):
        sentence = lambda t: mv.mpt_script_text([t], subtitle_mode="sentence")  # noqa: E731
        self.assertEqual(sentence("Wait … really – yes"), "Wait really yes.")
        self.assertEqual(sentence("It took 1,000 years, maybe."), "It took 1,000 years maybe.")
        self.assertEqual(sentence("An ice-cold drink."), "An ice-cold drink.")

    def test_script_text_has_no_comma_split_points(self):
        text = mv.mpt_script_text(["Dann presst ein Kompressor es zusammen, und die Wärme entweicht."], subtitle_mode="sentence")
        self.assertNotIn(",", text)
        self.assertEqual(text, "Dann presst ein Kompressor es zusammen und die Wärme entweicht.")

    def test_parse_result_takes_the_json_line_after_the_logs(self):
        payload = {"task_id": "abc", "result": {"videos": ["/v/final-1.mp4"], "subtitle_path": "/v/subtitle.srt", "warnings": None}}
        lines = ["2026-10-13 INFO | start CLI task", '{"not": "ours"}', json.dumps(payload), ""]
        self.assertEqual(mv.parse_mpt_result(lines), payload)

    def test_parse_result_none_when_missing(self):
        self.assertIsNone(mv.parse_mpt_result(["just logs", "{broken json", '{"result": 5}']))

    def test_strip_ansi(self):
        self.assertEqual(mv.strip_ansi("\x1b[32mINFO\x1b[0m hello"), "INFO hello")

    def test_notes_collect_mismatch_and_extra_lines(self):
        log = "\n".join([
            "\x1b[33mWARNING\x1b[0m | Mismatch - Script: hello, Subtitle: hullo",
            "INFO | Subtitle is correct",
            "WARNING | Extra script line: goodbye",
        ])
        notes = mv.collect_mpt_notes(log)
        self.assertEqual(len(notes), 2)
        self.assertIn("Mismatch - Script: hello", notes[0])
        self.assertNotIn("\x1b", notes[0])
        self.assertIn("Extra script line: goodbye", notes[1])

    def test_whisper_language_detection(self):
        log = "INFO | detected language: 'de', probability: 0.98"
        self.assertEqual(mv.detect_whisper_language(log), ("de", 0.98))
        self.assertIsNone(mv.detect_whisper_language("nothing here"))

    def test_whisper_language_check(self):
        ok, _ = mv.check_whisper_language("detected language: 'en', probability: 0.99", "en")
        self.assertTrue(ok)
        ok, msg = mv.check_whisper_language("detected language: 'de', probability: 0.97", "en")
        self.assertFalse(ok)
        self.assertIn("'de'", msg)
        ok, _ = mv.check_whisper_language("detected language: 'nl', probability: 0.31", "de")
        self.assertTrue(ok)  # unsure guess is not "clearly different"
        ok, _ = mv.check_whisper_language("no language line", "en")
        self.assertTrue(ok)

    def test_bgm_detection(self):
        self.assertEqual(mv.find_bgm_usage("INFO | combining video\nINFO | video saved: x.mp4", {"bgm_type": "", "bgm_file": ""}), [])
        self.assertTrue(mv.find_bgm_usage("INFO | using ./resource/songs/output000.mp3"))
        self.assertTrue(mv.find_bgm_usage("ERROR | failed to mix background music: type=random"))
        self.assertTrue(mv.find_bgm_usage("ok", {"bgm_type": "random"}))
        self.assertTrue(mv.find_bgm_usage("ok", {"bgm_type": "", "bgm_file": "/x/song.mp3"}))
        # our own "# command" header line must not count
        self.assertEqual(mv.find_bgm_usage("# uv run --bgm-file resource/songs/x.mp3"), [])


class CreditsTests(unittest.TestCase):
    def test_pexels_credit_line_format(self):
        recs = [{"provider": "pexels", "local_file": "a.mp4", "source_page": "https://www.pexels.com/video/a-1/",
                 "creator": {"id": "7", "name": "Jane Doe", "profile_page": "https://www.pexels.com/@jane"}}]
        lines, notes = mv.build_credits(recs)
        self.assertEqual(lines, ["Videos by Jane Doe on Pexels (pexels.com): https://www.pexels.com/video/a-1/"])
        self.assertEqual(notes, [])

    def test_missing_creator_falls_back_to_page_url_with_a_note(self):
        recs = [{"provider": "pexels", "local_file": "a.mp4", "source_page": "https://www.pexels.com/video/a-1/"}]
        lines, notes = mv.build_credits(recs)
        self.assertEqual(lines, ["Video on Pexels (pexels.com): https://www.pexels.com/video/a-1/"])
        self.assertTrue(any("no creator" in n for n in notes))

    def test_duplicates_and_local_are_dropped(self):
        rec = {"provider": "pexels", "source_page": "https://www.pexels.com/video/a-1/", "creator": {"name": "Jane"}}
        lines, _ = mv.build_credits([rec, dict(rec), {"provider": "local", "local_file": "x.mp4"}, {"provider": ""}])
        self.assertEqual(len(lines), 1)

    def test_only_used_providers_are_credited(self):
        recs = [
            {"provider": "pexels", "source_page": "https://www.pexels.com/video/a-1/", "creator": {"name": "Jane"}},
            {"provider": "pixabay", "source_page": "https://pixabay.com/videos/b-2/", "creator": {"name": "Max"}},
        ]
        lines, _ = mv.build_credits(recs)
        self.assertEqual(len(lines), 2)
        self.assertIn("Pixabay (pixabay.com)", lines[1])

    def test_no_records_no_credits(self):
        self.assertEqual(mv.build_credits([]), ([], []))
        self.assertEqual(mv.build_credits(None), ([], []))


class NamingAndCaptionTests(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(mv.slug_from_id("2026-10-14-en-fridge", "en"), "fridge")
        self.assertEqual(mv.slug_from_id("2026-10-14-de-kuehlschrank-und-mehr", "de"), "kuehlschrank-und-mehr")
        self.assertEqual(mv.slug_from_id("fridge", "en"), "fridge")
        self.assertEqual(mv.slug_from_id("en-fridge", "en"), "fridge")
        self.assertEqual(mv.slug_from_id("_test-en", "en"), "test-en")

    def test_review_folder_uses_date_from_id_else_today(self):
        today = datetime.date(2026, 10, 13)
        self.assertEqual(mv.review_folder_name({"id": "2026-10-14-en-fridge", "language": "en"}, today), "2026-10-14-en-fridge")
        self.assertEqual(mv.review_folder_name({"id": "2026-10-20-de-kuehlschrank", "language": "de"}, today), "2026-10-20-de-kuehlschrank")
        self.assertEqual(mv.review_folder_name({"id": "_test-en", "language": "en"}, today), "2026-10-13-en-test-en")
        self.assertEqual(mv.review_folder_name({"id": "2026-13-45-en-x", "language": "en"}, today), "2026-10-13-en-2026-13-45-en-x")

    def test_caption_layout_english(self):
        text = mv.build_caption(good_script(), ["Videos by Jane on Pexels (pexels.com): https://p/1"])
        expected = (
            "How your fridge really works\n\n"
            "Your fridge moves heat out. Here is how.\n\n"
            "#science #fridge #shorts\n\n"
            "AI voice. Script written with AI assistance and fact-checked.\n"
            "Videos by Jane on Pexels (pexels.com): https://p/1\n\n"
            "Sources:\n"
            "Refrigerator – https://en.wikipedia.org/wiki/Refrigerator\n"
            "Vapor-compression – https://en.wikipedia.org/wiki/Vapor-compression_refrigeration\n"
        )
        self.assertEqual(text, expected)

    def test_caption_german_without_credits(self):
        s = good_script()
        s["language"] = "de"
        text = mv.build_caption(s, [])
        self.assertIn("\n\nKI-Stimme. Skript mit KI-Unterstützung geschrieben und faktengeprüft.\n\nQuellen:\n", text)
        self.assertNotIn("Sources:", text)
        self.assertNotIn("Pexels", text)


class FinalChecksTests(unittest.TestCase):
    def results(self, info, min_seconds=61):
        return {name: (ok, detail) for name, ok, detail in mv.check_final_info(info, min_seconds)}

    def test_all_good(self):
        r = self.results({"duration": 65.0, "width": 1080, "height": 1920, "has_audio": True})
        self.assertTrue(all(ok for ok, _ in r.values()))

    def test_duration_tolerance_is_half_a_second(self):
        base = {"width": 1080, "height": 1920, "has_audio": True}
        self.assertTrue(self.results({**base, "duration": 60.5})["final duration"][0])
        self.assertFalse(self.results({**base, "duration": 60.4})["final duration"][0])

    def test_min_zero_skips_duration_check(self):
        r = self.results({"duration": 3.0, "width": 1080, "height": 1920, "has_audio": True}, min_seconds=0)
        self.assertTrue(r["final duration"][0])

    def test_wrong_size_and_missing_audio(self):
        r = self.results({"duration": 65.0, "width": 1920, "height": 1080, "has_audio": False})
        self.assertFalse(r["final size"][0])
        self.assertFalse(r["final audio"][0])


class MiscTests(unittest.TestCase):
    def test_tts_engine_check(self):
        good = {"active": "mlx-audio", "active_model": "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-6bit"}
        self.assertIsNone(mv.check_tts_engine(good))
        self.assertIn("MLX-Audio + Qwen3-TTS CustomVoice", mv.check_tts_engine({**good, "active": "omnivoice"}))
        self.assertTrue(mv.check_tts_engine({**good, "active_model": "mlx-community/Kokoro-82M"}))
        self.assertTrue(mv.check_tts_engine({"active": "mlx-audio", "active_model": None}))
        self.assertIsNone(mv.check_tts_engine({"active": "mlx-audio", "active_model": {"id": "Qwen3-TTS-12Hz-1.7B-CustomVoice"}}))

    def test_multipart_body(self):
        body, ctype = mv.build_multipart({"model": "m", "language": "de"}, "file", "a.wav", b"RIFFDATA", "audio/wav")
        boundary = ctype.split("boundary=")[1]
        self.assertTrue(ctype.startswith("multipart/form-data"))
        self.assertIn(b'name="model"\r\n\r\nm\r\n', body)
        self.assertIn(b'name="file"; filename="a.wav"', body)
        self.assertIn(b"RIFFDATA", body)
        self.assertTrue(body.endswith(f"--{boundary}--\r\n".encode()))

    def test_newest_media_scripts_dir_is_picked_by_version_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for version, has_speak in (("1.0.9", True), ("1.0.10", True), ("2.0.0", False)):
                folder = base / version / "skills" / "media-studio" / "scripts"
                folder.mkdir(parents=True)
                if has_speak:
                    (folder / "speak.mjs").write_text("//")
            picked = mv.pick_media_scripts_dir(base)
            self.assertEqual(picked.parents[2].name, "1.0.10")

    def test_missing_media_scripts_dir_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(mv.GateError):
                mv.pick_media_scripts_dir(Path(tmp))


FONT_FILE = Path(__file__).resolve().parents[2] / "MoneyPrinterTurbo" / "resource" / "fonts" / "BeVietnamPro-Bold.ttf"


class FormatSrtTests(unittest.TestCase):
    def test_round_trip_and_clean_separators(self):
        mpt_style = "1\n00:00:00,000 --> 00:00:00,240\nYour\n        \n2\n00:00:00,240 --> 00:01:01,520\nfridge\n        \n"
        cues = mv.parse_srt(mpt_style)
        text = mv.format_srt(cues)
        self.assertEqual(text, "1\n00:00:00,000 --> 00:00:00,240\nYour\n\n2\n00:00:00,240 --> 00:01:01,520\nfridge\n\n")
        self.assertEqual(mv.parse_srt(text), cues)
        self.assertNotIn("        ", text)

    def test_milliseconds_do_not_drift_or_overflow(self):
        text = mv.format_srt([{"start": 0.9996, "end": 3599.9999, "text": "x"}])
        self.assertIn("00:00:01,000 --> 01:00:00,000", text)


class SrtAccuracyTests(unittest.TestCase):
    def cues(self, *texts):
        return [{"index": k + 1, "start": k * 0.4, "end": k * 0.4 + 0.3, "text": t} for k, t in enumerate(texts)]

    def test_word_cues_match_the_script(self):
        script = ["Your fridge does not make cold.", "It moves heat out."]
        cues = self.cues("Your", "fridge", "does", "not", "make", "cold.", "It", "moves", "heat", "out.")
        ok, wer, msg, diffs = mv.check_srt_accuracy(cues, script)
        self.assertTrue(ok)
        self.assertEqual(wer, 0.0)
        self.assertEqual(diffs, [])
        self.assertIn("0.000", msg)

    def test_wer_above_limit_fails_and_lists_the_words(self):
        # colours, not number words: numbers are one "<num>" in this check (see NumberToleranceTests)
        script = ["red blue green yellow pink black white brown grey gold"]
        cues = self.cues("red", "blue", "screen", "yellow", "pink", "black", "white", "brown", "grey", "gold", "silver")  # 2 errors in 10
        ok, wer, msg, diffs = mv.check_srt_accuracy(cues, script)
        self.assertFalse(ok)
        self.assertAlmostEqual(wer, 0.2)
        self.assertIn('script "green" -> subtitle "screen"', msg)
        self.assertIn('extra word(s) in the subtitle: "silver"', msg)
        self.assertEqual(len(diffs), 2)

    def test_limit_is_inclusive_and_default_is_ten_percent(self):
        self.assertEqual(mv.SRT_WER_LIMIT, 0.10)
        script = ["red blue green yellow pink black white brown grey gold"]
        cues = self.cues("red", "blue", "green", "yellow", "pink", "black", "white", "brown", "grey", "gild")  # exactly 0.1
        ok, wer, _, _ = mv.check_srt_accuracy(cues, script)
        self.assertAlmostEqual(wer, 0.1)
        self.assertTrue(ok)

    def test_punctuation_case_and_dashes_do_not_count(self):
        ok, wer, _, _ = mv.check_srt_accuracy(self.cues("Noise", "cancelling", "Kühlschrank,"), ["Noise-cancelling kühlschrank"])
        self.assertTrue(ok)
        self.assertEqual(wer, 0.0)

    def test_no_cues_fails(self):
        ok, wer, _, _ = mv.check_srt_accuracy([], ["Some words here."])
        self.assertFalse(ok)
        self.assertEqual(wer, 1.0)

    def test_word_differences_shapes(self):
        self.assertEqual(mv.word_differences("a b c", "a b c"), [])
        self.assertEqual(mv.word_differences("a b c", "a c"), ['script word(s) missing in the subtitle: "b"'])
        self.assertEqual(mv.word_differences("a c", "a b c"), ['extra word(s) in the subtitle: "b"'])
        many = mv.word_differences(" ".join(["x"] * 3 * 40), " ".join(["x", "y", "z"] * 40), limit=5)
        self.assertEqual(len(many), 6)
        self.assertTrue(many[-1].startswith("... and "))

    def test_first_caption_problem(self):
        self.assertIsNone(mv.first_caption_problem([{"start": 0.3, "end": 0.6, "text": "x", "index": 1}]))
        self.assertIn("2.50 s", mv.first_caption_problem([{"start": 2.5, "end": 3.0, "text": "x", "index": 1}]))
        self.assertTrue(mv.first_caption_problem([]))


@unittest.skipUnless(FONT_FILE.is_file(), "MoneyPrinterTurbo font not found")
class CaptionStyleTests(unittest.TestCase):
    def test_font_measure_matches_known_widths(self):
        # Measured once with Pillow: the advance sum is within a few pixels of the ink width.
        measure = mv.FontMeasure(FONT_FILE.read_bytes())
        for word, pillow_px_at_100 in (("Kühlschrankkompressor", 1234), ("Flugzeugtriebwerken", 1078), ("refrigerant", 560)):
            width = measure.text_width(word, 100)
            self.assertAlmostEqual(width / pillow_px_at_100, 1.0, delta=0.01, msg=word)
        self.assertEqual(measure.text_width("", 100), 0)
        self.assertEqual(measure.line_height(100), 127)

    def test_long_german_word_forces_a_smaller_font_but_never_overflows(self):
        style = mv.pick_caption_style(["Der Flugzeugtriebwerken, sagt er."], FONT_FILE)
        self.assertEqual(style["widest_word"], "Flugzeugtriebwerken,")
        self.assertLess(style["font_size"], 100)
        self.assertLessEqual(style["widest_word_px"], mv.CAPTION_MAX_WORD_PX + 2)
        self.assertLessEqual(style["widest_word_px"], 1000)
        self.assertTrue(style["size_limited_by_word"])

    def test_short_words_get_the_maximum_size(self):
        style = mv.pick_caption_style(["Your fridge moves heat."], FONT_FILE)
        self.assertEqual(style["font_size"], mv.CAPTION_FONT_MAX)
        self.assertFalse(style["size_limited_by_word"])

    def test_even_an_absurd_word_stays_inside_the_limits(self):
        style = mv.pick_caption_style(["Donaudampfschifffahrtsgesellschaftskapitaensmuetze"], FONT_FILE)
        self.assertEqual(style["font_size"], mv.CAPTION_FONT_MIN)
        # the font cannot shrink any further, so this must be REPORTED, not silently cut in two on screen
        problem = mv.caption_word_problem(style)
        self.assertIsNotNone(problem)
        self.assertIn("Donaudampfschifffahrtsgesellschaftskapitaensmuetze", problem)
        self.assertIn("Split or hyphenate", problem)

    def test_german_compounds_that_used_to_pass_silently_are_reported(self):
        # 962 px and 983 px at the smallest size: both are wider than the limit
        for word in ("Lebensmittelverschwendung,", "Geschwindigkeitsbegrenzung."):
            style = mv.pick_caption_style([f"Das ist {word}"], FONT_FILE)
            self.assertEqual(style["font_size"], mv.CAPTION_FONT_MIN, word)
            self.assertIsNotNone(mv.caption_word_problem(style), word)

    def test_words_that_fit_are_not_reported(self):
        for text in ("Your fridge moves heat.", "Der Kühlschrankkompressor läuft.", "Flugzeugtriebwerken, sagt er."):
            style = mv.pick_caption_style([text], FONT_FILE)
            self.assertIsNone(mv.caption_word_problem(style), text)

    def test_captions_stay_below_the_diagram_panels(self):
        for text in ("Your fridge moves heat.", "Kühlschrankkompressor", "a"):
            style = mv.pick_caption_style([text], FONT_FILE)
            self.assertGreaterEqual(style["box_top_y"], mv.CAPTION_TOP_LIMIT_Y, text)
            self.assertAlmostEqual(style["box_top_y"], mv.CAPTION_BOX_TOP_Y, delta=1, msg=text)
            # ... and the whole box stays above the YouTube Shorts title/channel overlay
            self.assertLess(style["box_top_y"] + style["box_height"], 1600, text)

    def test_custom_position_puts_the_box_top_where_we_want_it_for_every_font_size(self):
        for size in (64, 90, 110, 120):
            stroke = mv.caption_stroke_width(size)
            height = mv.caption_box_height(size, stroke, math.ceil(1.27 * size))
            percent = mv.caption_position_percent(height)
            self.assertAlmostEqual(mv.caption_box_top_y(height, percent), mv.CAPTION_BOX_TOP_Y, delta=1, msg=size)

    def test_box_height_follows_mpts_formula(self):
        self.assertEqual(mv.caption_box_height(120, 10, 152), 152 + 42 + 30 + 20)

    def test_box_top_is_clamped_like_mpt_does(self):
        self.assertEqual(mv.caption_box_top_y(200, 0), 10)
        self.assertEqual(mv.caption_box_top_y(200, 100), 1920 - 200 - 10)

    def test_unreadable_font_falls_back_to_a_safe_estimate(self):
        style = mv.pick_caption_style(["Alltagstechnik, sagt er."], Path("/nonexistent/font.ttf"))
        self.assertIn("safe estimate", style["note"])
        self.assertLessEqual(style["widest_word_px"], mv.CAPTION_MAX_WORD_PX + 2)

    def test_stroke_scales_with_size(self):
        self.assertEqual(mv.caption_stroke_width(120), 10)
        self.assertEqual(mv.caption_stroke_width(64), 5)
        self.assertEqual(mv.caption_stroke_width(20), 3)


class RunStreamingTests(unittest.TestCase):
    """The timeout must stop the launcher AND what it started, and the output loop must end."""

    def test_normal_run_streams_lines_and_returns_exit_code(self):
        seen = []
        code, timed_out = mv.run_streaming([sys.executable, "-c", "print('a'); print('b'); import sys; sys.exit(3)"],
                                           None, None, 30, seen.append)
        self.assertEqual((code, timed_out), (3, False))
        self.assertEqual(seen, ["a", "b"])

    def test_timeout_kills_the_whole_process_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "grandchild.pid"
            # The launcher starts a grandchild that inherits the output pipe, like `uv` does for python/ffmpeg.
            code_text = (
                "import subprocess, sys, time\n"
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
                f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
                "print('started', flush=True)\n"
                "time.sleep(120)\n"
            )
            seen = []
            started = time.monotonic()
            code, timed_out = mv.run_streaming([sys.executable, "-c", code_text], None, None, 1.5, seen.append)
            elapsed = time.monotonic() - started
            self.assertTrue(timed_out)
            self.assertNotEqual(code, 0)
            self.assertLess(elapsed, 20, "the output loop must end soon after the timeout")
            self.assertEqual(seen, ["started"])
            grandchild = int(pid_file.read_text())
            for _ in range(50):  # give the system a moment to remove the killed process
                try:
                    os.kill(grandchild, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.1)
            else:
                os.kill(grandchild, 9)
                self.fail("the grandchild process survived the timeout")

    def test_missing_command_raises_oserror(self):
        with self.assertRaises(OSError):
            mv.run_streaming(["/nonexistent/program"], None, None, 5, lambda line: None)

    def test_interrupt_in_the_callback_kills_the_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "child.pid"
            code_text = (
                "import os, sys, time\n"
                f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
                "print('go', flush=True)\n"
                "time.sleep(120)\n"
            )

            def stop(line):
                raise KeyboardInterrupt

            with self.assertRaises(KeyboardInterrupt):
                mv.run_streaming([sys.executable, "-c", code_text], None, None, 60, stop)
            pid = int(pid_file.read_text())
            for _ in range(50):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.1)
            else:
                os.kill(pid, 9)
                self.fail("the child survived Ctrl-C")


class PreflightRobustnessTests(unittest.TestCase):
    def test_voicestudio_errors_become_plain_gate_errors(self):
        for exc in (urllib.error.URLError("refused"), ValueError("bad json"), OSError("reset"), mv.http.client.IncompleteRead(b"x")):
            with mock.patch.object(mv, "http_get_json", side_effect=exc):
                with self.assertRaises(mv.GateError) as ctx:
                    mv.voicestudio_info("/engines/tts", "which voice engine is active")
                self.assertIn("/engines/tts", str(ctx.exception))
                self.assertIn("VoiceStudio", str(ctx.exception))

    def test_non_object_answer_is_a_gate_error(self):
        with mock.patch.object(mv, "http_get_json", return_value=["not", "an", "object"]):
            with self.assertRaises(mv.GateError) as ctx:
                mv.voicestudio_info("/engines/asr", "which transcription engine is active")
        self.assertIn("unexpected", str(ctx.exception))

    def test_good_answer_passes_through(self):
        with mock.patch.object(mv, "http_get_json", return_value={"active": "x"}):
            self.assertEqual(mv.voicestudio_info("/engines/asr", "w"), {"active": "x"})

    def test_visuals_module_without_render_function_is_refused(self):
        fake = type(sys)("visuals")
        with mock.patch.dict(sys.modules, {"visuals": fake}):
            with self.assertRaises(mv.GateError) as ctx:
                mv.load_visuals_module([1, 2])
        self.assertIn("render_and_overlay", str(ctx.exception))
        self.assertIn("captions", str(ctx.exception))  # visuals.py draws the captions, so --no-visuals cannot avoid it

    def test_visuals_module_with_render_function_is_accepted(self):
        fake = type(sys)("visuals")
        fake.render_and_overlay = lambda *a, **k: {}
        with mock.patch.dict(sys.modules, {"visuals": fake}):
            self.assertIs(mv.load_visuals_module([1]), fake)

    def test_missing_visuals_module_names_the_lines(self):
        with mock.patch.object(mv.importlib, "import_module", side_effect=ModuleNotFoundError("no", name="visuals")):
            with self.assertRaises(mv.GateError) as ctx:
                mv.load_visuals_module([3, 5])
        self.assertIn("lines 3, 5", str(ctx.exception))

    def test_visuals_module_is_needed_for_the_captions_even_without_any_visual(self):
        with mock.patch.object(mv.importlib, "import_module", side_effect=ModuleNotFoundError("no", name="visuals")):
            with self.assertRaises(mv.GateError) as ctx:
                mv.load_visuals_module([])
        self.assertIn("draws the captions", str(ctx.exception))
        self.assertNotIn("lines", str(ctx.exception))

    def test_broken_visuals_module_is_a_gate_error(self):
        with mock.patch.object(mv.importlib, "import_module", side_effect=SyntaxError("oops")):
            with self.assertRaises(mv.GateError) as ctx:
                mv.load_visuals_module([0])
        self.assertIn("could not be imported", str(ctx.exception))


class VoiceFailureMessageTests(unittest.TestCase):
    def test_no_audio_is_not_called_a_wording_problem(self):
        bad = [{"index": 2, "wer": None, "error": "speak.mjs made no audio in any of 3 attempts: connect ECONNREFUSED", "threshold": 0.15}]
        msg = mv.voice_failure_message(bad, 3)
        self.assertIn("VoiceStudio failed to make audio for line(s) 2", msg)
        self.assertIn("check VoiceStudio", msg)
        self.assertIn("ECONNREFUSED", msg)
        self.assertNotIn("Reword", msg)

    def test_mishearing_still_says_reword(self):
        bad = [{"index": 1, "wer": 0.5, "threshold": 0.15, "text": "script text", "heard": "other text"}]
        msg = mv.voice_failure_message(bad, 3)
        self.assertIn("Reword", msg)
        self.assertIn("script text", msg)
        self.assertIn("other text", msg)
        self.assertNotIn("failed to make audio", msg)

    def test_both_kinds_are_reported_separately(self):
        bad = [
            {"index": 0, "wer": None, "error": "boom", "threshold": 0.3},
            {"index": 4, "wer": 0.4, "threshold": 0.15, "text": "a", "heard": "b"},
        ]
        msg = mv.voice_failure_message(bad, 3)
        self.assertIn("failed to make audio for line(s) 0", msg)
        self.assertIn("1 line(s) are still not understood", msg)


class ReportPathTests(unittest.TestCase):
    def test_repoint_replaces_only_exact_matches_everywhere(self):
        report = {"a": "/w/sub.srt", "b": ["/w/sub.srt", "/w/other"], "c": {"d": "/w/sub.srt "}, "n": 5}
        out = mv.repoint_paths(report, {"/w/sub.srt": "/r/subtitles.srt"})
        self.assertEqual(out, {"a": "/r/subtitles.srt", "b": ["/r/subtitles.srt", "/w/other"], "c": {"d": "/w/sub.srt "}, "n": 5})
        self.assertEqual(report["a"], "/w/sub.srt")  # input untouched

    def test_deleted_paths_become_none_but_siblings_stay(self):
        report = {"narration": {"path": "/w/id/narration.wav"}, "log": "/w/id/mpt.log", "task": "/mpt/tasks/T/final-1.mp4",
                  "kept": "/review/x/final.mp4", "similar": "/w/id/narration.wav.bak", "text": "narration.wav is gone",
                  "clips": ["/mpt/tasks/T/a.mp4", "/keep/b.mp4"]}
        out = mv.drop_deleted_paths(report, ["/w/id/narration.wav", "/mpt/tasks/T"])
        self.assertEqual(out["clips"], ["/keep/b.mp4"])  # left out of lists
        self.assertIsNone(out["narration"]["path"])
        self.assertIsNone(out["task"])
        self.assertEqual(out["log"], "/w/id/mpt.log")
        self.assertEqual(out["kept"], "/review/x/final.mp4")
        self.assertEqual(out["similar"], "/w/id/narration.wav.bak")
        self.assertEqual(out["text"], "narration.wav is gone")


class OutputAndCleanupTests(unittest.TestCase):
    """step_output + step_cleanup on a fake tree: the corrected captions are kept, the report points at kept files."""

    WORDS = [
        {"text": "Hello", "start": 0.0, "end": 0.3, "timing": "heard"},
        {"text": "world.", "start": 0.3, "end": 0.6, "timing": "heard"},
    ]
    PHRASES = [{"start": 0.0, "end": 1.0, "text": "Hello world."}]

    def make_ctx(self, tmp: Path, keep_work: bool):
        args = mv.parse_args(["x.json"] + (["--keep-work"] if keep_work else []))
        ctx = mv.Ctx(args)
        ctx.script = good_script()
        ctx.work = tmp / "work" / ctx.script["id"]
        (ctx.work / "lines").mkdir(parents=True)
        for name in ("narration.wav", "timings.json", "mpt.log", "mpt-subtitles.log", "failed-report.json", "sheet.png", "final-visuals.mp4"):
            (ctx.work / name).write_text(name)
        task_dir = tmp / "mpt" / "storage" / "tasks" / "T1"
        task_dir.mkdir(parents=True)
        (task_dir / "final-1.mp4").write_text("v")
        whisper_dir = tmp / "mpt" / "storage" / "tasks" / "T2"  # the Whisper timing run (--stop-at subtitle)
        whisper_dir.mkdir(parents=True)
        (whisper_dir / "subtitle.srt").write_text("1\n00:00:00,000 --> 00:00:00,300\nHallo\n        \n")
        mpt = {"video": task_dir / "final-1.mp4", "task_dir": task_dir, "task_id": "T1", "extra_task_dirs": [whisper_dir],
               "captions": {"words": [dict(w) for w in self.WORDS], "phrases": [dict(p) for p in self.PHRASES]}}
        ctx.report.update(
            narration={"path": str(ctx.work / "narration.wav"), "duration": 3.0},
            mpt={"log": str(ctx.work / "mpt.log"), "video": str(mpt["video"]),
                 "subtitle_run": {"log": str(ctx.work / "mpt-subtitles.log"), "subtitle_path": str(whisper_dir / "subtitle.srt")}},
            visuals={"out": str(ctx.work / "final-visuals.mp4"), "panels": 1},
        )
        ctx.checks += [  # the sentences the real steps write (they contain paths)
            {"name": "narration joined", "ok": True, "detail": f"3.0 s, 2 lines, 0.25 s gaps; timings in {ctx.work / 'timings.json'}"},
            {"name": "MPT subtitle path", "ok": True, "detail": f"{whisper_dir / 'subtitle.srt'} (the Whisper run must write a subtitle file)"},
            {"name": "MPT video", "ok": True, "detail": f"{mpt['video']}"},
            {"name": "visuals", "ok": True, "detail": f"2 caption words and 1 visual line(s) rendered onto the video in one ffmpeg pass -> {ctx.work / 'final-visuals.mp4'}"},
            {"name": "contact sheet", "ok": True, "detail": str(ctx.work / "sheet.png")},
        ]
        return ctx, mpt

    def run_steps(self, keep_work):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            ctx, mpt = self.make_ctx(tmp, keep_work)
            with mock.patch.object(mv, "REVIEW_ROOT", tmp / "review"), mock.patch.object(mv, "MPT_DIR", tmp / "mpt"), \
                    contextlib.redirect_stdout(io.StringIO()):
                folder = mv.step_output(ctx, ctx.work / "final-visuals.mp4", ctx.work / "sheet.png", ["credit"], mpt)
                after_output = json.loads((folder / "report.json").read_text(encoding="utf-8"))
                mv.step_cleanup(ctx, mpt, folder)
                after_cleanup = json.loads((folder / "report.json").read_text(encoding="utf-8"))
            return {"folder_files": sorted(p.name for p in folder.iterdir()), "srt": (folder / "subtitles.srt").read_text(encoding="utf-8"),
                    "words_json": json.loads((folder / "captions-words.json").read_text(encoding="utf-8")),
                    "after_output": after_output, "after_cleanup": after_cleanup, "folder": str(folder),
                    "work_left": sorted(p.name for p in ctx.work.iterdir()),
                    "task_dirs_exist": [d.exists() for d in (mpt["task_dir"], *mpt["extra_task_dirs"])],
                    "work": str(ctx.work), "task_dir": str(mpt["task_dir"]), "whisper_dir": str(mpt["extra_task_dirs"][0])}

    def test_corrected_captions_are_kept_and_report_points_at_kept_copies(self):
        r = self.run_steps(keep_work=False)
        self.assertEqual(r["folder_files"], ["caption.txt", "captions-words.json", "final.mp4", "report.json", "sheet.png", "subtitles.srt"])
        # the YouTube file holds the phrases of the CORRECTED captions, not Whisper's raw words
        self.assertEqual(r["srt"], "1\n00:00:00,000 --> 00:00:01,000\nHello world.\n\n")
        self.assertEqual(r["words_json"], self.WORDS)  # the per-word list, as the video shows it
        for report in (r["after_output"], r["after_cleanup"]):
            self.assertEqual(report["visuals"]["out"], r["folder"] + "/final.mp4")
            self.assertEqual(report["outputs"]["subtitles"], r["folder"] + "/subtitles.srt")
            self.assertEqual(report["outputs"]["captions_words"], r["folder"] + "/captions-words.json")

    def test_cleanup_records_what_it_deleted_and_nulls_dead_paths(self):
        r = self.run_steps(keep_work=False)
        self.assertEqual(r["work_left"], ["mpt-subtitles.log", "mpt.log", "timings.json"])
        self.assertEqual(r["task_dirs_exist"], [False, False])  # the video run AND the Whisper run are removed
        cleanup = r["after_cleanup"]["cleanup"]
        self.assertTrue(cleanup["performed"])
        names = [Path(x).name for x in cleanup["removed"]]
        for expected in ("T1", "T2", "lines", "narration.wav", "sheet.png", "final-visuals.mp4", "failed-report.json"):
            self.assertIn(expected, names)
        self.assertNotIn("mpt.log", names)
        self.assertNotIn("mpt-subtitles.log", names)
        self.assertIsNone(r["after_cleanup"]["narration"]["path"])
        self.assertIsNone(r["after_cleanup"]["mpt"]["video"])
        self.assertIsNone(r["after_cleanup"]["mpt"]["subtitle_run"]["subtitle_path"])
        self.assertTrue(r["after_cleanup"]["mpt"]["log"].endswith("mpt.log"))
        self.assertTrue(r["after_cleanup"]["mpt"]["subtitle_run"]["log"].endswith("mpt-subtitles.log"))
        self.assertIsNotNone(r["after_output"]["narration"]["path"])  # before cleanup the file still existed

    @staticmethod
    def details(report):
        return {c["name"]: c["detail"] for c in report["checks"]}

    def test_check_sentences_point_at_the_kept_copies(self):
        r = self.run_steps(keep_work=False)
        folder = r["folder"]
        for report in (r["after_output"], r["after_cleanup"]):
            d = self.details(report)
            self.assertTrue(d["visuals"].endswith(f"-> {folder}/final.mp4"), d["visuals"])
            self.assertEqual(d["contact sheet"], f"{folder}/sheet.png")

    def test_check_sentences_never_name_a_deleted_file_after_cleanup(self):
        r = self.run_steps(keep_work=False)
        d = self.details(r["after_cleanup"])
        self.assertEqual(d["MPT video"], "final-1.mp4 (deleted after the run)")
        self.assertTrue(d["MPT subtitle path"].startswith("subtitle.srt (deleted after the run)"), d["MPT subtitle path"])
        self.assertIn(r["work"] + "/timings.json", d["narration joined"])  # a kept file keeps its full path
        for name, detail in d.items():
            self.assertNotIn(r["task_dir"], detail, name)
            self.assertNotIn(r["whisper_dir"], detail, name)
            for gone in ("narration.wav", "final-visuals.mp4"):
                self.assertNotIn(r["work"] + "/" + gone, detail, name)
        # before cleanup the temporary files still existed, so their paths were still correct
        self.assertIn(r["task_dir"], self.details(r["after_output"])["MPT video"])
        self.assertIn(r["whisper_dir"], self.details(r["after_output"])["MPT subtitle path"])

    def test_keep_work_deletes_nothing_and_says_so(self):
        r = self.run_steps(keep_work=True)
        self.assertEqual(r["task_dirs_exist"], [True, True])
        self.assertIn("narration.wav", r["work_left"])
        self.assertEqual(r["after_cleanup"]["cleanup"], {"performed": False, "reason": "--keep-work", "removed": []})
        self.assertTrue(r["after_cleanup"]["narration"]["path"].endswith("narration.wav"))


class TextRewriteTests(unittest.TestCase):
    def test_replace_in_strings_works_inside_sentences_and_prefers_the_longest_key(self):
        mapping = {"/w/a.mp4": "/review/final.mp4", "/w": "/other"}
        out = mv.replace_in_strings([{"detail": "ok -> /w/a.mp4 and /w/b", "n": 3}, "/w/a.mp4"], mapping)
        self.assertEqual(out, [{"detail": "ok -> /review/final.mp4 and /other/b", "n": 3}, "/review/final.mp4"])

    def test_mark_deleted_shortens_paths_inside_sentences(self):
        deleted = ["/m/tasks/T1", "/w/id/lines"]
        out = mv.mark_deleted_in_strings(
            ["/m/tasks/T1/final-1.mp4 ok, see /w/id/lines; keep /w/id/timings.json (and /m/tasks/T1)"], deleted)
        self.assertEqual(out, ["final-1.mp4 (deleted after the run) ok, see lines (deleted after the run); "
                               "keep /w/id/timings.json (and T1 (deleted after the run))"])

    def test_mark_deleted_leaves_similar_looking_text_alone(self):
        self.assertEqual(mv.mark_deleted_in_strings("narration.wav is gone", ["/w/id/narration.wav"]), "narration.wav is gone")


class FixedInCaptionsNoteTests(unittest.TestCase):
    def test_no_differences_no_note(self):
        self.assertIsNone(mv.fixed_in_captions_note([]))

    def test_every_differing_word_is_listed(self):
        diffs = ['script word(s) missing in the subtitle: "an"', 'script "zwängt" -> subtitle "zwingt"']
        text = mv.fixed_in_captions_note(diffs)
        self.assertIn("fixed in captions", text)
        self.assertIn("2 spot(s)", text)
        self.assertIn("zwingt", text)
        self.assertIn('missing in the subtitle: "an"', text)
        self.assertIn("narration", text)  # it points at the VOICE: the captions themselves are right

    def test_a_passing_comparison_with_a_misspelling_is_listed_as_fixed(self):
        script = ["Der Druck zwängt das Gas durch die Kühlschlange und das hier ist ein langer Satz"]
        cues = [{"index": 1, "start": 0, "end": 1, "text": script[0].replace("zwängt", "zwingt")}]
        ok, wer, msg, diffs = mv.check_srt_accuracy(cues, script)
        self.assertTrue(ok)  # below the 10 percent limit, so the gate lets it through ...
        self.assertIn("fixed in the captions", msg)  # ... the captions show the script's word ...
        self.assertIn("zwingt", mv.fixed_in_captions_note(diffs))  # ... and the user can still see what Whisper heard

    def test_the_voice_gate_message_talks_about_the_voice(self):
        script = ["red blue green yellow pink black white brown grey gold"]
        cues = [{"index": 1, "start": 0, "end": 1, "text": "red blue screen yellow pink black white brown grey gold silver"}]
        ok, _wer, msg, _diffs = mv.check_srt_accuracy(cues, script)
        self.assertFalse(ok)
        self.assertIn("voice", msg)


class UnexpectedErrorTests(unittest.TestCase):
    def test_unexpected_exception_prints_plain_message_and_writes_failed_report(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            script_path = tmp / "script.json"
            script_path.write_text(json.dumps(good_script()), encoding="utf-8")
            err = io.StringIO()
            with mock.patch.object(mv, "WORK_ROOT", tmp / "work"), \
                    mock.patch.object(mv, "step_preflight", side_effect=KeyError("surprise")), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                code = mv.main([str(script_path)])
            self.assertEqual(code, 1)
            text = err.getvalue()
            self.assertIn("FAILED (unexpected)", text)
            self.assertIn("KeyError", text)
            self.assertNotIn("Traceback", text)
            failed = tmp / "work" / "2026-10-14-en-fridge" / "failed-report.json"
            self.assertTrue(failed.is_file())
            data = json.loads(failed.read_text(encoding="utf-8"))
            self.assertFalse(data["ok"])
            self.assertIn("KeyError", data["error"])
            self.assertIn("Traceback", data["traceback"])

    def test_gate_errors_still_use_the_plain_failed_headline(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            script_path = tmp / "script.json"
            script_path.write_text(json.dumps(good_script()), encoding="utf-8")
            err = io.StringIO()
            with mock.patch.object(mv, "WORK_ROOT", tmp / "work"), \
                    mock.patch.object(mv, "step_preflight", side_effect=mv.GateError("VoiceStudio is off")), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                code = mv.main([str(script_path)])
            self.assertEqual(code, 1)
            self.assertIn("FAILED: VoiceStudio is off", err.getvalue())
            self.assertTrue((tmp / "work" / "2026-10-14-en-fridge" / "failed-report.json").is_file())


class MainFailsLoudlyTests(unittest.TestCase):
    """These never reach the network: validation fails first."""

    def run_main(self, path):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = mv.main([str(path)])
        return code, err.getvalue()

    def test_missing_file(self):
        code, err = self.run_main("/nonexistent/script.json")
        self.assertEqual(code, 1)
        self.assertIn("FAILED", err)

    def test_invalid_script_lists_every_problem(self):
        bad = copy.deepcopy(good_script())
        bad["sources"] = []
        bad["video_terms"] = ["only", "three", "terms"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "script.json"
            path.write_text(json.dumps(bad), encoding="utf-8")
            code, err = self.run_main(path)
        self.assertEqual(code, 1)
        self.assertIn("sources", err)
        self.assertIn("video_terms", err)

    def test_not_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "script.json"
            path.write_text("{oops", encoding="utf-8")
            code, err = self.run_main(path)
        self.assertEqual(code, 1)
        self.assertIn("not valid JSON", err)


class SpellingTolerantLineCheckTests(unittest.TestCase):
    """Real cases from the 2026-10-14 noise-cancelling runs: spelling variants must pass, a mishearing must fail."""

    def passes(self, ref, heard):
        wer, cer = mv.word_error_rate(ref, heard), mv.char_error_rate(ref, heard)
        return mv.line_error_score(wer, cer, mv.wer_threshold(ref)) <= 1.0

    def test_hyphen_and_compound_variants_pass(self):
        self.assertTrue(self.passes("The whole loop runs nonstop, adjusting faster than you could ever notice.",
                                    "The whole loop runs non-stop, adjusting faster than you could ever notice."))
        self.assertTrue(self.passes("On the outside of each ear cup, a tiny microphone listens to the world around you.",
                                    "On the outside of each earcup, a tiny microphone listens to the world around you."))
        self.assertTrue(self.passes("Und der Transparenzmodus? Gleiche Mikrofone, aber statt den Schall umzudrehen, leiten sie ihn einfach weiter.",
                                    "Und der Transparenz-Modus? Gleiche Mikrofone aber statt den Schall umzudrehen, leiten sie ihn einfach weiter."))

    def test_char_error_rate_ignores_spaces_and_dashes(self):
        self.assertEqual(mv.char_error_rate("Zugrattern", "zu grattern"), 0.0)
        self.assertEqual(mv.char_error_rate("", ""), 0.0)
        self.assertEqual(mv.char_error_rate("", "x"), 1.0)

    def test_real_mishearing_still_fails(self):
        self.assertFalse(self.passes("Kopfhörer mit Noise Cancelling bekämpfen Lärm mit noch mehr Schall.",
                                     "Kopfhörer mit Neuskänzeling bekämpfen Lärm mit noch mehr Schall."))


class BrollValidationTests(unittest.TestCase):
    """script.json lines[].broll: optional English search phrase for the stock footage."""

    def check(self, value):
        s = good_script()
        s["lines"][1]["broll"] = value
        return mv.validate_script(s)

    def test_good_phrases_pass(self):
        for phrase in ("refrigerator interior", "ice cubes", "close-up", "ab", "x" * 40, "Copper Pipes"):
            errors, warnings = self.check(phrase)
            self.assertEqual((errors, warnings), ([], []), phrase)

    def test_broll_is_optional(self):
        self.assertEqual(mv.validate_script(good_script()), ([], []))
        self.assertEqual(self.check(None)[0], [])  # null = not set

    def test_bad_phrases_are_errors_naming_the_line(self):
        for bad in ("a", "", "   ", "x" * 41, "kühlschrank", "fridge 2", "fridge!", "fridge\n", 5, ["ice"], {"a": 1}, True):
            errors, _ = self.check(bad)
            self.assertEqual(len(errors), 1, repr(bad))
            self.assertIn("lines[1].broll", errors[0])

    def test_more_than_four_words_is_only_a_warning(self):
        errors, warnings = self.check("old white fridge door open")
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("lines[1].broll", warnings[0])


class FootageModeTests(unittest.TestCase):
    def test_auto_uses_own_footage_when_a_pixabay_key_is_set(self):
        self.assertEqual(mv.resolve_footage_mode("auto", False, True, "pixabay"), ("own", None))
        self.assertEqual(mv.resolve_footage_mode("auto", False, True, "pexels"), ("own", None))  # a Pexels key does not change that (yet)

    def test_auto_without_a_pixabay_key_keeps_the_old_behaviour(self):
        self.assertEqual(mv.resolve_footage_mode("auto", False, False, "pexels"), ("mpt", "pexels"))

    def test_mpt_is_the_old_behaviour_even_with_a_pixabay_key(self):
        self.assertEqual(mv.resolve_footage_mode("mpt", False, True, "pixabay"), ("mpt", "pixabay"))

    def test_local_materials_win_over_auto_and_mpt(self):
        self.assertEqual(mv.resolve_footage_mode("auto", True, True, "pixabay"), ("local", None))
        self.assertEqual(mv.resolve_footage_mode("mpt", True, True, "pixabay"), ("local", None))

    def test_own_with_local_materials_is_refused(self):
        with self.assertRaises(mv.GateError) as ctx:
            mv.resolve_footage_mode("own", True, True, "pixabay")
        self.assertIn("--local-materials", str(ctx.exception))

    def test_own_without_a_pixabay_key_says_what_to_do(self):
        with self.assertRaises(mv.GateError) as ctx:
            mv.resolve_footage_mode("own", False, False, "pexels")
        self.assertIn("pixabay_api_keys", str(ctx.exception))

    def test_no_key_at_all_is_the_old_plain_message(self):
        for requested in ("auto", "mpt"):
            with self.assertRaises(mv.GateError) as ctx:
                mv.resolve_footage_mode(requested, False, False, None)
            self.assertIn("No stock-footage API key", str(ctx.exception))

    def test_footage_flag(self):
        self.assertEqual(mv.parse_args(["s.json"]).footage, "auto")
        for mode in ("auto", "own", "mpt"):
            self.assertEqual(mv.parse_args(["s.json", "--footage", mode]).footage, mode)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            mv.parse_args(["s.json", "--footage", "pexels"])

    def test_mpt_command_keeps_our_order_for_own_footage(self):
        cmd = mv.build_mpt_command("uv", "x", ["t"], Path("/n.wav"), "id", [Path("/w/broll.mp4")], fixed_order_seconds=72)
        pairs = dict(zip(cmd[4:], cmd[5:]))
        self.assertEqual(pairs["--video-source"], "local")
        self.assertEqual(pairs["--video-materials"], "/w/broll.mp4")
        self.assertEqual(pairs["--video-concat-mode"], "sequential")
        self.assertEqual(pairs["--video-transition-mode"], "none")
        self.assertEqual(pairs["--video-clip-duration"], "72")  # longer than the file, or MPT would keep only its first 5 s
        self.assertEqual(pairs["--video-clip-speed"], "1.0")

    def test_other_commands_do_not_get_the_fixed_order_flags(self):
        for cmd in (mv.build_mpt_command("uv", "x", ["t"], Path("/n.wav"), "id", [Path("/m/a.mp4")]),
                    mv.build_mpt_command("uv", "x", ["t"], Path("/n.wav"), "id", source="pixabay")):
            for flag in ("--video-concat-mode", "--video-transition-mode", "--video-clip-duration", "--video-clip-speed"):
                self.assertNotIn(flag, cmd)

    def test_fixed_order_flags_are_ignored_without_local_files(self):
        cmd = mv.build_mpt_command("uv", "x", ["t"], Path("/n.wav"), "id", source="pexels", fixed_order_seconds=72)
        self.assertNotIn("--video-clip-duration", cmd)


class CaptionlessVideoCommandTests(unittest.TestCase):
    """The two MoneyPrinterTurbo runs: Whisper timing only (--stop-at subtitle) and the video WITHOUT captions."""

    def pairs(self, cmd):
        return dict(zip(cmd[4:], cmd[5:]))

    def test_the_video_run_has_no_captions_and_no_caption_styling(self):
        cmd = mv.build_mpt_command("uv", "x", ["t"], Path("/n.wav"), "id", [Path("/w/broll.mp4")], burn_captions=False, fixed_order_seconds=72)
        self.assertIn("--no-subtitle-enabled", cmd)
        self.assertNotIn("--subtitle-enabled", cmd)
        for flag in ("--font-name", "--subtitle-display-mode", "--subtitle-animation", "--subtitle-position", "--custom-position",
                     "--font-size", "--stroke-width", "--stroke-color", "--text-fore-color", "--no-subtitle-background-enabled", "--stop-at"):
            self.assertNotIn(flag, cmd)
        pairs = self.pairs(cmd)  # everything else stays as it was: our own B-roll in order, no music, narration, 9:16
        self.assertEqual(pairs["--video-source"], "local")
        self.assertEqual(pairs["--video-materials"], "/w/broll.mp4")
        self.assertEqual(pairs["--video-concat-mode"], "sequential")
        self.assertEqual(pairs["--video-transition-mode"], "none")
        self.assertEqual(pairs["--video-clip-duration"], "72")
        self.assertEqual(pairs["--video-clip-speed"], "1.0")
        self.assertEqual(pairs["--bgm-type"], "none")
        self.assertEqual(pairs["--custom-audio-file"], "/n.wav")
        self.assertEqual(pairs["--video-aspect"], "9:16")
        self.assertEqual(pairs["--task-id"], "id")

    def test_the_default_run_still_burns_captions_and_runs_to_the_end(self):
        cmd = mv.build_mpt_command("uv", "x", ["t"], Path("/n.wav"), "id")
        self.assertIn("--subtitle-enabled", cmd)
        self.assertNotIn("--no-subtitle-enabled", cmd)
        self.assertNotIn("--stop-at", cmd)

    def test_the_whisper_run_stops_after_the_subtitle_stage_and_needs_no_footage(self):
        cmd = mv.build_mpt_command("uv", "Das Skript.", ["t"], Path("/n.wav"), "id", [Path("/w/broll.mp4")], stop_at="subtitle",
                                   fixed_order_seconds=72, source="pixabay")
        pairs = self.pairs(cmd)
        self.assertEqual(pairs["--stop-at"], "subtitle")
        self.assertEqual(cmd[-2:], ["--stop-at", "subtitle"])
        self.assertEqual(pairs["--video-script"], "Das Skript.")
        self.assertEqual(pairs["--custom-audio-file"], "/n.wav")
        self.assertEqual(pairs["--bgm-type"], "none")
        self.assertIn("--subtitle-enabled", cmd)  # the subtitle stage must produce a file
        for flag in ("--video-source", "--video-materials", "--video-concat-mode", "--video-clip-duration"):
            self.assertNotIn(flag, cmd)

    def test_burned_captions_are_detected(self):
        ok_params = {"subtitle_enabled": False}
        self.assertEqual(mv.find_burned_captions("generating video", {"videos": ["a.mp4"]}, ok_params), [])
        self.assertEqual(mv.find_burned_captions("x", {"videos": [], "subtitle_path": ""}, ok_params), [])
        self.assertTrue(mv.find_burned_captions("x", {"subtitle_path": "/t/subtitle.srt"}, ok_params))
        self.assertTrue(mv.find_burned_captions("detected language: 'de', probability: 1.00", {}, ok_params))
        self.assertTrue(mv.find_burned_captions("x", {}, {"subtitle_enabled": True}))
        self.assertTrue(mv.find_burned_captions("x", {}, {}))  # not saying "disabled" is not good enough
        self.assertEqual(mv.find_burned_captions("x", {}, None), [])  # saved params unreadable: the other signals decide

    def test_caption_overlay_position_matches_the_old_caption_box(self):
        import visuals

        self.assertEqual(visuals.CAPTION_Y, mv.CAPTION_BOX_TOP_Y)
        self.assertGreater(visuals.CAPTION_Y, mv.CAPTION_TOP_LIMIT_Y)  # below the diagram panels
        self.assertLessEqual(visuals.CAPTION_Y + visuals.CAPTION_H, mv.FRAME_HEIGHT)
        self.assertEqual(visuals.CAPTION_W, 1080)
        for size in (mv.CAPTION_FONT_MIN, mv.CAPTION_FONT_MAX):  # the box of every allowed font size fits the canvas
            box = mv.caption_box_height(size, mv.caption_stroke_width(size), math.ceil(1.35 * size))
            self.assertLessEqual(box, visuals.CAPTION_H)


class CaptionStepTests(unittest.TestCase):
    """step_captions: one caption per script word, gates, report."""

    SCRIPT_LINES = [{"text": "Trifft ein Wellenberg auf ein Wellental, löschen sie sich aus.", "visual": None},
                    {"text": "Das heißt destruktive Interferenz.", "visual": None}]

    def make(self):
        ctx = mv.Ctx(mv.parse_args(["content/x/script.json"]))
        script = good_script()
        script["lines"] = [dict(line) for line in self.SCRIPT_LINES]
        ctx.script = script
        ctx.report["captions"] = {"mode": "word_by_word"}
        setup = {"caption": {"font_size": 69, "stroke_width": 6, "box_height": 141}}
        return ctx, setup

    def whisper(self, words, diffs=()):
        cues = [{"index": k + 1, "start": 0.4 * k, "end": 0.4 * (k + 1), "text": w} for k, w in enumerate(words)]
        return {"cues": cues, "differences": list(diffs)}

    def run_step(self, ctx, setup, whisper, total=10.0):
        with contextlib.redirect_stdout(io.StringIO()):
            return mv.step_captions(ctx, whisper, setup, total)

    def test_captions_have_the_script_spelling_not_whiskers(self):
        ctx, setup = self.make()
        heard = ["rift", "ein", "Wellenberg", "auf", "ein", "Wellental", "löschen", "sie", "sich", "aus", "Das", "heißt", "destruktive", "Interferenz"]
        result = self.run_step(ctx, setup, self.whisper(heard, ['script "trifft" -> subtitle "rift"']))
        self.assertEqual(" ".join(w["text"] for w in result["words"]),
                         "Trifft ein Wellenberg auf ein Wellental, löschen sie sich aus. Das heißt destruktive Interferenz.")
        self.assertEqual(result["words"][0]["start"], 0.0)  # the time of "rift"
        self.assertEqual(result["words"][0]["end"], 0.4)
        self.assertEqual(result["style"], {"font_size": 69, "stroke_width": 6, "box_height": 141, "word_sizes": {}})
        self.assertTrue(result["phrases"])
        names = {c["name"]: c for c in ctx.checks}
        self.assertTrue(names["captions match script"]["ok"])
        self.assertTrue(names["caption timing"]["ok"])
        self.assertEqual(ctx.report["captions"]["fixed_in_captions"], ['script "trifft" -> subtitle "rift"'])
        self.assertEqual(ctx.report["captions"]["alignment"]["words"], 14)
        self.assertEqual(ctx.report["captions"]["script_words"], 14)
        self.assertIn("Remotion", ctx.report["captions"]["renderer"])

    def test_words_with_their_own_size_are_handed_on_to_the_drawing_step(self):
        ctx, setup = self.make()
        setup["caption"]["word_sizes"] = {"Wellenberg": 52}
        heard = ["Trifft", "ein", "Wellenberg", "auf", "ein", "Wellental", "löschen", "sie", "sich", "aus", "Das", "heißt", "destruktive", "Interferenz"]
        result = self.run_step(ctx, setup, self.whisper(heard))
        self.assertEqual(result["style"]["word_sizes"], {"Wellenberg": 52})
        self.assertEqual(result["style"]["font_size"], 69)  # the base size is not touched
        self.assertIsNot(result["style"]["word_sizes"], setup["caption"]["word_sizes"])  # a copy

    def test_the_gate_fails_loudly_when_a_caption_word_is_not_the_script_word(self):
        ctx, setup = self.make()
        heard = ["Trifft", "ein", "Wellenberg", "auf", "ein", "Wellental", "löschen", "sie", "sich", "aus", "Das", "heißt", "destruktive", "Interferenz"]
        wrong = [{"text": "Rift" if k == 0 else w, "start": 0.4 * k, "end": 0.4 * (k + 1), "timing": "heard"}
                 for k, w in enumerate(" ".join(line["text"] for line in self.SCRIPT_LINES).split())]
        with mock.patch.object(mv.captionlib, "align_words", return_value=wrong):
            with self.assertRaises(mv.GateError) as raised:
                self.run_step(ctx, setup, self.whisper(heard))
        self.assertIn("captions match script failed", str(raised.exception))
        self.assertIn("'Rift'", str(raised.exception))

    def test_alignment_trouble_is_a_plain_gate_error(self):
        ctx, setup = self.make()
        with self.assertRaises(mv.GateError) as raised:
            self.run_step(ctx, setup, self.whisper(["a", "b"]), total=0.3)  # 14 words cannot fit into 0.3 s
        self.assertIn("Could not build the captions", str(raised.exception))

    def test_many_guessed_words_give_a_warning(self):
        ctx, setup = self.make()
        self.run_step(ctx, setup, self.whisper(["Trifft", "ein", "Wellenberg"]))  # 11 of 14 words missing from Whisper
        self.assertTrue(any("spreading or interpolating" in w for w in ctx.warnings))

    def test_a_perfect_transcript_gives_no_warning(self):
        ctx, setup = self.make()
        heard = ["Trifft", "ein", "Wellenberg", "auf", "ein", "Wellental", "löschen", "sie", "sich", "aus", "Das", "heißt", "destruktive", "Interferenz"]
        self.run_step(ctx, setup, self.whisper(heard))
        self.assertEqual(ctx.warnings, [])
        self.assertEqual(ctx.report["captions"]["alignment"]["guessed"], 0)
        self.assertEqual(ctx.report["captions"]["fixed_in_captions"], [])

    def test_a_late_first_caption_is_only_a_warning(self):
        ctx, setup = self.make()
        heard = ["Trifft", "ein", "Wellenberg", "auf", "ein", "Wellental", "löschen", "sie", "sich", "aus", "Das", "heißt", "destruktive", "Interferenz"]
        whisper = self.whisper(heard)
        for cue in whisper["cues"]:
            cue["start"] += 2.0
            cue["end"] += 2.0
        self.run_step(ctx, setup, whisper, total=10.0)
        self.assertTrue(any("first caption only appears" in w for w in ctx.warnings))


class WhisperStepTests(unittest.TestCase):
    def make(self, tmp):
        ctx = mv.Ctx(mv.parse_args(["content/x/script.json"]))
        ctx.script = good_script()
        ctx.work = tmp / "work"
        ctx.work.mkdir()
        setup = {"caption": {"font_size": 69, "stroke_width": 6, "box_height": 141, "position_percent": 73.07}}
        return ctx, setup

    def run_step(self, ctx, setup, srt_text, log_lines=("detected language: 'en', probability: 0.99",)):
        srt = ctx.work / "subtitle.srt"
        srt.write_text(srt_text, encoding="utf-8")
        seen = {}

        def fake_run(c, cmd, log_path, record):
            seen["cmd"], seen["log"] = cmd, log_path
            record.update(log=str(log_path), exit_code=0)
            return list(log_lines), {"subtitle_path": str(srt)}

        with mock.patch.object(mv, "find_tool", return_value="/bin/uv"), mock.patch.object(mv, "run_mpt_task", side_effect=fake_run), \
                contextlib.redirect_stdout(io.StringIO()):
            result = mv.step_whisper_timing(ctx, Path("/w/narration.wav"), setup, "Your fridge does not make cold. It moves heat out of the box.",
                                            ["Your fridge does not make cold.", "It moves heat out of the box."])
        return result, seen

    GOOD_SRT = "".join(f"{k}\n00:00:0{k // 2},{(k % 2) * 500:03d} --> 00:00:0{(k + 1) // 2},{((k + 1) % 2) * 500:03d}\n{w}\n\n"
                       for k, w in enumerate("Your fridge does not make cold. It moves heat out of the box.".split(), 1))

    def test_the_whisper_run_stops_at_the_subtitle_stage_and_is_checked(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx, setup = self.make(Path(raw))
            result, seen = self.run_step(ctx, setup, self.GOOD_SRT)
        self.assertEqual(seen["cmd"][-2:], ["--stop-at", "subtitle"])
        self.assertTrue(str(seen["log"]).endswith("mpt-subtitles.log"))
        self.assertEqual(len(result["cues"]), 13)
        names = {c["name"]: c["ok"] for c in ctx.checks}
        self.assertTrue(names["MPT subtitle path"])
        self.assertTrue(names["whisper language"])
        self.assertTrue(names["whisper vs script"])  # the voice-quality gate is still there
        self.assertEqual(ctx.report["srt"]["wer"], 0.0)
        self.assertEqual(ctx.report["srt"]["wer_limit"], mv.SRT_WER_LIMIT)
        self.assertEqual(ctx.report["mpt"]["subtitle_run"]["exit_code"], 0)
        self.assertEqual(result["task_dir"].name, result["task_id"])

    def test_a_voice_that_whisper_cannot_understand_still_fails_the_run(self):
        bad = "".join(f"{k}\n00:00:00,{k:03d} --> 00:00:00,{k + 1:03d}\nblah{k}\n\n" for k in range(1, 13))
        with tempfile.TemporaryDirectory() as raw:
            ctx, setup = self.make(Path(raw))
            with self.assertRaises(mv.GateError) as raised:
                self.run_step(ctx, setup, bad)
        self.assertIn("whisper vs script failed", str(raised.exception))
        self.assertIn("voice", str(raised.exception))

    def test_the_wrong_language_still_fails_the_run(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx, setup = self.make(Path(raw))
            with self.assertRaises(mv.GateError) as raised:
                self.run_step(ctx, setup, self.GOOD_SRT, log_lines=("detected language: 'de', probability: 0.99",))
        self.assertIn("whisper language failed", str(raised.exception))


class VisualsStepTests(unittest.TestCase):
    """step_visuals hands the captions (and, unless --no-visuals, the panels) to visuals.render_and_overlay."""

    def make(self, tmp, extra_args=()):
        ctx = mv.Ctx(mv.parse_args(["x.json", *extra_args]))
        ctx.script = good_script()  # line 1 has a stat visual
        ctx.work = tmp
        words = [{"text": w, "start": 0.3 * k, "end": 0.3 * (k + 1), "timing": "heard"}
                 for k, w in enumerate(" ".join(line["text"] for line in ctx.script["lines"]).split())]
        mpt = {"video": tmp / "mpt.mp4", "captions": {"words": words, "phrases": [], "stats": {},
                                                      "style": {"font_size": 69, "stroke_width": 6, "box_height": 141}}}
        return ctx, mpt

    def run_step(self, ctx, mpt):
        calls = []

        def fake_render(base, script, timings, out, work, captions=None):
            calls.append({"base": base, "script": script, "captions": captions})
            Path(out).write_text("video")
            return {"panels": 1, "render_seconds": 1.0, "out": out, "captions": {"words": 2, "render_seconds": 1.0}}

        fake = type(sys)("visuals")
        fake.render_and_overlay = fake_render
        with mock.patch.object(mv, "load_visuals_module", return_value=fake), contextlib.redirect_stdout(io.StringIO()):
            out = mv.step_visuals(ctx, mpt, [{"index": 0, "start": 0, "end": 2}, {"index": 1, "start": 2.25, "end": 4}])
        return out, calls

    def test_captions_and_panels_go_in_one_call(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx, mpt = self.make(Path(raw))
            out, calls = self.run_step(ctx, mpt)
            self.assertEqual(len(calls), 1)
            captions = calls[0]["captions"]
            self.assertEqual(captions["words"][:2], [{"text": "Your", "start": 0.0, "end": 0.3}, {"text": "fridge", "start": 0.3, "end": 0.6}])
            self.assertEqual(" ".join(w["text"] for w in captions["words"]), " ".join(line["text"] for line in ctx.script["lines"]))
            self.assertTrue(all(set(w) == {"text", "start", "end"} for w in captions["words"]))
            self.assertEqual((captions["font_size"], captions["stroke_width"], captions["box_height"]), (69, 6, 141))
            self.assertEqual((captions["text_color"], captions["stroke_color"]), ("#FFFFFF", "#000000"))
            self.assertIsNotNone(calls[0]["script"]["lines"][1]["visual"])
            self.assertEqual(out, ctx.work / "final-visuals.mp4")
            self.assertEqual(ctx.report["visuals"]["captions"]["words"], 2)
            self.assertIn("13 caption words and 1 visual line(s)", ctx.checks[-1]["detail"])
            self.assertTrue(any(c["name"] == "captions match script (as drawn)" and c["ok"] for c in ctx.checks))

    def test_no_visuals_still_draws_the_captions(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx, mpt = self.make(Path(raw), ["--no-visuals"])
            out, calls = self.run_step(ctx, mpt)
            self.assertEqual(len(calls), 1)
            self.assertTrue(calls[0]["captions"]["words"])
            self.assertTrue(all(line["visual"] is None for line in calls[0]["script"]["lines"]))
            self.assertEqual(ctx.report["visuals"]["skipped"], "--no-visuals")
            self.assertNotIn("visual line", ctx.checks[-1]["detail"])
            self.assertTrue(out.name == "final-visuals.mp4")
            self.assertIsNotNone(good_script()["lines"][1]["visual"])  # the caller's script is not changed

    def test_a_script_without_visuals_still_draws_the_captions(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx, mpt = self.make(Path(raw))
            ctx.script["lines"][1]["visual"] = None
            _out, calls = self.run_step(ctx, mpt)
            self.assertEqual(len(calls), 1)
            self.assertEqual(ctx.report["visuals"]["skipped"], "no line has a visual")

    def test_changed_caption_words_are_stopped_before_rendering(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx, mpt = self.make(Path(raw))
            mpt["captions"]["words"][0]["text"] = "Rift"  # somebody changed a word after the gate
            fake = type(sys)("visuals")
            fake.render_and_overlay = mock.Mock()
            with mock.patch.object(mv, "load_visuals_module", return_value=fake), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(mv.GateError) as raised:
                    mv.step_visuals(ctx, mpt, [])
            self.assertIn("captions match script (as drawn) failed", str(raised.exception))
            fake.render_and_overlay.assert_not_called()

    def test_a_crash_in_visuals_is_a_plain_gate_error(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx, mpt = self.make(Path(raw))
            fake = type(sys)("visuals")
            fake.render_and_overlay = mock.Mock(side_effect=RuntimeError("remotion failed"))
            with mock.patch.object(mv, "load_visuals_module", return_value=fake), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(mv.GateError) as raised:
                    mv.step_visuals(ctx, mpt, [])
            self.assertIn("remotion failed", str(raised.exception))


class MptStepOrderTests(unittest.TestCase):
    """step_mpt: Whisper timing run first, then the footage, then the video run WITHOUT captions."""

    def test_order_and_commands(self):
        events = []
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            ctx = mv.Ctx(mv.parse_args(["x.json"]))
            ctx.script = good_script()
            ctx.work = tmp / "work"
            ctx.work.mkdir()
            ctx.report["captions"] = {}
            video = tmp / "final-1.mp4"
            video.write_text("v")
            setup = {"caption": {"font_size": 69, "stroke_width": 6, "box_height": 141, "position_percent": 73.07},
                     "footage": "local", "local_files": [Path("/m/a.mp4")], "source": None}
            whisper = {"cues": [], "differences": [], "task_dir": tmp / "tasks" / "W", "task_id": "W", "log_text": "detected language: 'en'"}
            captions = {"words": [], "phrases": [], "stats": {}, "style": {}}

            def fake_whisper(c, narration, st, script_text, texts):
                events.append("whisper")
                c.report["mpt"] = {"subtitle_run": {"task_id": "W"}}
                return whisper

            def fake_captions(c, w, st, total):
                events.append("captions")
                return captions

            seen = {}

            def fake_run(c, cmd, log_path, record):
                events.append("video")
                seen["cmd"] = cmd
                record.update(log=str(log_path), exit_code=0)
                return ["generating video"], {"videos": [str(video)], "subtitle_path": "", "audio_duration": 72}

            with mock.patch.object(mv, "step_whisper_timing", side_effect=fake_whisper), mock.patch.object(mv, "step_captions", side_effect=fake_captions), \
                    mock.patch.object(mv, "run_mpt_task", side_effect=fake_run), mock.patch.object(mv, "find_tool", return_value="/bin/uv"), \
                    mock.patch.object(mv, "MPT_DIR", tmp / "mpt"), contextlib.redirect_stdout(io.StringIO()):
                mpt = mv.step_mpt(ctx, Path("/w/narration.wav"), setup, [], 10.0)
        self.assertEqual(events, ["whisper", "captions", "video"])
        self.assertIn("--no-subtitle-enabled", seen["cmd"])
        self.assertNotIn("--subtitle-enabled", seen["cmd"])
        self.assertNotIn("--stop-at", seen["cmd"])
        self.assertEqual(mpt["captions"], captions)
        self.assertEqual(mpt["extra_task_dirs"], [whisper["task_dir"]])  # cleanup must remove the Whisper run too
        self.assertEqual(mpt["video"], video)
        names = {c["name"]: c["ok"] for c in ctx.checks}
        self.assertTrue(names["no burned-in captions"])
        self.assertTrue(any("saved task params" in w for w in ctx.warnings))  # the fake MPT task folder has no script.json
        self.assertEqual(ctx.report["mpt"]["subtitle_run"], {"task_id": "W"})  # the Whisper run's entry survives
        self.assertEqual(ctx.report["mpt"]["exit_code"], 0)


class OwnFootageStepTests(unittest.TestCase):
    KEY = "SECRETKEY-1234567890-abcdef"

    def make_ctx(self):
        ctx = mv.Ctx(mv.parse_args(["content/x/script.json"]))
        ctx.script = good_script()
        ctx.work = Path("/nonexistent/work")
        return ctx

    def fake_result(self):
        return {
            "path": Path("/nonexistent/work/broll.mp4"), "segments": [{"start": 0.0, "end": 4.0, "phrase": "refrigerator", "line_indexes": [0]}],
            "credits": [{"provider": "pixabay", "id": 5, "user": "Ann", "page_url": "https://pixabay.com/videos/a-5/"}],
            "credit_lines": ["Video by Ann on Pixabay: https://pixabay.com/videos/a-5/"],
            "report": {"provider": "pixabay", "clips_used": 1, "downloads": 1, "clip_cache_hits": 0, "search_requests": 2, "search_cache_hits": 1,
                       "broll_seconds": 4.0, "credits": [],
                       "segments": [{"start": 0.0, "end": 4.0, "phrase": "refrigerator", "fallback": False, "searched_phrase": "refrigerator", "clip_id": 5}]},
        }

    def run_step(self, ctx, **patches):
        with mock.patch.object(mv, "find_tool", side_effect=lambda name: f"/bin/{name}"), \
                mock.patch.object(mv.footage, "load_pixabay_key", return_value=patches.get("key", self.KEY)), \
                mock.patch.object(mv.footage, "build_broll", **({"side_effect": patches["error"]} if "error" in patches else {"return_value": self.fake_result()})), \
                contextlib.redirect_stdout(io.StringIO()):
            return mv.step_own_footage(ctx, [{"index": 0, "start": 0.0, "end": 4.0}], 4.0)

    def test_report_gets_a_footage_section_without_the_key(self):
        ctx = self.make_ctx()
        result = self.run_step(ctx)
        self.assertEqual(result["credit_lines"], ["Video by Ann on Pixabay: https://pixabay.com/videos/a-5/"])
        self.assertEqual(ctx.report["footage"]["mode"], "own")
        self.assertEqual(ctx.report["footage"]["clips_used"], 1)
        self.assertNotIn(self.KEY, json.dumps(ctx.report))
        self.assertNotIn(self.KEY, json.dumps(ctx.checks))

    def test_a_fallback_search_is_a_warning(self):
        ctx = self.make_ctx()
        result = self.fake_result()
        result["report"]["segments"][0].update(fallback=True, searched_phrase="kitchen")
        with mock.patch.object(mv, "find_tool", side_effect=lambda name: f"/bin/{name}"), \
                mock.patch.object(mv.footage, "load_pixabay_key", return_value=self.KEY), \
                mock.patch.object(mv.footage, "build_broll", return_value=result), \
                contextlib.redirect_stdout(io.StringIO()):
            mv.step_own_footage(ctx, [], 4.0)
        self.assertTrue(any("refrigerator" in w and "kitchen" in w for w in ctx.warnings))

    def test_an_unrelated_stand_in_is_named_as_such_in_the_warning(self):
        for related, expect in ((True, False), (False, True)):
            ctx = self.make_ctx()
            result = self.fake_result()
            result["report"]["segments"][0].update(fallback=True, searched_phrase="kitchen", fallback_related=related)
            with mock.patch.object(mv, "find_tool", side_effect=lambda name: f"/bin/{name}"), \
                    mock.patch.object(mv.footage, "load_pixabay_key", return_value=self.KEY), \
                    mock.patch.object(mv.footage, "build_broll", return_value=result), \
                    contextlib.redirect_stdout(io.StringIO()):
                mv.step_own_footage(ctx, [], 4.0)
            self.assertEqual(any("NOT about the phrase" in w for w in ctx.warnings), expect)

    def test_footage_errors_become_plain_gate_errors(self):
        ctx = self.make_ctx()
        with self.assertRaises(mv.GateError) as raised:
            self.run_step(ctx, error=mv.footage.FootageError("No usable stock clip was found for line 3"))
        self.assertIn("Stock footage:", str(raised.exception))
        self.assertIn("line 3", str(raised.exception))

    def test_missing_key_is_a_plain_gate_error(self):
        with self.assertRaises(mv.GateError) as raised:
            self.run_step(self.make_ctx(), key=None)
        self.assertIn("pixabay_api_keys", str(raised.exception))

    def test_credits_are_exactly_the_clips_used(self):
        ctx = self.make_ctx()
        mpt = {"broll": self.fake_result()}
        with contextlib.redirect_stdout(io.StringIO()):
            lines = mv.step_credits(ctx, mpt, local=False)
        self.assertEqual(lines, ["Video by Ann on Pixabay: https://pixabay.com/videos/a-5/"])
        self.assertEqual(ctx.report["credits"]["lines"], lines)
        self.assertFalse(any("credited all" in n for n in ctx.report["credits"]["notes"]))
        caption = mv.build_caption(good_script(), lines)
        self.assertIn("Video by Ann on Pixabay: https://pixabay.com/videos/a-5/", caption)

    def test_order_check_passes_when_mpt_kept_our_pictures(self):
        ctx = self.make_ctx()
        ctx.report["footage"] = {"mode": "own"}
        frames = [{"seconds": 2.0, "diff": 3.1, "same": True}, {"seconds": 6.0, "diff": 5.2, "same": True}]
        with mock.patch.object(mv, "find_tool", return_value="/bin/ffmpeg"), mock.patch.object(mv.footage, "check_order", return_value=frames), \
                contextlib.redirect_stdout(io.StringIO()):
            mv.check_footage_order(ctx, Path("/w/mpt.mp4"), self.fake_result())
        self.assertEqual(ctx.report["footage"]["order_check"]["frames"], frames)
        self.assertTrue(ctx.checks[-1]["ok"])

    def test_order_check_fails_loudly_when_mpt_shuffled_or_looped(self):
        ctx = self.make_ctx()
        ctx.report["footage"] = {"mode": "own"}
        frames = [{"seconds": 2.0, "diff": 3.1, "same": True}, {"seconds": 6.0, "diff": 88.0, "same": False}]
        with mock.patch.object(mv, "find_tool", return_value="/bin/ffmpeg"), mock.patch.object(mv.footage, "check_order", return_value=frames), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(mv.GateError) as raised:
                mv.check_footage_order(ctx, Path("/w/mpt.mp4"), self.fake_result())
        self.assertIn("footage order kept failed", str(raised.exception))
        self.assertIn("6 s", str(raised.exception))

    def test_failure_output_never_shows_an_api_key_in_a_url(self):
        ctx = self.make_ctx()
        ctx.script = {}  # no id yet: nothing is written
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            mv.fail(ctx, "FAILED", f"Pixabay broke: https://pixabay.com/api/videos/?key={self.KEY}&q=x")
        self.assertNotIn(self.KEY, err.getvalue())
        self.assertIn("key=***", err.getvalue())

    def test_failed_report_never_holds_an_api_key_in_a_url(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            ctx = self.make_ctx()
            ctx.work = tmp
            with mock.patch.object(mv, "WORK_ROOT", tmp), contextlib.redirect_stderr(io.StringIO()):
                mv.fail(ctx, "FAILED", f"Pixabay broke: ?key={self.KEY}&q=x", extra={"traceback": f"Traceback ... ?key={self.KEY}&q=x"})
            self.assertNotIn(self.KEY, (tmp / "failed-report.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------
# Hook card, cover, topic on screen, per-word caption size, publish info
# --------------------------------------------------------------------------------------


def hook_script(**hook_over):
    script = good_script()
    script["hook"] = {"line1": "Your fridge is", "line2": "secretly a heater", "accent": "heater", **hook_over}
    script["topic_noun"] = "refrigerator"
    script["pinned_comment"] = "Did you know? Yes or no 👇"
    return script


class NewScriptFieldTests(unittest.TestCase):
    def test_a_script_with_hook_topic_noun_and_pinned_comment_is_valid(self):
        errors, warnings = mv.validate_script(hook_script())
        self.assertEqual((errors, warnings), ([], []))

    def test_scripts_without_the_new_fields_still_pass(self):
        s = good_script()
        self.assertTrue(all(k not in s for k in ("hook", "topic_noun", "pinned_comment")))
        self.assertEqual(errors_of(s), [])

    def test_null_fields_count_as_absent(self):
        s = good_script()
        s.update(hook=None, topic_noun=None, pinned_comment=None)
        self.assertEqual(errors_of(s), [])

    def test_hook_problems_are_listed_with_their_field_names(self):
        for over, needle in (({"line1": "x" * 27}, "hook.line1"), ({"line2": "y" * 31}, "hook.line2"), ({"accent": "fridge now"}, "ONE word"),
                             ({"accent": "banana"}, "not a word of"), ({"line1": ""}, "hook.line1")):
            errors = errors_of(hook_script(**over))
            self.assertTrue(any(needle in e for e in errors), (over, errors))

    def test_a_hook_must_be_an_object(self):
        s = good_script()
        s["hook"] = "Your fridge"
        self.assertTrue(any("hook must be an object" in e for e in errors_of(s)))

    def test_line_zero_may_not_have_a_panel_when_there_is_a_hook(self):
        s = hook_script()
        s["lines"][0]["visual"] = {"type": "stat", "value": "5", "label": "five"}
        errors = errors_of(s)
        self.assertTrue(any("lines[0].visual must be empty" in e for e in errors), errors)
        del s["hook"]
        self.assertEqual(errors_of(s), [])  # without a hook line 0 may have one, as before

    def test_topic_noun_is_a_short_english_phrase(self):
        for bad in ("Kühlschrank", "", "x", "a" * 41, 5):
            s = good_script()
            s["topic_noun"] = bad
            self.assertTrue(any("topic_noun" in e for e in errors_of(s)), bad)
        s = good_script()
        s["topic_noun"] = "washing machine"
        self.assertEqual(errors_of(s), [])

    def test_pinned_comment_limit_150(self):
        s = good_script()
        s["pinned_comment"] = "x" * 150
        self.assertEqual(errors_of(s), [])
        s["pinned_comment"] = "x" * 151
        self.assertTrue(any("pinned_comment" in e for e in errors_of(s)))
        s["pinned_comment"] = "  "
        self.assertTrue(any("pinned_comment" in e for e in errors_of(s)))


@unittest.skipUnless(FONT_FILE.is_file(), "MoneyPrinterTurbo font not found")
class PerWordCaptionSizeTests(unittest.TestCase):
    NORMAL = "The fridge moves heat out of the box and the cold air stays in because the door is closed."  # 19 short words

    def style(self, *extra, repeat=6):
        return mv.pick_caption_style([self.NORMAL] * repeat + list(extra), FONT_FILE)

    def test_the_percentile_is_nearest_rank(self):
        self.assertEqual(mv.percentile([5, 1, 3, 2, 4], 0.9), 5)
        self.assertEqual(mv.percentile(list(range(1, 11)), 0.9), 9)
        self.assertEqual(mv.percentile(list(range(1, 101)), 0.9), 90)
        self.assertEqual(mv.percentile([7], 0.9), 7)
        self.assertEqual(mv.percentile([], 0.9), 0.0)

    def test_one_long_word_does_not_shrink_the_whole_video(self):
        before = self.style()
        style = self.style("Das ist Kühlschrankkompressor.")
        self.assertEqual(before["font_size"], mv.CAPTION_FONT_MAX)
        self.assertEqual(style["font_size"], mv.CAPTION_FONT_MAX)  # the base size is what it was without the long word
        self.assertEqual(list(style["word_sizes"]), ["Kühlschrankkompressor."])
        own = style["word_sizes"]["Kühlschrankkompressor."]
        self.assertLess(own, mv.CAPTION_FONT_MAX)
        self.assertGreaterEqual(own, mv.CAPTION_FONT_MIN)
        self.assertLessEqual(style["widest_word_px"], mv.CAPTION_MAX_WORD_PX)  # it fits at ITS size ...
        self.assertIsNone(mv.caption_word_problem(style))  # ... so there is nothing to report

    def test_the_base_size_comes_from_the_ninetieth_percentile_word(self):
        # 10 words: nine short ones and one 21-letter word: the 90th-percentile word is the 9th of 10 = a short one
        text = "Dein Kühlschrank ist ein Gerät, das Wärme nach draußen schiebt, Kühlschrankkompressor."
        style = mv.pick_caption_style([text], FONT_FILE)
        words = text.split()
        self.assertEqual(len(words), 11)
        self.assertEqual(style["font_size"], mv.CAPTION_FONT_MAX)
        self.assertEqual(list(style["word_sizes"]), ["Kühlschrankkompressor."])

    def test_when_many_words_are_wide_the_base_size_shrinks_too(self):
        # every word of the script is long: the 90th-percentile word is long, so the base size must come down
        text = "Kühlschrankkompressor Flugzeugtriebwerken Wärmepumpenanlage Gefrierschrank."
        style = mv.pick_caption_style([text], FONT_FILE)
        self.assertLess(style["font_size"], mv.CAPTION_FONT_MAX)
        self.assertLessEqual(style["widest_word_px"], mv.CAPTION_MAX_WORD_PX + 2)

    def test_words_that_fit_at_the_base_size_get_no_size_of_their_own(self):
        style = self.style()
        self.assertEqual(style["word_sizes"], {})
        self.assertFalse(style["size_limited_by_word"])

    def test_a_word_too_wide_even_at_the_smallest_size_is_still_reported(self):
        style = self.style("Das ist Donaudampfschifffahrtsgesellschaftskapitaensmuetze.")
        self.assertEqual(style["font_size"], mv.CAPTION_FONT_MAX)
        problem = mv.caption_word_problem(style)
        self.assertIsNotNone(problem)
        self.assertIn("Donaudampfschifffahrtsgesellschaftskapitaensmuetze", problem)

    def test_the_summary_sentence_names_the_words_with_their_own_size(self):
        text = mv.caption_size_summary(self.style("Das ist Kühlschrankkompressor."))
        self.assertIn("Kühlschrankkompressor.", text)
        self.assertIn("own smaller size", text)
        self.assertNotIn("own smaller size", mv.caption_size_summary(self.style()))

    def test_the_payload_carries_the_own_size_only_for_those_words(self):
        words = [{"text": "Das", "start": 0.0, "end": 0.3, "timing": "heard"}, {"text": "Kühlschrankkompressor.", "start": 0.3, "end": 1.0}]
        payload = mv.caption_payload(words, {"Kühlschrankkompressor.": 70}, 120)
        self.assertEqual(payload, [{"text": "Das", "start": 0.0, "end": 0.3}, {"text": "Kühlschrankkompressor.", "start": 0.3, "end": 1.0, "font_size": 70}])
        self.assertEqual(mv.caption_payload(words, {"Kühlschrankkompressor.": 120}, 120)[1], {"text": "Kühlschrankkompressor.", "start": 0.3, "end": 1.0})  # not smaller: none

    def test_a_caption_unit_with_a_lone_dash_is_measured_as_shown(self):
        style = mv.pick_caption_style(["Tom - Jerry"], FONT_FILE)  # the dash is shown together with 'Tom'
        self.assertEqual(style["font_size"], mv.CAPTION_FONT_MAX)


@unittest.skipUnless(FONT_FILE.is_file(), "MoneyPrinterTurbo font not found")
class HookStyleTests(unittest.TestCase):
    def hook(self, line1, line2, accent="Why"):
        return {"line1": line1, "line2": line2, "accent": accent}

    def test_short_lines_get_big_letters_up_to_the_maximum(self):
        style = mv.pick_hook_style(self.hook("Hot", "Cold", "Hot"), FONT_FILE)
        self.assertEqual(style["font_size"], mv.HOOK_FONT_MAX)
        self.assertFalse(style["below_target"])
        self.assertFalse(style["too_small"])

    def test_the_widest_line_with_its_outline_fits_the_width_for_all_sizes(self):
        for line1, line2 in (("Your fridge is", "secretly a heater"), ("How does a microwave", "actually heat food?"), ("Dein Kühlschrank", "ist heimlich eine Heizung"),
                             ("Does GPS need", "the internet? No.")):
            style = mv.pick_hook_style(self.hook(line1, line2, line1.split()[0]), FONT_FILE)
            self.assertLessEqual(style["widest_px"], mv.HOOK_MAX_WIDTH_PX, (line1, line2))
            self.assertLessEqual(max(style["line_px"]), mv.HOOK_MAX_WIDTH_PX)
            self.assertEqual(style["stroke_width"], mv.hook_stroke_width(style["font_size"]))
            # the biggest size that fits: one more pixel of font would be too wide
            measure = mv.FontMeasure(FONT_FILE.read_bytes())
            wide = max(measure.text_width(line1, 1000), measure.text_width(line2, 1000)) / 1000
            bigger = style["font_size"] + 1
            if style["font_size"] < mv.HOOK_FONT_MAX:
                self.assertGreater(wide * bigger + 2 * mv.hook_stroke_width(bigger), mv.HOOK_MAX_WIDTH_PX, (line1, line2))

    def test_both_lines_share_one_size(self):
        style = mv.pick_hook_style(self.hook("Hot outside.", "Frozen inside. Why?"), FONT_FILE)
        self.assertEqual(style["widest_line"], "Frozen inside. Why?")
        self.assertLess(style["line_px"][0], style["line_px"][1])

    def test_the_microwave_example_is_below_96_px_and_says_so(self):
        # "How does a microwave" is 1129 px wide at 96 px: no size >= 96 px can fit into 1000 px. The card still works (a warning, not a stop).
        style = mv.pick_hook_style(self.hook("How does a microwave", "actually heat food?", "microwave"), FONT_FILE)
        self.assertLess(style["font_size"], mv.HOOK_FONT_TARGET)
        self.assertGreaterEqual(style["font_size"], mv.HOOK_FONT_MIN)
        self.assertTrue(style["below_target"])
        self.assertIsNone(mv.hook_size_problem(style))

    def test_a_line_that_would_need_tiny_letters_stops_the_run_and_names_the_line(self):
        style = mv.pick_hook_style(self.hook("Woher weiß das deine Funkuhr?", "Zeitumstellung am Sonntag", "Funkuhr?"), FONT_FILE)
        self.assertTrue(style["too_small"])
        problem = mv.hook_size_problem(style)
        self.assertIn("Woher weiß das deine Funkuhr?", problem)
        self.assertIn(f"{mv.HOOK_FONT_MIN} px", problem)
        self.assertIn("Shorten", problem)

    def test_an_unreadable_font_falls_back_to_a_safe_estimate(self):
        style = mv.pick_hook_style(self.hook("Your fridge is", "secretly a heater", "heater"), Path("/nonexistent/font.ttf"))
        self.assertIn("safe estimate", style["note"])
        self.assertLessEqual(style["widest_px"], mv.HOOK_MAX_WIDTH_PX)

    def test_the_card_sits_where_the_overlay_puts_it(self):
        visuals = importlib_visuals()
        self.assertEqual(mv.HOOK_BAND_CROP, f"crop={visuals.HOOK_W}:{visuals.HOOK_H}:{visuals.HOOK_X}:{visuals.HOOK_Y}")


def importlib_visuals():
    import importlib
    return importlib.import_module("visuals")


class HookStepTests(unittest.TestCase):
    TIMINGS = [{"index": 0, "start": 0.1, "end": 2.0}, {"index": 1, "start": 2.4, "end": 6.0}]

    def make(self, script=None, extra=()):
        ctx = mv.Ctx(mv.parse_args(["x.json", *extra]))
        ctx.script = script or hook_script()
        return ctx

    def run_step(self, ctx, timings=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return mv.step_hook(ctx, timings or self.TIMINGS)

    def test_no_hook_no_hook_end(self):
        ctx = self.make(good_script())
        self.assertIsNone(self.run_step(ctx))
        self.assertIsNone(ctx.hook_end)
        self.assertEqual(ctx.checks, [])

    def test_a_short_line_zero_keeps_the_card_up_for_2_5_seconds(self):
        ctx = self.make(hook_script())
        ctx.script["lines"][1]["visual"] = None  # a panel at 2.4 s would clash: see the next test
        self.assertEqual(self.run_step(ctx), 2.5)
        self.assertEqual(ctx.hook_end, 2.5)
        self.assertEqual(ctx.report["hook"]["hook_end"], 2.5)
        self.assertEqual(ctx.report["hook"]["fade_seconds"], 0.25)
        self.assertTrue(ctx.checks[-1]["ok"])
        self.assertIn("2.50 s", ctx.checks[-1]["detail"])

    def test_a_panel_that_would_start_under_the_card_stops_the_run(self):
        ctx = self.make(hook_script())  # good_script's line 1 has a visual and starts at 2.4 s, the card is up until 2.5 s
        with self.assertRaises(mv.GateError) as raised:
            self.run_step(ctx)
        self.assertIn("hook timing failed", str(raised.exception))
        self.assertIn("line 1", str(raised.exception))

    def test_a_panel_that_starts_while_the_card_fades_out_stops_the_run(self):
        ctx = self.make(hook_script())
        # line 0 ends at 3.0 s: the card is fully visible until 3.0 s and fades out until 3.25 s; the panel of line 1 starts at 3.1 s
        timings = [{"index": 0, "start": 0.0, "end": 3.0}, {"index": 1, "start": 3.1, "end": 7.0}]
        with self.assertRaises(mv.GateError) as raised:
            self.run_step(ctx, timings)
        self.assertIn("hook timing failed", str(raised.exception))
        self.assertIn("3.10 s", str(raised.exception))
        self.assertIn("fades out until 3.25 s", str(raised.exception))

    def test_a_panel_that_starts_when_the_fade_is_over_is_fine(self):
        ctx = self.make(hook_script())
        timings = [{"index": 0, "start": 0.0, "end": 3.0}, {"index": 1, "start": 3.25, "end": 7.0}]
        self.assertEqual(self.run_step(ctx, timings), 3.0)
        self.assertTrue(ctx.checks[-1]["ok"])
        self.assertIn("before 3.25 s", ctx.checks[-1]["detail"])
        self.assertEqual(ctx.report["hook"]["panels_free_from"], 3.25)

    def test_without_panels_there_is_no_clash(self):
        ctx = self.make(hook_script(), extra=["--no-visuals"])
        self.assertEqual(self.run_step(ctx), 2.5)

    def test_a_long_line_zero_is_capped_at_3_5_seconds(self):
        ctx = self.make(hook_script())
        timings = [{"index": 0, "start": 0.0, "end": 5.0}, {"index": 1, "start": 5.3, "end": 8.0}]
        self.assertEqual(self.run_step(ctx, timings), 3.5)

    def test_the_end_of_line_zero_in_between(self):
        ctx = self.make(hook_script())
        timings = [{"index": 0, "start": 0.0, "end": 3.2}, {"index": 1, "start": 3.5, "end": 8.0}]
        self.assertEqual(self.run_step(ctx, timings), 3.2)


class HookVisualsStepTests(unittest.TestCase):
    """step_visuals with a hook: the captions under the card are not drawn, the card goes to render_and_overlay."""

    def make(self, tmp, script=None):
        ctx = mv.Ctx(mv.parse_args(["x.json"]))
        ctx.script = script or hook_script()
        ctx.work = tmp
        ctx.hook_end = 2.5
        ctx.hook_style = {"font_size": 100, "stroke_width": 9}
        words = [{"text": w, "start": 0.3 * k, "end": 0.3 * (k + 1), "timing": "heard"}
                 for k, w in enumerate(" ".join(line["text"] for line in ctx.script["lines"]).split())]
        mpt = {"video": tmp / "mpt.mp4", "captions": {"words": words, "phrases": [], "stats": {},
                                                      "style": {"font_size": 69, "stroke_width": 6, "box_height": 141,
                                                                "word_sizes": {"box.": 50}}}}
        return ctx, mpt

    def run_step(self, ctx, mpt):
        calls = []

        def fake_render(base, script, timings, out, work, captions=None, hook=None):
            calls.append({"captions": captions, "hook": hook})
            Path(out).write_text("video")
            return {"panels": 1, "render_seconds": 1.0, "out": out}

        fake = type(sys)("visuals")
        fake.render_and_overlay = fake_render
        with mock.patch.object(mv, "load_visuals_module", return_value=fake), contextlib.redirect_stdout(io.StringIO()):
            mv.step_visuals(ctx, mpt, [])
        return calls

    def test_the_words_under_the_card_are_not_drawn_and_the_rest_is_checked_against_the_script(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx, mpt = self.make(Path(raw))
            calls = self.run_step(ctx, mpt)
        drawn = calls[0]["captions"]["words"]
        self.assertEqual([w["text"] for w in drawn], ["heat", "out", "of", "the", "box."])
        self.assertEqual(drawn[0]["start"], 2.5)  # "heat" is spoken 2.4-2.7 s: it starts when the card ends
        self.assertTrue(all(w["start"] >= 2.5 for w in drawn))
        check = next(c for c in ctx.checks if c["name"] == "captions match script (as drawn)")
        self.assertTrue(check["ok"])
        self.assertIn("hook card", check["detail"])
        self.assertEqual(ctx.report["captions"]["hidden_under_hook"],
                         {"until": 2.5, "words_hidden": 8, "words_started_late": 1, "script_words_not_drawn": 8})

    def test_the_card_goes_to_the_overlay_with_its_size_and_end(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx, mpt = self.make(Path(raw))
            calls = self.run_step(ctx, mpt)
        self.assertEqual(calls[0]["hook"], {"line1": "Your fridge is", "line2": "secretly a heater", "accent": "heater",
                                            "font_size": 100, "stroke_width": 9, "hook_end": 2.5})
        self.assertIn("and the hook card", ctx.checks[-1]["detail"])

    def test_a_word_with_its_own_size_carries_it(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx, mpt = self.make(Path(raw))
            drawn = self.run_step(ctx, mpt)[0]["captions"]["words"]
        self.assertEqual([w.get("font_size") for w in drawn], [None, None, None, None, 50])
        self.assertIn("1 with their own smaller size", ctx.checks[-1]["detail"])

    def test_without_a_hook_nothing_is_hidden_and_no_hook_argument_is_passed(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx, mpt = self.make(Path(raw), good_script())
            ctx.hook_end = None
            calls = self.run_step(ctx, mpt)
        self.assertIsNone(calls[0]["hook"])
        self.assertEqual(len(calls[0]["captions"]["words"]), 13)
        self.assertNotIn("hidden_under_hook", ctx.report.get("captions", {}))

    def test_a_changed_word_after_the_hidden_start_is_still_caught(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx, mpt = self.make(Path(raw))
            mpt["captions"]["words"][-1]["text"] = "BOX."
            with self.assertRaises(mv.GateError) as raised:
                self.run_step(ctx, mpt)
        self.assertIn("captions match script (as drawn) failed", str(raised.exception))


class CoverTests(unittest.TestCase):
    def test_the_command_takes_frame_zero_as_a_jpeg_at_about_quality_90(self):
        cmd = mv.cover_command("ffmpeg", Path("/w/final.mp4"), Path("/w/cover.jpg"))
        self.assertEqual(cmd[cmd.index("-ss") + 1], "0")
        self.assertEqual(cmd[cmd.index("-frames:v") + 1], "1")
        self.assertEqual(cmd[cmd.index("-q:v") + 1], mv.COVER_QUALITY)
        self.assertEqual(cmd[-1], "/w/cover.jpg")
        self.assertEqual(cmd[cmd.index("-i") + 1], "/w/final.mp4")

    def test_write_cover_returns_the_probe_and_fails_plainly(self):
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw) / "cover.jpg"

            def fake_run(cmd, timeout, what, cwd=None):
                Path(cmd[-1]).write_bytes(b"jpeg")
                return mock.Mock(returncode=0, stderr="")

            with mock.patch.object(mv, "run_cmd", side_effect=fake_run), mock.patch.object(mv, "find_tool", return_value="/bin/ffprobe"), \
                    mock.patch.object(mv, "ffprobe_info", return_value={"width": 1080, "height": 1920}):
                self.assertEqual(mv.write_cover("ffmpeg", Path("/w/f.mp4"), out), {"width": 1080, "height": 1920})
            self.assertTrue(out.is_file())
            out.unlink()
            with mock.patch.object(mv, "run_cmd", return_value=mock.Mock(returncode=1, stderr="no such file")):
                with self.assertRaises(mv.GateError) as raised:
                    mv.write_cover("ffmpeg", Path("/w/f.mp4"), out)
            self.assertIn("cover frame could not be saved", str(raised.exception))

    def test_the_final_checks_write_the_cover_and_check_that_the_hook_is_in_it(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            ctx = mv.Ctx(mv.parse_args(["x.json"]))
            ctx.script, ctx.work, ctx.hook_end = hook_script(), tmp, 2.5
            ctx.media_dir = tmp
            ctx.report["captions"] = {}
            (tmp / "sheet.png").write_text("sheet")
            words = [{"text": "a", "start": 0.0, "end": 0.5}]
            mpt = {"video": tmp / "mpt.mp4", "captions": {"words": words}}
            final = tmp / "final.mp4"
            final.write_text("v")
            info = {"duration": 60.0, "width": 1080, "height": 1920, "has_audio": True, "has_video": True}
            with mock.patch.object(mv, "find_tool", side_effect=lambda n: f"/bin/{n}"), mock.patch.object(mv, "ffprobe_info", return_value=info), \
                    mock.patch.object(mv, "run_cmd", return_value=mock.Mock(returncode=0, stderr="", stdout="")), \
                    mock.patch.object(mv, "write_cover", return_value={"width": 1080, "height": 1920}) as write, \
                    mock.patch.object(mv, "hook_visibility", return_value=[{"seconds": 0.0, "diff": 31.0, "seen": True}, {"seconds": 2.4, "diff": 30.0, "seen": True}]), \
                    contextlib.redirect_stdout(io.StringIO()):
                mv.step_final_checks(ctx, final, mpt, 60.0)
            names = {c["name"]: c for c in ctx.checks}
            self.assertTrue(names["cover frame"]["ok"])
            self.assertIn("hook card", names["cover frame"]["detail"])
            self.assertTrue(names["hook visible at 0 s"]["ok"])
            self.assertEqual(ctx.cover, tmp / "cover.jpg")
            self.assertEqual(write.call_args[0][2], tmp / "cover.jpg")
            self.assertEqual(ctx.report["hook"]["visibility_check"]["frames"][0]["diff"], 31.0)
            self.assertEqual(ctx.report["cover"]["size"], "1080x1920")

    def test_a_hook_that_is_not_in_the_picture_fails_the_run(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            ctx = mv.Ctx(mv.parse_args(["x.json"]))
            ctx.script, ctx.work, ctx.hook_end, ctx.media_dir = hook_script(), tmp, 2.5, tmp
            ctx.report["captions"] = {}
            (tmp / "sheet.png").write_text("sheet")
            mpt = {"video": tmp / "mpt.mp4", "captions": {"words": [{"text": "a", "start": 0.0, "end": 0.5}]}}
            final = tmp / "final.mp4"
            final.write_text("v")
            info = {"duration": 60.0, "width": 1080, "height": 1920, "has_audio": True, "has_video": True}
            with mock.patch.object(mv, "find_tool", side_effect=lambda n: f"/bin/{n}"), mock.patch.object(mv, "ffprobe_info", return_value=info), \
                    mock.patch.object(mv, "run_cmd", return_value=mock.Mock(returncode=0, stderr="", stdout="")), \
                    mock.patch.object(mv, "write_cover", return_value={"width": 1080, "height": 1920}), \
                    mock.patch.object(mv, "hook_visibility", return_value=[{"seconds": 0.0, "diff": 0.4, "seen": False}, {"seconds": 2.4, "diff": 0.5, "seen": False}]), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(mv.GateError) as raised:
                    mv.step_final_checks(ctx, final, mpt, 60.0)
            self.assertIn("hook visible at 0 s failed", str(raised.exception))

    def test_a_cover_of_the_wrong_size_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            ctx = mv.Ctx(mv.parse_args(["x.json"]))
            ctx.script, ctx.work, ctx.media_dir = good_script(), tmp, tmp
            ctx.report["captions"] = {}
            (tmp / "sheet.png").write_text("sheet")
            mpt = {"video": tmp / "mpt.mp4", "captions": {"words": [{"text": "a", "start": 0.0, "end": 0.5}]}}
            final = tmp / "final.mp4"
            final.write_text("v")
            info = {"duration": 60.0, "width": 1080, "height": 1920, "has_audio": True, "has_video": True}
            with mock.patch.object(mv, "find_tool", side_effect=lambda n: f"/bin/{n}"), mock.patch.object(mv, "ffprobe_info", return_value=info), \
                    mock.patch.object(mv, "run_cmd", return_value=mock.Mock(returncode=0, stderr="", stdout="")), \
                    mock.patch.object(mv, "write_cover", return_value={"width": 720, "height": 1280}), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(mv.GateError) as raised:
                    mv.step_final_checks(ctx, final, mpt, 60.0)
            self.assertIn("cover frame failed", str(raised.exception))

    def test_hook_visibility_compares_the_card_band_of_the_final_with_the_video_underneath(self):
        calls = []

        def fake_band(ffmpeg, video, seconds, crop, w, h, run=None):
            calls.append((Path(video).name, seconds, crop, w, h))
            return bytes([200 if Path(video).name == "final.mp4" else 20]) * (w * h)

        with mock.patch.object(mv.footage, "band_signature", side_effect=fake_band):
            results = mv.hook_visibility("ffmpeg", Path("/w/final.mp4"), Path("/w/mpt.mp4"), 2.5)
        self.assertEqual([r["seconds"] for r in results], [0.0, 2.4])
        self.assertTrue(all(r["seen"] and r["diff"] == 180.0 for r in results))
        self.assertTrue(all(c[2] == mv.HOOK_BAND_CROP for c in calls))
        with mock.patch.object(mv.footage, "band_signature", return_value=bytes(108 * 45)):  # identical pictures = no card in the video
            self.assertFalse(any(r["seen"] for r in mv.hook_visibility("ffmpeg", Path("/w/final.mp4"), Path("/w/mpt.mp4"), 2.5)))


class PublishInfoTests(unittest.TestCase):
    def test_title_comment_hook_and_runtime(self):
        info = mv.publish_info(hook_script(), 58.4)
        self.assertEqual(info["youtube_title"], "How your fridge really works")
        self.assertEqual((info["title_length"], info["title_limit"]), (28, 70))
        self.assertEqual(info["pinned_comment"], "Did you know? Yes or no 👇")
        self.assertEqual(info["hook"], {"line1": "Your fridge is", "line2": "secretly a heater", "accent": "heater"})
        self.assertEqual((info["topic_noun"], info["runtime_seconds"]), ("refrigerator", 58.4))

    def test_a_script_without_the_new_fields(self):
        info = mv.publish_info(good_script(), None)
        self.assertEqual((info["pinned_comment"], info["hook"], info["runtime_seconds"]), (None, None, None))
        self.assertEqual(info["topic_noun"], "refrigerator")  # the first video term is the default noun


class OutputWithCoverTests(unittest.TestCase):
    """step_output with a cover: it is copied into the review folder, listed in the report and survives the cleanup."""

    WORDS, PHRASES = OutputAndCleanupTests.WORDS, OutputAndCleanupTests.PHRASES
    make_ctx = OutputAndCleanupTests.make_ctx  # the same fake tree as the plain output tests

    def run_steps(self, keep_work):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            ctx, mpt = self.make_ctx(tmp, keep_work)
            (ctx.work / "cover.jpg").write_bytes(b"jpegdata")
            ctx.cover = ctx.work / "cover.jpg"
            ctx.script = hook_script()
            ctx.report["durations"] = {"final": 61.5}
            with mock.patch.object(mv, "REVIEW_ROOT", tmp / "review"), mock.patch.object(mv, "MPT_DIR", tmp / "mpt"), \
                    contextlib.redirect_stdout(io.StringIO()):
                folder = mv.step_output(ctx, ctx.work / "final-visuals.mp4", ctx.work / "sheet.png", ["credit"], mpt)
                report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
                mv.step_cleanup(ctx, mpt, folder)
                after_cleanup = json.loads((folder / "report.json").read_text(encoding="utf-8"))
            return {"files": sorted(p.name for p in folder.iterdir()), "report": report, "after_cleanup": after_cleanup,
                    "cover": (folder / "cover.jpg").read_bytes(), "folder": str(folder)}

    def test_the_cover_is_in_the_review_folder_and_in_the_report(self):
        r = self.run_steps(keep_work=False)
        self.assertEqual(r["files"], ["caption.txt", "captions-words.json", "cover.jpg", "final.mp4", "report.json", "sheet.png", "subtitles.srt"])
        self.assertEqual(r["cover"], b"jpegdata")
        self.assertEqual(r["report"]["outputs"]["cover"], r["folder"] + "/cover.jpg")
        self.assertEqual(r["after_cleanup"]["outputs"]["cover"], r["folder"] + "/cover.jpg")

    def test_the_report_carries_what_the_upload_pack_needs(self):
        r = self.run_steps(keep_work=False)
        publish = r["after_cleanup"]["publish"]
        self.assertEqual(publish["youtube_title"], "How your fridge really works")
        self.assertEqual(publish["pinned_comment"], "Did you know? Yes or no 👇")
        self.assertEqual(publish["hook"]["line1"], "Your fridge is")
        self.assertEqual(publish["runtime_seconds"], 61.5)

    def test_no_cover_no_cover_file(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            ctx, mpt = self.make_ctx(tmp, False)  # ctx.cover stays None
            with mock.patch.object(mv, "REVIEW_ROOT", tmp / "review"), mock.patch.object(mv, "MPT_DIR", tmp / "mpt"), contextlib.redirect_stdout(io.StringIO()):
                folder = mv.step_output(ctx, ctx.work / "final-visuals.mp4", ctx.work / "sheet.png", ["credit"], mpt)
            self.assertFalse((folder / "cover.jpg").exists())
            self.assertNotIn("cover", json.loads((folder / "report.json").read_text(encoding="utf-8"))["outputs"])


class TopicStepTests(unittest.TestCase):
    """The topic check in step_own_footage."""

    KEY = OwnFootageStepTests.KEY
    make_ctx, fake_result = OwnFootageStepTests.make_ctx, OwnFootageStepTests.fake_result

    def with_topic(self, **over):
        result = self.fake_result()
        result["report"]["topic"] = {"noun": "refrigerator", "noun_is_default": False, "clip_id": 5, "searched_phrase": "refrigerator",
                                     "found_by_topic_search": False, "first_tags": ["refrigerator", "kitchen"], "lead_tag_words": [], "ok": True, **over}
        return result

    def run_with(self, ctx, result):
        with mock.patch.object(mv, "find_tool", side_effect=lambda name: f"/bin/{name}"), \
                mock.patch.object(mv.footage, "load_pixabay_key", return_value=self.KEY), \
                mock.patch.object(mv.footage, "build_broll", return_value=result), contextlib.redirect_stdout(io.StringIO()):
            return mv.step_own_footage(ctx, [{"index": 0, "start": 0.0, "end": 4.0}], 4.0)

    def test_the_topic_check_is_in_the_report_checks(self):
        ctx = self.make_ctx()
        self.run_with(ctx, self.with_topic())
        check = next(c for c in ctx.checks if c["name"] == "topic on screen at 0 s")
        self.assertTrue(check["ok"])
        self.assertIn("pixabay 5", check["detail"])
        self.assertIn("refrigerator, kitchen", check["detail"])
        self.assertEqual(ctx.report["footage"]["topic"]["noun"], "refrigerator")

    def test_a_noun_found_by_a_direct_search_and_a_default_noun_are_both_said(self):
        ctx = self.make_ctx()
        self.run_with(ctx, self.with_topic(found_by_topic_search=True, noun_is_default=True))
        detail = next(c for c in ctx.checks if c["name"] == "topic on screen at 0 s")["detail"]
        self.assertIn("searched directly", detail)
        self.assertIn("topic_noun", detail)

    def test_a_failed_topic_check_stops_the_run(self):
        ctx = self.make_ctx()
        with self.assertRaises(mv.GateError) as raised:
            self.run_with(ctx, self.with_topic(ok=False))
        self.assertIn("topic on screen at 0 s failed", str(raised.exception))

    def test_a_footage_report_without_a_topic_adds_no_check(self):
        ctx = self.make_ctx()
        self.run_with(ctx, self.fake_result())
        self.assertFalse(any(c["name"] == "topic on screen at 0 s" for c in ctx.checks))


class StepOrderWithHookTests(unittest.TestCase):
    def test_the_hook_is_timed_right_after_the_length_gate_and_before_the_stage_stops(self):
        events = []
        with tempfile.TemporaryDirectory() as raw:
            script_path = Path(raw) / "script.json"
            script_path.write_text(json.dumps(hook_script()), encoding="utf-8")

            def rec(name, result=None):
                def fn(*a, **k):
                    events.append(name)
                    return result
                return fn

            take = {"x": 1}
            with mock.patch.object(mv, "WORK_ROOT", Path(raw) / "work"), mock.patch.object(mv, "step_preflight", side_effect=rec("preflight", {})), \
                    mock.patch.object(mv, "step_voice", side_effect=rec("voice", take)), \
                    mock.patch.object(mv, "step_join", side_effect=rec("join", (Path("/n.wav"), [{"index": 0, "start": 0, "end": 3}], 60.0))), \
                    mock.patch.object(mv, "step_length", side_effect=rec("length")), mock.patch.object(mv, "step_hook", side_effect=rec("hook")), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = mv.main([str(script_path), "--stage", "voice"])
        self.assertEqual(code, 0)
        self.assertEqual(events, ["preflight", "voice", "join", "length", "hook"])


if __name__ == "__main__":
    unittest.main()
