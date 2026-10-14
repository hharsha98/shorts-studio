"""Tests for studio/captions.py: aligning the SCRIPT's words with Whisper's word timing, and phrase grouping.

Pure functions only (no MoneyPrinterTurbo, no Remotion, no ffmpeg).

Run from /Users/harsha/shorts-studio:
    python3 -m unittest discover -s studio/tests -t .
"""

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import captions as cp  # noqa: E402


def cues(*items):
    """Whisper-style cues from (text, start, end) tuples."""
    return [{"index": k + 1, "text": t, "start": s, "end": e} for k, (t, s, e) in enumerate(items)]


def chain(*words, start=0.0, step=0.4):
    """Back-to-back cues, each `step` seconds long (like MoneyPrinterTurbo's word cues)."""
    return cues(*[(w, start + k * step, start + (k + 1) * step) for k, w in enumerate(words)])


def by_text(words):
    return {w["text"]: w for w in words}


class NormalizeTests(unittest.TestCase):
    def test_lowercase_nfc_punctuation_and_dashes(self):
        self.assertEqual(cp.normalize_words("Kühl-Schlangen, 1930s! „Zitat“"), ["kühl", "schlangen", "1930s", "zitat"])
        self.assertEqual(cp.normalize_words("Kühl"), ["kühl"])  # decomposed umlaut equals the composed one
        self.assertEqual(cp.normalize_words("— … &"), [])
        self.assertEqual(cp.normalize_words(""), [])
        self.assertEqual(cp.normalize_words(None), [])

    def test_same_function_as_the_word_error_rate(self):
        import make_video

        self.assertIs(make_video.normalize_words, cp.normalize_words)


class ScriptUnitsTests(unittest.TestCase):
    def test_pieces_are_kept_as_written(self):
        self.assertEqual(cp.script_units(["Flip, Kühlschlangen,", "Ende."]), ["Flip,", "Kühlschlangen,", "Ende."])

    def test_symbol_only_piece_joins_the_word_before(self):
        self.assertEqual(cp.script_units(["Tom & Jerry — fun"]), ["Tom &", "Jerry —", "fun"])

    def test_symbol_only_piece_at_the_start_joins_the_next_word(self):
        self.assertEqual(cp.script_units(["— Ja", "ok"]), ["— Ja", "ok"])

    def test_symbol_only_piece_at_a_line_start_joins_the_last_word_of_the_line_before(self):
        self.assertEqual(cp.script_units(["Eins", "– zwei"]), ["Eins –", "zwei"])

    def test_nothing_but_symbols_gives_no_words(self):
        self.assertEqual(cp.script_units(["— … &"]), [])
        self.assertEqual(cp.script_units([]), [])
        self.assertEqual(cp.script_units(["", "   "]), [])

    def test_extra_spaces_and_newlines_are_ignored(self):
        self.assertEqual(cp.script_units(["  a   b\n c "]), ["a", "b", "c"])

    def test_units_split_back_into_the_script_pieces(self):
        lines = ["Tom & Jerry — fun", "— Ja nein, ok!"]
        self.assertEqual(" ".join(cp.script_units(lines)).split(), " ".join(lines).split())


class MatchScriptTests(unittest.TestCase):
    def test_exact_match(self):
        ok, detail = cp.captions_match_script(["Flip,", "Kühlschlangen,"], ["Flip, Kühlschlangen,"])
        self.assertTrue(ok)
        self.assertIn("2 caption words", detail)

    def test_a_different_spelling_fails_and_names_the_word(self):
        ok, detail = cp.captions_match_script(["Rift", "ein"], ["Trifft ein"])
        self.assertFalse(ok)
        self.assertIn("'Rift'", detail)
        self.assertIn("'Trifft'", detail)

    def test_case_and_punctuation_count(self):
        self.assertFalse(cp.captions_match_script(["trifft"], ["Trifft"])[0])
        self.assertFalse(cp.captions_match_script(["Trifft"], ["Trifft,"])[0])

    def test_missing_and_extra_words_fail(self):
        self.assertFalse(cp.captions_match_script(["a"], ["a b"])[0])
        self.assertFalse(cp.captions_match_script(["a", "b", "c"], ["a b"])[0])
        self.assertIn("2 words but the script has 3", cp.captions_match_script(["a", "b"], ["a b c"])[1])

    def test_lines_are_joined(self):
        self.assertTrue(cp.captions_match_script(["a", "b", "c"], ["a b", "c"])[0])


class AlignEqualTests(unittest.TestCase):
    def test_equal_words_copy_whisper_timing(self):
        out = cp.align_words(cues(("Hello", 0.0, 0.4), ("big", 0.4, 0.7), ("world.", 0.7, 1.2)), ["Hello big world."])
        self.assertEqual([w["text"] for w in out], ["Hello", "big", "world."])
        self.assertEqual([(w["start"], w["end"]) for w in out], [(0.0, 0.4), (0.4, 0.7), (0.7, 1.2)])
        self.assertEqual({w["timing"] for w in out}, {cp.TIMING_HEARD})

    def test_text_is_the_script_as_written_with_punctuation(self):
        out = cp.align_words(chain("flip", "kuhlschlangen", "ende", step=0.5), ["Flip, Kühlschlangen, Ende."])
        # "kuhlschlangen" (no umlaut) is a different word for Whisper, but still ONE word at the same place
        self.assertEqual([w["text"] for w in out], ["Flip,", "Kühlschlangen,", "Ende."])

    def test_case_and_punctuation_of_whisper_do_not_matter(self):
        out = cp.align_words(cues(("KÜHLSCHLANGEN", 0, 1), ("ende!!", 1, 2)), ["Kühlschlangen, Ende."])
        self.assertEqual([w["timing"] for w in out], [cp.TIMING_HEARD, cp.TIMING_HEARD])
        self.assertEqual([(w["start"], w["end"]) for w in out], [(0, 1), (1, 2)])

    def test_lines_are_one_continuous_word_list(self):
        out = cp.align_words(chain("one", "two", "three"), ["One two", "three"])
        self.assertEqual([w["text"] for w in out], ["One", "two", "three"])

    def test_gaps_between_words_stay(self):
        out = cp.align_words(cues(("a", 0.0, 0.3), ("b", 1.0, 1.4)), ["a b"])
        self.assertEqual([(w["start"], w["end"]) for w in out], [(0.0, 0.3), (1.0, 1.4)])

    def test_end_limit_defaults_to_the_last_cue(self):
        out = cp.align_words(chain("a", "b"), ["a b"])
        self.assertEqual(out[-1]["end"], 0.8)


class AlignReplaceTests(unittest.TestCase):
    def test_german_misheard_word_keeps_the_script_spelling_and_whisper_timing(self):
        script = ["Trifft ein Wellenberg auf ein Wellental"]
        heard = cues(("rift", 13.42, 13.68), ("ein", 13.68, 13.84), ("Wellenberg", 13.84, 14.5), ("auf", 14.5, 14.7), ("ein", 14.7, 14.9), ("Wellental", 14.9, 15.6))
        out = cp.align_words(heard, script)
        self.assertEqual(out[0]["text"], "Trifft")
        self.assertEqual((out[0]["start"], out[0]["end"]), (13.42, 13.68))
        self.assertEqual(out[0]["timing"], cp.TIMING_HEARD)  # its own Whisper timestamps
        self.assertEqual([w["text"] for w in out], script[0].split())

    def test_several_misheard_words_in_a_row_get_their_own_times(self):
        out = cp.align_words(chain("der", "druck", "zwingt", "ein", "gas", step=0.5), ["Der Druck zwängt einen Gas"])
        self.assertEqual([w["text"] for w in out], ["Der", "Druck", "zwängt", "einen", "Gas"])
        self.assertEqual([(w["start"], w["end"]) for w in out], [(0, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 2.5)])
        self.assertEqual({w["timing"] for w in out}, {cp.TIMING_HEARD})

    def test_digits_heard_as_number_words(self):
        heard = cues(("Das", 0, 0.3), ("war", 0.3, 0.6), ("in", 0.6, 0.8), ("den", 0.8, 1.0), ("nineteen", 1.0, 1.6), ("thirties", 1.6, 2.2), ("so", 2.2, 2.5))
        out = cp.align_words(heard, ["Das war in den 1930s so"])
        self.assertEqual([w["text"] for w in out], ["Das", "war", "in", "den", "1930s", "so"])
        digits = out[4]
        self.assertEqual((digits["start"], digits["end"]), (1.0, 2.2))  # the whole span of both heard words
        self.assertEqual(digits["timing"], cp.TIMING_HEARD)  # one word taking a block of time is not a guess

    def test_german_number_word_heard_as_digits_and_split(self):
        heard = cues(("in", 58.8, 59.0), ("den", 59.0, 59.2), ("30er", 59.28, 59.6), ("Jahren", 59.6, 59.92), ("patentiert", 59.92, 60.6))
        out = cp.align_words(heard, ["in den Dreißigerjahren patentiert"])
        self.assertEqual([w["text"] for w in out], ["in", "den", "Dreißigerjahren", "patentiert"])
        self.assertEqual((out[2]["start"], out[2]["end"]), (59.28, 59.92))

    def test_compound_split_in_the_script_is_spread_by_length(self):
        # script "non stop" (two words), Whisper heard "nonstop" (one word)
        heard = cues(("nonstop", 1.0, 1.7), ("music", 1.7, 2.2))
        out = cp.align_words(heard, ["non stop music"])
        self.assertEqual([w["text"] for w in out], ["non", "stop", "music"])
        self.assertEqual(out[0]["start"], 1.0)
        self.assertEqual(out[1]["end"], 1.7)
        self.assertEqual(out[0]["end"], out[1]["start"])
        self.assertAlmostEqual(out[0]["end"], 1.3, places=2)  # 3 of 7 letters of the 0.7 s
        self.assertEqual([w["timing"] for w in out[:2]], [cp.TIMING_SPREAD, cp.TIMING_SPREAD])
        self.assertEqual(out[2]["timing"], cp.TIMING_HEARD)

    def test_compound_joined_in_the_script_heard_as_two_words(self):
        heard = cues(("non", 1.0, 1.3), ("stop", 1.3, 1.7), ("music", 1.7, 2.2))
        out = cp.align_words(heard, ["nonstop music"])
        self.assertEqual([w["text"] for w in out], ["nonstop", "music"])
        self.assertEqual((out[0]["start"], out[0]["end"]), (1.0, 1.7))
        self.assertEqual(out[0]["timing"], cp.TIMING_HEARD)

    def test_hyphenated_compound_is_one_caption_with_the_span_of_its_parts(self):
        heard = cues(("Kühl", 0.0, 0.4), ("schlangen", 0.4, 1.0), ("sind", 1.0, 1.3))
        out = cp.align_words(heard, ["Kühl-Schlangen sind"])
        self.assertEqual([w["text"] for w in out], ["Kühl-Schlangen", "sind"])
        self.assertEqual((out[0]["start"], out[0]["end"]), (0.0, 1.0))

    def test_hyphenated_compound_heard_as_one_word(self):
        out = cp.align_words(cues(("Noise-cancelling", 0.0, 0.9), ("headphones", 0.9, 1.6)), ["Noise cancelling headphones"])
        self.assertEqual([w["text"] for w in out], ["Noise", "cancelling", "headphones"])
        self.assertEqual(out[0]["start"], 0.0)
        self.assertEqual(out[1]["end"], 0.9)
        self.assertLess(out[0]["end"], out[1]["end"])

    def test_more_script_words_than_heard_words_share_the_span(self):
        heard = cues(("start", 0.0, 0.5), ("blahblahblahblah", 0.5, 1.5), ("end", 1.5, 2.0))
        out = cp.align_words(heard, ["start one two three four end"])
        middle = out[1:5]
        self.assertEqual(middle[0]["start"], 0.5)
        self.assertEqual(middle[-1]["end"], 1.5)
        self.assertEqual({w["timing"] for w in middle}, {cp.TIMING_SPREAD})
        self.assertGreater(middle[2]["end"] - middle[2]["start"], middle[1]["end"] - middle[1]["start"])  # "three" is longer than "two"

    def test_fewer_script_words_than_heard_words(self):
        heard = cues(("start", 0, 1), ("a", 1, 1.2), ("b", 1.2, 1.5), ("c", 1.5, 2), ("end", 2, 3))
        out = cp.align_words(heard, ["start xyz end"])
        self.assertEqual([w["text"] for w in out], ["start", "xyz", "end"])
        self.assertEqual((out[1]["start"], out[1]["end"]), (1, 2))


class AlignInsertDeleteTests(unittest.TestCase):
    def test_missing_word_is_placed_inside_the_gap_between_its_neighbours(self):
        heard = cues(("Wir", 0.0, 0.3), ("lernen", 0.3, 0.9), ("der", 1.3, 1.5), ("Uni", 1.5, 2.0))
        out = cp.align_words(heard, ["Wir lernen an der Uni"])
        an = by_text(out)["an"]
        self.assertEqual(an["timing"], cp.TIMING_INTERPOLATED)
        self.assertGreaterEqual(an["start"], 0.9)
        self.assertLessEqual(an["end"], 1.3)
        self.assertEqual(out[1]["end"], 0.9)  # the neighbours keep their time: the gap was big enough
        self.assertEqual(out[3]["start"], 1.3)

    def test_missing_word_without_a_gap_borrows_from_both_neighbours(self):
        heard = chain("Wir", "lernen", "der", "Uni", step=0.5)
        out = cp.align_words(heard, ["Wir lernen an der Uni"])
        an = by_text(out)["an"]
        self.assertGreaterEqual(an["end"] - an["start"], cp.MIN_WORD_SECONDS)
        self.assertEqual(an["timing"], cp.TIMING_INTERPOLATED)
        self.assertEqual(cp.caption_problems(out, 2.0), [])
        self.assertLess(out[1]["end"], 1.0)  # "lernen" gave something up ...
        self.assertGreater(out[3]["start"], 1.0)  # ... and so did "der"
        self.assertEqual(out[0]["start"], 0.0)
        self.assertEqual(out[-1]["end"], 2.0)

    def test_a_long_pause_is_not_filled_completely(self):
        heard = cues(("Hallo", 0.0, 0.5), ("Welt", 3.5, 4.0))
        out = cp.align_words(heard, ["Hallo du Welt"])
        du = by_text(out)["du"]
        self.assertLess(du["end"] - du["start"], 1.0)  # a short word, not the whole 3 s pause
        self.assertGreater(du["start"], 0.5)
        self.assertLess(du["end"], 3.5)

    def test_several_missing_words_in_a_row_split_the_gap_by_length(self):
        heard = cues(("Anfang", 0.0, 0.6), ("Ende", 2.6, 3.0))
        out = cp.align_words(heard, ["Anfang ab kurz extralanges Ende"])
        run = out[1:4]
        self.assertEqual({w["timing"] for w in run}, {cp.TIMING_INTERPOLATED})
        self.assertEqual(cp.caption_problems(out, 3.0), [])
        durations = [w["end"] - w["start"] for w in run]
        self.assertGreater(durations[2], durations[0])  # the long word gets more time than "ab"

    def test_missing_word_at_the_start_and_at_the_end(self):
        heard = cues(("middle", 2.0, 2.6))
        out = cp.align_words(heard, ["first middle last"], end_limit=5.0)
        self.assertEqual([w["text"] for w in out], ["first", "middle", "last"])
        self.assertLessEqual(out[0]["end"], 2.0)
        self.assertGreaterEqual(out[2]["start"], 2.6)
        self.assertLessEqual(out[2]["end"], 5.0)
        self.assertEqual(cp.caption_problems(out, 5.0), [])

    def test_extra_whisper_word_is_dropped_and_its_time_goes_to_the_neighbours(self):
        heard = cues(("alpha", 0.0, 1.0), ("UMM", 1.0, 1.4), ("beta", 1.4, 2.4))
        out = cp.align_words(heard, ["alpha beta"])
        self.assertEqual([w["text"] for w in out], ["alpha", "beta"])
        self.assertAlmostEqual(out[0]["end"], 1.2)
        self.assertAlmostEqual(out[1]["start"], 1.2)
        self.assertEqual(out[0]["start"], 0.0)
        self.assertEqual(out[1]["end"], 2.4)

    def test_extra_whisper_word_at_the_start_goes_to_the_first_word(self):
        out = cp.align_words(cues(("umm", 0.0, 0.5), ("alpha", 0.5, 1.0)), ["alpha"])
        self.assertEqual([(w["text"], w["start"], w["end"]) for w in out], [("alpha", 0.0, 1.0)])

    def test_extra_whisper_word_at_the_end_goes_to_the_last_word(self):
        out = cp.align_words(cues(("alpha", 0.0, 0.5), ("thanks", 0.5, 1.0)), ["alpha"])
        self.assertEqual([(w["text"], w["start"], w["end"]) for w in out], [("alpha", 0.0, 1.0)])

    def test_the_dropped_word_never_reaches_the_output(self):
        out = cp.align_words(chain("a", "hallucinated", "words", "b"), ["a b"])
        self.assertEqual([w["text"] for w in out], ["a", "b"])


class AlignEdgeCaseTests(unittest.TestCase):
    def test_empty_script_gives_no_captions(self):
        self.assertEqual(cp.align_words(chain("a", "b"), []), [])
        self.assertEqual(cp.align_words(chain("a", "b"), [""]), [])
        self.assertEqual(cp.align_words([], []), [])
        self.assertEqual(cp.align_words(chain("a"), ["— …"]), [])

    def test_no_whisper_words_spreads_the_script_over_the_narration(self):
        out = cp.align_words([], ["one two three four"], end_limit=8.0)
        self.assertEqual(len(out), 4)
        self.assertEqual(out[0]["start"], 0.0)
        self.assertEqual(out[-1]["end"], 8.0)
        self.assertEqual({w["timing"] for w in out}, {cp.TIMING_INTERPOLATED})
        self.assertEqual(cp.caption_problems(out, 8.0), [])

    def test_no_whisper_words_and_no_narration_length_is_an_error(self):
        with self.assertRaises(cp.CaptionError):
            cp.align_words([], ["one two"])

    def test_punctuation_only_whisper_cues_are_ignored(self):
        heard = cues(("...", 0.0, 0.2), ("hello", 0.2, 0.8), ("-", 0.8, 0.9), ("world", 0.9, 1.5))
        out = cp.align_words(heard, ["hello world"])
        self.assertEqual([(w["start"], w["end"]) for w in out], [(0.2, 0.8), (0.9, 1.5)])

    def test_single_word(self):
        out = cp.align_words(cues(("Hallo", 0.5, 1.0)), ["Hallo!"])
        self.assertEqual([(w["text"], w["start"], w["end"]) for w in out], [("Hallo!", 0.5, 1.0)])

    def test_everything_misheard_still_gets_timing(self):
        out = cp.align_words(chain("xx", "yy", "zz"), ["aa bb cc"])
        self.assertEqual([w["text"] for w in out], ["aa", "bb", "cc"])
        self.assertEqual(cp.caption_problems(out, 1.2), [])

    def test_zero_length_whisper_word_gets_the_minimum_time(self):
        heard = cues(("one", 0.0, 0.5), ("two", 0.5, 0.5), ("three", 0.5, 1.0))
        out = cp.align_words(heard, ["one two three"])
        self.assertGreaterEqual(out[1]["end"] - out[1]["start"], cp.MIN_WORD_SECONDS - 1e-9)
        self.assertEqual(cp.caption_problems(out, 1.0), [])

    def test_overlapping_whisper_words_are_pulled_apart(self):
        heard = cues(("one", 0.0, 0.6), ("two", 0.4, 1.0), ("three", 0.9, 1.5))
        out = cp.align_words(heard, ["one two three"])
        self.assertEqual(cp.caption_problems(out, 1.5), [])
        self.assertEqual([w["text"] for w in out], ["one", "two", "three"])

    def test_words_with_identical_start_get_strictly_increasing_starts(self):
        heard = cues(("a", 1.0, 1.0), ("b", 1.0, 1.0), ("c", 1.0, 1.0))
        out = cp.align_words(heard, ["a b c"], end_limit=3.0)
        starts = [w["start"] for w in out]
        self.assertEqual(starts, sorted(set(starts)))
        self.assertEqual(cp.caption_problems(out, 3.0), [])

    def test_whisper_time_past_the_narration_end_is_clamped(self):
        out = cp.align_words(cues(("one", 0.0, 0.5), ("two", 0.5, 2.0)), ["one two"], end_limit=1.2)
        self.assertEqual(out[-1]["end"], 1.2)
        self.assertEqual(cp.caption_problems(out, 1.2), [])

    def test_the_last_word_is_not_squeezed_out_at_the_end(self):
        heard = cues(("a", 0.0, 0.5), ("b", 0.5, 1.0), ("c", 1.0, 1.0), ("d", 1.0, 1.0))  # the last two have no time at all
        out = cp.align_words(heard, ["a b c d"], end_limit=1.0)
        self.assertEqual(cp.caption_problems(out, 1.0), [])
        self.assertTrue(all(w["end"] - w["start"] >= cp.MIN_WORD_SECONDS - 1e-9 for w in out))

    def test_more_words_than_the_narration_can_hold_is_an_error(self):
        with self.assertRaises(cp.CaptionError):
            cp.align_words(chain("a", "b", "c", "d", "e", "f", step=0.05), ["a b c d e f"], end_limit=0.3)

    def test_first_word_may_start_after_zero(self):
        out = cp.align_words(cues(("hi", 1.5, 2.0)), ["hi"], end_limit=3.0)
        self.assertEqual(out[0]["start"], 1.5)

    def test_cue_text_with_several_words_shares_its_time(self):
        out = cp.align_words(cues(("hello world", 0.0, 1.0), ("again", 1.0, 1.5)), ["hello world again"])
        self.assertEqual([w["text"] for w in out], ["hello", "world", "again"])
        self.assertEqual(out[0]["start"], 0.0)
        self.assertEqual(out[1]["end"], 1.0)
        self.assertEqual(cp.caption_problems(out, 1.5), [])

    def test_symbol_only_script_piece_rides_with_its_word(self):
        out = cp.align_words(chain("Tom", "Jerry", "fun"), ["Tom & Jerry — fun"])
        self.assertEqual([w["text"] for w in out], ["Tom &", "Jerry —", "fun"])
        self.assertEqual(out[0]["timing"], cp.TIMING_HEARD)

    def test_cues_may_come_with_or_without_an_index(self):
        out = cp.align_words([{"text": "a", "start": 0, "end": 1}, {"text": "b", "start": 1, "end": 2}], ["a b"])
        self.assertEqual(len(out), 2)

    def test_output_is_plain_data(self):
        out = cp.align_words(chain("a", "b"), ["a b"])
        for w in out:
            self.assertEqual(set(w), {"text", "start", "end", "timing"})
            self.assertIsInstance(w["start"], float)
            self.assertEqual(round(w["start"], 3), w["start"])  # whole milliseconds

    def test_input_cues_are_not_changed(self):
        heard = chain("rift", "ein")
        before = [dict(c) for c in heard]
        cp.align_words(heard, ["Trifft ein"])
        self.assertEqual(heard, before)


class AlignInvariantsTests(unittest.TestCase):
    """Whatever Whisper does, the captions have exactly the script's words and obey every timing rule."""

    VOCAB = ["Kühlschrank", "der", "die", "und", "Geräuschunterdrückung", "a", "ab", "Trifft", "Welle", "Mikrofon", "zwängt", "ein", "an", "Gas", "1930s", "non-stop", "Kühl-Schlangen"]

    def make_case(self, seed):
        rng = random.Random(seed)
        n = rng.randint(1, 40)
        script_words = [rng.choice(self.VOCAB) + rng.choice(["", "", ",", "."]) for _ in range(n)]
        # Whisper: copy the script, then drop / replace / insert / split words at random
        heard_words = []
        for w in script_words:
            roll = rng.random()
            if roll < 0.08:
                continue  # missing
            if roll < 0.20:
                heard_words.append(rng.choice(["rift", "zwingt", "xx", "nineteen thirties"]))
            elif roll < 0.26:
                heard_words.append(w)
                heard_words.append(rng.choice(["umm", "thanks"]))  # extra
            elif roll < 0.30 and len(w) > 4:
                heard_words += [w[: len(w) // 2], w[len(w) // 2:]]  # split
            else:
                heard_words.append(w)
        t = rng.uniform(0, 1)
        heard = []
        for w in heard_words:
            dur = rng.choice([0.0, 0.05, 0.2, 0.3, 0.5])
            gap = rng.choice([0.0, 0.0, 0.1, 0.8])
            heard.append({"text": w, "start": round(t, 3), "end": round(t + dur, 3)})
            t += dur + gap
        end_limit = max(t + rng.uniform(0, 1), n * 0.1 + 0.5)
        lines = []
        rest = list(script_words)
        while rest:
            k = rng.randint(1, 7)
            lines.append(" ".join(rest[:k]))
            rest = rest[k:]
        return heard, lines, script_words, end_limit

    def test_random_cases_obey_every_rule(self):
        for seed in range(400):
            heard, lines, script_words, end_limit = self.make_case(seed)
            with self.subTest(seed=seed):
                out = cp.align_words(heard, lines, end_limit=end_limit)
                self.assertEqual([w["text"] for w in out], script_words)  # exactly one cue per script word, as written, in order
                self.assertEqual(cp.caption_problems(out, end_limit), [])
                for a, b in zip(out, out[1:]):
                    self.assertLess(a["start"], b["start"])
                    self.assertLessEqual(a["end"], b["start"] + 1e-9)
                for w in out:
                    self.assertGreaterEqual(w["start"], 0.0)
                    self.assertLessEqual(w["end"], end_limit + 1e-9)
                    self.assertGreaterEqual(w["end"] - w["start"], cp.MIN_WORD_SECONDS - 1e-9)
                stats = cp.alignment_stats(out)
                self.assertEqual(stats["heard"] + stats["spread"] + stats["interpolated"], len(script_words))
                self.assertTrue(cp.captions_match_script([w["text"] for w in out], lines)[0])

    def test_a_perfect_transcript_has_nothing_guessed(self):
        words = ["Ein", "Chip", "erzeugt", "daraus", "ein", "exaktes", "Spiegelbild,"]
        out = cp.align_words(chain(*words), [" ".join(words)])
        stats = cp.alignment_stats(out)
        self.assertEqual((stats["heard"], stats["guessed"]), (7, 0))
        self.assertIsNone(cp.guessed_warning(stats))


class CaptionProblemsTests(unittest.TestCase):
    def word(self, text, start, end):
        return {"text": text, "start": start, "end": end}

    def test_valid_cues(self):
        self.assertEqual(cp.caption_problems([self.word("a", 0, 0.5), self.word("b", 0.5, 1.0)], 1.0), [])
        self.assertEqual(cp.caption_problems([], 1.0), [])

    def test_too_short(self):
        problems = cp.caption_problems([self.word("a", 0, 0.05)], 1.0)
        self.assertTrue(any("only 0.050 s long" in p for p in problems))

    def test_minimum_is_inclusive(self):
        self.assertEqual(cp.caption_problems([self.word("a", 0, cp.MIN_WORD_SECONDS)], 1.0), [])

    def test_overlap(self):
        problems = cp.caption_problems([self.word("a", 0, 0.6), self.word("b", 0.5, 1.0)], 1.0)
        self.assertTrue(any("overlap" in p for p in problems))

    def test_not_increasing(self):
        problems = cp.caption_problems([self.word("a", 0.5, 0.9), self.word("b", 0.5, 1.0)], 1.0)
        self.assertTrue(any("not after the previous word" in p for p in problems))

    def test_before_start_and_after_end(self):
        self.assertTrue(any("before the narration" in p for p in cp.caption_problems([self.word("a", -0.2, 0.5)], 1.0)))
        self.assertTrue(any("after the narration ends" in p for p in cp.caption_problems([self.word("a", 0.5, 1.5)], 1.0)))

    def test_problem_names_the_word(self):
        self.assertTrue(any("'zwängt'" in p for p in cp.caption_problems([self.word("zwängt", 0, 0.01)], 1.0)))


class StatsTests(unittest.TestCase):
    def words(self, heard, spread, interpolated):
        return ([{"timing": cp.TIMING_HEARD}] * heard + [{"timing": cp.TIMING_SPREAD}] * spread
                + [{"timing": cp.TIMING_INTERPOLATED}] * interpolated)

    def test_counts(self):
        stats = cp.alignment_stats(self.words(90, 6, 4))
        self.assertEqual(stats, {"words": 100, "heard": 90, "spread": 6, "interpolated": 4, "guessed": 10, "guessed_share": 0.1})

    def test_empty(self):
        stats = cp.alignment_stats([])
        self.assertEqual((stats["words"], stats["guessed_share"]), (0, 0.0))
        self.assertIsNone(cp.guessed_warning(stats))

    def test_warning_only_above_ten_percent(self):
        self.assertIsNone(cp.guessed_warning(cp.alignment_stats(self.words(90, 6, 4))))  # exactly 10 %
        warning = cp.guessed_warning(cp.alignment_stats(self.words(89, 6, 5)))  # 11 %
        self.assertIn("11 of 100", warning)
        self.assertIn("6 spread", warning)
        self.assertIn("5 interpolated", warning)


def timed(*items):
    """Per-word cues from (text, start, end)."""
    return [{"text": t, "start": s, "end": e, "timing": cp.TIMING_HEARD} for t, s, e in items]


class PhraseTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(cp.group_phrases([]), [])

    def test_splits_after_sentence_endings(self):
        words = timed(("Hello", 0.0, 0.3), ("world.", 0.3, 0.7), ("Next", 0.7, 1.0), ("one!", 1.0, 1.4), ("Really?", 1.4, 1.9), ("Yes…", 1.9, 2.4), ("ok", 2.4, 2.7))
        self.assertEqual([p["text"] for p in cp.group_phrases(words)], ["Hello world.", "Next one!", "Really?", "Yes…", "ok"])

    def test_sentence_ending_hidden_behind_a_closing_quote(self):
        words = timed(("Er", 0.0, 0.3), ("sagt:", 0.3, 0.6), ("„Nein.“", 0.6, 1.0), ("Dann", 1.0, 1.3), ("geht", 1.3, 1.6))
        self.assertEqual([p["text"] for p in cp.group_phrases(words)], ["Er sagt: „Nein.“", "Dann geht"])

    def test_splits_at_a_pause(self):
        words = timed(("one", 0.0, 0.3), ("two", 0.3, 0.6), ("three", 1.2, 1.5), ("four", 1.5, 1.8))
        self.assertEqual([p["text"] for p in cp.group_phrases(words)], ["one two", "three four"])

    def test_a_pause_just_under_the_limit_does_not_split(self):
        words = timed(("one", 0.0, 0.3), ("two", 0.3 + cp.PHRASE_PAUSE_SECONDS - 0.01, 1.0))
        self.assertEqual(len(cp.group_phrases(words)), 1)

    def test_a_pause_exactly_at_the_limit_splits(self):
        words = timed(("one", 0.0, 0.3), ("two", 0.3 + cp.PHRASE_PAUSE_SECONDS, 1.0))
        self.assertEqual(len(cp.group_phrases(words)), 2)

    def test_phrases_never_exceed_the_line_length(self):
        words = timed(*[(f"Wort{k}", k * 0.3, k * 0.3 + 0.3) for k in range(40)])
        phrases = cp.group_phrases(words)
        self.assertGreater(len(phrases), 3)
        for p in phrases:
            self.assertLessEqual(len(p["text"]), cp.PHRASE_MAX_CHARS)

    def test_max_chars_is_a_parameter(self):
        words = timed(("aaaa", 0.0, 0.3), ("bbbb", 0.3, 0.6), ("cccc", 0.6, 0.9))
        self.assertEqual([p["text"] for p in cp.group_phrases(words, max_chars=9)], ["aaaa bbbb", "cccc"])
        self.assertEqual([p["text"] for p in cp.group_phrases(words, max_chars=8)], ["aaaa", "bbbb", "cccc"])

    def test_a_word_longer_than_the_line_stands_alone(self):
        words = timed(("x" * 50, 0.0, 0.5), ("short", 0.5, 0.9))
        self.assertEqual([p["text"] for p in cp.group_phrases(words)], ["x" * 50, "short"])

    def test_a_comma_ends_a_phrase_once_it_is_long_enough(self):
        words = timed(("Spiegelbild,", 0.0, 0.5), ("eine", 0.5, 0.7), ("auf", 0.7, 0.9), ("den", 0.9, 1.1), ("Kopf", 1.1, 1.3), ("gestellte,", 1.3, 1.7), ("Welle", 1.7, 2.0))
        self.assertEqual([p["text"] for p in cp.group_phrases(words)], ["Spiegelbild, eine auf den Kopf gestellte,", "Welle"])

    def test_a_phrase_that_gets_too_long_is_cut_at_an_earlier_comma(self):
        # without the rule this would be "Spiegelbild, eine auf den Kopf gestellte" + "Welle." (one word alone)
        words = timed(("Spiegelbild,", 0.0, 0.5), ("eine", 0.5, 0.7), ("auf", 0.7, 0.9), ("den", 0.9, 1.1), ("Kopf", 1.1, 1.3), ("gestellte", 1.3, 1.7), ("Welle.", 1.7, 2.1))
        self.assertEqual([p["text"] for p in cp.group_phrases(words)], ["Spiegelbild,", "eine auf den Kopf gestellte Welle."])

    def test_no_comma_cut_when_the_rest_would_not_fit_either(self):
        words = timed(("Ab,", 0.0, 0.2), ("a" * 20, 0.2, 0.6), ("b" * 20, 0.6, 1.0))
        self.assertEqual([p["text"] for p in cp.group_phrases(words)], ["Ab, " + "a" * 20, "b" * 20])

    def test_no_comma_cut_when_the_part_before_it_would_be_tiny(self):
        words = timed(("Ja,", 0.0, 0.2), ("a" * 20, 0.2, 0.6), ("b" * 20, 0.6, 1.0))  # "Ja," is 3 characters
        self.assertEqual([p["text"] for p in cp.group_phrases(words)], ["Ja, " + "a" * 20, "b" * 20])

    def test_the_cut_never_breaks_the_rules_it_cut_for(self):
        words = timed(("Eins,", 0.0, 0.3), ("zwei", 0.3, 0.6), ("drei", 0.6, 0.9), ("vier", 0.9, 1.2), ("fünf", 1.2, 1.5), ("sechs", 1.5, 1.8), ("sieben", 1.8, 2.1), ("acht", 2.1, 2.4), ("neun.", 2.4, 2.7))
        phrases = cp.group_phrases(words)
        self.assertEqual(" ".join(p["text"] for p in phrases).split(), [w["text"] for w in words])
        for p in phrases:
            self.assertLessEqual(len(p["text"]), cp.PHRASE_MAX_CHARS)

    def test_a_comma_in_a_short_phrase_does_not_split(self):
        words = timed(("Ja,", 0.0, 0.3), ("gut", 0.3, 0.6), ("so", 0.6, 0.9))
        self.assertEqual([p["text"] for p in cp.group_phrases(words)], ["Ja, gut so"])

    def test_times_run_from_the_first_to_the_last_word(self):
        words = timed(("one", 0.0, 0.5), ("two", 0.5, 1.2), ("three.", 1.2, 2.5), ("four", 2.5, 3.6))
        phrases = cp.group_phrases(words)
        self.assertEqual([(p["start"], p["end"]) for p in phrases], [(0.0, 2.5), (2.5, 3.6)])

    def test_short_phrase_is_kept_longer_as_far_as_the_next_phrase_allows(self):
        words = timed(("Ja.", 0.0, 0.3), ("Dann", 0.6, 1.0), ("geht", 1.0, 1.4), ("es", 1.4, 3.0))
        phrases = cp.group_phrases(words)
        self.assertEqual(phrases[0]["text"], "Ja.")
        self.assertEqual(phrases[0]["end"], 0.6)  # wanted until 1.0, but the next phrase starts at 0.6
        words2 = timed(("Ja.", 0.0, 0.3), ("Dann", 2.0, 2.4))
        self.assertEqual(cp.group_phrases(words2)[0]["end"], 1.0)  # room enough: a full second

    def test_the_last_phrase_may_use_the_end_limit(self):
        words = timed(("Ja.", 0.0, 0.3))
        self.assertEqual(cp.group_phrases(words, end_limit=0.6)[0]["end"], 0.6)
        self.assertEqual(cp.group_phrases(words, end_limit=5.0)[0]["end"], 1.0)
        self.assertEqual(cp.group_phrases(words)[0]["end"], 1.0)

    def test_every_word_is_in_exactly_one_phrase_in_order(self):
        script = ["Ein Chip erzeugt daraus ein exaktes Spiegelbild, eine auf den Kopf gestellte Welle. Trifft ein Wellenberg des Lärms auf ein Wellental des Gegenschalls, löschen sie sich aus."]
        out = cp.align_words(chain(*script[0].split(), step=0.31), script)
        phrases = cp.group_phrases(out)
        self.assertEqual(" ".join(p["text"] for p in phrases).split(), script[0].split())

    def test_phrases_never_overlap_and_stay_in_order(self):
        rng = random.Random(7)
        t = 0.0
        words = []
        for k in range(80):
            dur = rng.choice([0.1, 0.2, 0.4])
            words.append({"text": rng.choice(["ab", "Wort.", "kurz,", "Geräuschunterdrückung", "x"]), "start": round(t, 3), "end": round(t + dur, 3)})
            t += dur + rng.choice([0.0, 0.0, 0.5])
        phrases = cp.group_phrases(words)
        for a, b in zip(phrases, phrases[1:]):
            self.assertLessEqual(a["end"], b["start"] + 1e-9)
            self.assertLess(a["start"], b["start"])
        for p in phrases:
            self.assertGreater(p["end"], p["start"])
            self.assertLessEqual(len(p["text"]), max(cp.PHRASE_MAX_CHARS, len("Geräuschunterdrückung")))

    def test_phrase_cues_are_valid_srt_cues(self):
        import make_video

        words = timed(("Hallo", 0.0, 0.5), ("Welt.", 0.5, 1.0), ("Nochmal", 1.4, 2.0))
        text = make_video.format_srt(cp.group_phrases(words))
        self.assertEqual(
            text,
            "1\n00:00:00,000 --> 00:00:01,000\nHallo Welt.\n\n2\n00:00:01,400 --> 00:00:02,400\nNochmal\n\n",
        )
        self.assertEqual(make_video.srt_problems(make_video.parse_srt(text)), [])


if __name__ == "__main__":
    unittest.main()
