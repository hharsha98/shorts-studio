"""Tests for studio/number_words.py and for how the VOICE checks in studio/make_video.py use it.

The scripts write numbers as words ("twenty thousand kilometers", "zweitausendzehn"); the transcriber writes digits and
symbols ("20,000", "2010", "40%", "0°", "DCF77"). Both sides of the voice comparison turn every run of number tokens into
one "<num>", so a correct voice is not rejected, while a real mishearing still is. The unit next to a number is NOT part
of the run: it stays a word in one standard spelling ("km" = "kilometers"), so a swapped or dropped unit still fails.
The captions never use this.

Pure functions only (no network, no audio).

Run from /Users/harsha/shorts-studio:
    python3 -m unittest discover -s studio/tests -t .
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import captions as cp  # noqa: E402
import make_video as mv  # noqa: E402
import number_words as nw  # noqa: E402

NUM = nw.NUM
NUM_TIMES = nw.NUM_TIMES


class SpokenWordsTests(unittest.TestCase):
    def assertWords(self, text, expected):
        self.assertEqual(nw.spoken_words(text), expected, text)

    def test_the_placeholder_is_num(self):
        self.assertEqual(NUM, "<num>")

    def test_plain_text_is_just_the_normalised_words(self):
        self.assertWords("Your fridge moves heat.", ["your", "fridge", "moves", "heat"])
        self.assertWords("", [])
        self.assertEqual(nw.spoken_words(None), [])

    def test_a_run_of_english_number_words_is_one_placeholder(self):
        self.assertWords("twenty thousand kilometers", [NUM, "kilometer"])  # the unit stays, in its standard spelling
        self.assertWords("twenty thousand miles", [NUM, "miles"])
        self.assertWords("thirty-eight millionths of a second", [NUM, "millionth", "of", "a", "second"])
        self.assertWords("three hundred meters", [NUM, "meter"])
        self.assertWords("in the nineteen thirties", ["in", "the", NUM])

    def test_digits_are_number_tokens_whatever_surrounds_them(self):
        self.assertWords("20,000 miles", [NUM, "miles"])
        self.assertWords("about 3.5 billion $", ["about", NUM, "dollar"])
        self.assertWords("€5 or 5€", [NUM, "euro", "or", NUM, "euro"])  # a leading symbol moves behind its number
        self.assertWords("$3.5 billion", [NUM, "dollar"])
        self.assertWords("€ 20 per month", [NUM, "euro", "per", "month"])
        self.assertWords("2010", [NUM])
        self.assertWords("10-20", [NUM])  # two numbers side by side are one run

    def test_symbols_percent_and_degrees(self):
        self.assertWords("40%", [NUM, "percent"])
        self.assertWords("about 40 %", ["about", NUM, "percent"])
        self.assertWords("vierzig Prozent", [NUM, "percent"])
        self.assertWords("forty percent", [NUM, "percent"])
        self.assertWords("0°", [NUM, "degree"])
        self.assertWords("null Grad", [NUM, "degree"])
        self.assertWords("zero degrees", [NUM, "degree"])
        self.assertWords("-5 °C", [NUM, "degree", "celsius"])
        self.assertWords("minus five degrees Celsius", [NUM, "degree", "celsius"])
        self.assertWords("20C", [NUM, "degree", "celsius"])
        self.assertWords("18º", [NUM, "degree"])

    def test_units_the_transcriber_abbreviates(self):
        for spoken, written, standard in (
                ("three hundred meters", "300 m", "meter"), ("dreihundert Meter", "300m", "meter"),
                ("zwanzig Kilometern", "20 km", "kilometer"), ("five kilometres", "5 km", "kilometer"),
                ("zwei Kilogramm", "2 kg", "kilogram"), ("ten seconds", "10 s", "second"),
                ("zwanzig Sekunden", "20 Sekunden", "second"), ("zwei Stunden", "2 h", "hour"), ("two hours", "2h", "hour"),
                ("fünf Zentimeter", "5 cm", "centimeter"), ("three Liter", "3 l", "liter"), ("ten minutes", "10 min", "minute"),
                ("fünf Euro", "5 €", "euro"), ("five dollars", "$5", "dollar"), ("zwölf Cent", "12 cents", "cent")):
            self.assertEqual(nw.spoken_words(spoken), nw.spoken_words(written), (spoken, written))
            self.assertEqual(nw.spoken_words(spoken), [NUM, standard], spoken)

    def test_different_units_stay_different_words(self):
        for one, other in (("meters", "kilometers"), ("seconds", "minutes"), ("Sekunden", "Stunden"), ("Euro", "Dollar"),
                           ("gram", "kilogram"), ("percent", "degrees"), ("milliseconds", "seconds"), ("Meter", "Zentimeter")):
            self.assertNotEqual(nw.spoken_words(f"about thirty {one}"), nw.spoken_words(f"about thirty {other}"), (one, other))
            self.assertNotEqual(nw.spoken_words(f"about 30 {one}"), nw.spoken_words(f"about thirty {other}"), (one, other))

    def test_a_unit_the_voice_leaves_out_is_a_missing_token(self):
        for with_unit in ("thirty seconds", "300 m", "vierzig Prozent", "zwanzig Euro", "null Grad", "eine Stunde"):
            self.assertEqual(len(nw.spoken_words(with_unit)), 2, with_unit)
            self.assertEqual(len(nw.spoken_words(with_unit.split()[0])), 1, with_unit)

    def test_the_noun_after_the_german_article_is_not_swallowed(self):
        self.assertWords("eine Stunde", [NUM, "hour"])
        self.assertWords("eine Sekunde", [NUM, "second"])
        self.assertWords("ein Liter", [NUM, "liter"])
        self.assertWords("eine Minute", [NUM, "minute"])
        self.assertNotEqual(nw.spoken_words("eine Stunde"), nw.spoken_words("eine Sekunde"))

    def test_a_letter_after_a_degrees_word_is_part_of_the_unit_only_there(self):
        self.assertWords("0 degrees c", [NUM, "degree", "celsius"])
        self.assertWords("0 degrees F", [NUM, "degree", "fahrenheit"])
        self.assertWords("0 Grad Celsius", [NUM, "degree", "celsius"])
        self.assertWords("a c major chord", ["a", "c", "major", "chord"])
        self.assertWords("five c", [NUM, "c"])  # a lone c is not a unit: only celsius / c / f right after degrees

    def test_connectors_belong_to_a_run_only_inside_it(self):
        self.assertWords("two and a half", [NUM])
        self.assertWords("one hundred and five", [NUM])
        self.assertWords("three point five", [NUM])
        self.assertWords("drei Komma fünf", [NUM])
        self.assertWords("zwei und zwanzig", [NUM])
        self.assertWords("a hundred meters", [NUM, "meter"])
        self.assertWords("cats and dogs", ["cats", "and", "dogs"])
        self.assertWords("Katzen und Hunde", ["katzen", "und", "hunde"])
        self.assertWords("twenty and a few", [NUM, "and", "a", "few"])  # "and a" must lead to a number
        self.assertWords("a dog and half a cat", ["a", "dog", "and", "half", "a", "cat"])  # "half" alone is a word
        self.assertWords("three half-lives", [NUM, "half", "lives"])

    def test_a_sign_belongs_to_the_number_after_it(self):
        self.assertWords("minus fünf", [NUM])
        self.assertWords("plus ten", [NUM])
        self.assertWords("negative five", [NUM])
        self.assertWords("minus the cost", ["minus", "the", "cost"])
        self.assertWords("plus one more", [NUM, "more"])  # "one" is a number word, as the module doc says

    def test_german_compound_number_words(self):
        for word in ("zweitausendzehn", "achtunddreißig", "zweieinhalb", "siebenundsiebzig", "zwanzigtausend", "dreihundert",
                     "einundzwanzig", "sechzehn", "siebzehn", "neunzehn", "zwölf", "elf", "null", "eins", "dreißig", "dreissig",
                     "hunderteins", "tausendeins", "zweitausend", "milliarden", "millionen", "einhalb", "halb"):
            self.assertWords(word, [NUM])

    def test_german_words_that_only_contain_a_number_morpheme_are_not_numbers(self):
        for word in ("einem", "einen", "einer", "eines", "Achtung", "Achtel", "Zeitung", "Vierecke", "Dreieck", "Sechsecke",
                     "Neuland", "Hunde", "Zehe", "Eisen", "Elfmeter"):
            self.assertEqual(nw.spoken_words(word), [word.lower()], word)

    def test_a_lone_und_is_not_a_number(self):
        self.assertFalse(nw.is_number_word("und"))
        self.assertFalse(nw.is_number_word("undund"))
        self.assertWords("Brot und Butter", ["brot", "und", "butter"])
        self.assertWords("eins und zwei", [NUM])  # but between numbers it is part of the run

    def test_choices_for_the_ambiguous_words(self):
        self.assertWords("Zehntel", [NUM])  # a fraction word that is not behind a number is a number
        self.assertWords("ein Zehntel Grad", [NUM, "tenth", "degree"])  # behind a number it is a token of its own, the unit follows
        self.assertWords("Acht geben", [NUM, "geben"])  # acht is a number even here (documented: both sides are the same)
        self.assertWords("ein Hund", [NUM, "hund"])  # the article is the number one: it is compared as <num> on both sides
        self.assertWords("eine Katze", [NUM, "katze"])
        self.assertWords("einem Hund", ["einem", "hund"])  # but einem / einen / einer are not

    def test_german_decades_and_times(self):
        self.assertWords("in den dreißiger Jahren", ["in", "den", NUM, "jahren"])
        self.assertWords("in den 30er Jahren", ["in", "den", NUM, "jahren"])
        self.assertWords("die Neunziger", ["die", NUM])
        self.assertWords("dreimal am Tag", [NUM_TIMES, "am", "tag"])  # <num> + mal is ONE token
        self.assertWords("3-mal am Tag", [NUM_TIMES, "am", "tag"])
        self.assertWords("3 mal am Tag", [NUM_TIMES, "am", "tag"])
        self.assertWords("zweieinhalb Milliarden Mal pro Sekunde", [NUM_TIMES, "pro", "sekunde"])
        self.assertWords("einmal", [NUM_TIMES])
        self.assertWords("normal", ["normal"])
        self.assertWords("mal sehen", ["mal", "sehen"])

    def test_letters_and_digits_in_one_token_are_split(self):
        self.assertWords("DCF77", ["dcf", NUM])
        self.assertWords("DCF siebenundsiebzig", ["dcf", NUM])
        self.assertWords("MP3", ["mp", NUM])
        self.assertWords("1930s", [NUM])
        self.assertWords("the 1930's", ["the", NUM])
        self.assertWords("300m", [NUM, "meter"])
        self.assertWords("20,000km", [NUM, "kilometer"])
        self.assertWords("the 80s", ["the", NUM])  # an attached s is the decade plural, never "seconds"
        self.assertWords("4K video", [NUM, "video"])
        self.assertWords("the 20th century", ["the", NUM, "century"])
        self.assertWords("700ths of a second", [NUM, "hundredth", "of", "a", "second"])  # what Whisper wrote for "seven hundredths"
        self.assertWords("38 millionths of a second", [NUM, "millionth", "of", "a", "second"])
        self.assertWords("20ths", [NUM])  # "twentieths": not one digit followed by zeros, so no fraction word

    def test_fraction_words_behind_a_number_are_kept_as_tokens(self):
        for spoken, written in (("seven hundredths of a second", "700ths of a second"),
                                ("one millionth of a second", "1 millionth of a second"),
                                ("thirty-eight millionths of a second", "38 millionths of a second"),
                                ("drei Zehntel Sekunden", "3 Zehntel Sekunden"), ("siebenhundertstel Sekunden", "7 Hundertstel Sekunden")):
            self.assertEqual(nw.spoken_words(spoken), nw.spoken_words(written), (spoken, written))
        self.assertWords("seven hundredths", [NUM, "hundredth"])
        self.assertWords("siebenhundertstel", [NUM, "hundredth"])
        self.assertNotEqual(nw.spoken_words("seven hundredths"), nw.spoken_words("seven hundred"))
        self.assertNotEqual(nw.spoken_words("one millionth"), nw.spoken_words("1 million"))
        self.assertWords("the tenth floor", ["the", NUM, "floor"])  # not behind a number: a number itself, like "10th"
        self.assertWords("the 10th floor", ["the", NUM, "floor"])

    def test_runs_that_are_separated_by_a_word_stay_separate(self):
        self.assertWords("zwei Katzen und drei Hunde", [NUM, "katzen", "und", NUM, "hunde"])
        self.assertWords("from 5 to 10", ["from", NUM, "to", NUM])

    def test_very_long_tokens_are_never_number_words(self):
        self.assertWords("x" * 500, ["x" * 500])
        self.assertWords("zwei" * 40, ["zwei" * 40])  # 160 letters: longer than the limit, so not a number word
        self.assertFalse(nw.is_number_word(""))


class CaptionsAreUntouchedTests(unittest.TestCase):
    def test_caption_normalisation_keeps_numbers_as_they_are(self):
        self.assertEqual(cp.normalize_words("zwanzigtausend 20,000 40%"), ["zwanzigtausend", "20000", "40"])
        self.assertEqual(cp.normalize_words("Kühl-Schlangen, 1930s! „Zitat“"), ["kühl", "schlangen", "1930s", "zitat"])

    def test_only_the_voice_checks_pass_the_number_words(self):
        self.assertGreater(mv.word_error_rate("zwanzig Meter", "20 Meter"), 0.0)  # the default is the caption normalisation
        self.assertEqual(mv.word_error_rate("zwanzig Meter", "20 Meter", nw.spoken_words), 0.0)


class VoiceLineCheckTests(unittest.TestCase):
    """mv.grade_line: the per-line voice check. Real pairs: what the script says vs what faster-whisper wrote."""

    def passes(self, script, heard):
        return mv.grade_line(script, heard)["ok"]

    def test_english_numbers_written_as_digits_pass(self):
        script = "About thirty GPS satellites circle the Earth, twenty thousand kilometers up."
        heard = "About 30 GPS satellites circle the Earth, 20,000 kilometers up."
        self.assertTrue(self.passes(script, heard))
        graded = mv.grade_line(script, heard)
        self.assertEqual(graded["wer"], 0.0)
        self.assertEqual(graded["cer"], 0.0)
        self.assertTrue(self.passes("A delay of one millionth of a second means an error of three hundred meters.",
                                    "A delay of 1 millionth of a second means an error of 300 m."))
        self.assertTrue(self.passes("Overall, they gain thirty-eight millionths of a second a day.",
                                    "Overall, they gain 38 millionths of a second a day."))
        self.assertTrue(self.passes("It was built in two thousand ten.", "It was built in 2010."))
        # real run (_num-test-en-gps): the script says "seven hundredths", faster-whisper wrote "700ths"
        graded = mv.grade_line("That signal needs about seven hundredths of a second to reach you.",
                               "That signal needs about 700ths of a second to reach you.")
        self.assertTrue(graded["ok"])
        self.assertEqual(graded["wer"], 0.0)
        self.assertTrue(self.passes("The drink is forty percent cheaper.", "The drink is 40% cheaper."))

    def test_german_numbers_written_as_digits_pass(self):
        self.assertTrue(self.passes("weit unter null Grad", "weit unter 0°"))
        self.assertTrue(self.passes("Im Jahr zweitausendzehn", "Im Jahr 2010"))
        self.assertTrue(self.passes("um fast vierzig Prozent", "um fast 40%"))
        self.assertTrue(self.passes("Der Sender heißt DCF siebenundsiebzig", "Der Sender heißt DCF77"))
        self.assertTrue(self.passes("Die Satelliten fliegen in zwanzigtausend Kilometern Höhe.", "Die Satelliten fliegen in 20.000 Kilometern Höhe."))
        self.assertTrue(self.passes("Das sind dreihundert Meter pro Mikrosekunde.", "Das sind 300 m pro Mikrosekunde."))
        self.assertTrue(self.passes("Sie gewinnen achtunddreißig Millionstel Sekunden pro Tag.", "Sie gewinnen 38 Millionstel Sekunden pro Tag."))

    def test_the_line_threshold_counts_the_written_words_not_the_collapsed_ones(self):
        # the band is chosen from the words of the script line, so collapsing "two thousand" into one <num> never makes the
        # check more lenient than it was
        self.assertEqual(mv.grade_line("Im Jahr zweitausendzehn", "Im Jahr 2010")["threshold"], mv.WER_LIMIT_SHORT)  # 3 words
        self.assertEqual(mv.grade_line("one two three four five six", "1 2 3 4 5 6")["threshold"], mv.WER_LIMIT_LONG)  # 6 words
        self.assertEqual(mv.grade_line("Over two thousand people came", "Over 2000 people came")["threshold"], mv.WER_LIMIT_LONG)  # 5
        self.assertEqual(mv.grade_line("Die Kerze brennt etwa vierzig Prozent länger", "x")["threshold"], mv.WER_LIMIT_LONG)
        self.assertEqual(mv.grade_line("Twenty thousand kilometers up in space", "x")["threshold"], mv.WER_LIMIT_LONG)  # 6 written
        self.assertEqual(mv.wer_threshold("a b c d e"), mv.WER_LIMIT_LONG)

    def test_a_wrong_word_in_a_line_with_a_multi_word_number_is_not_more_lenient_than_before(self):
        # "Over two thousand people came" is 5 written words but only 4 once the number is collapsed: still the strict limit
        self.assertFalse(self.passes("Over two thousand people came", "Over 2000 purple came"))
        self.assertFalse(self.passes("Twenty thousand kilometers up in space", "20,000 kilometers up in race"))
        self.assertTrue(self.passes("Over two thousand people came", "Over 2000 people came"))
        self.assertTrue(self.passes("Twenty thousand kilometers up in space", "20,000 km up in space"))

    def test_a_real_mishearing_still_fails(self):
        self.assertFalse(self.passes("Kopfhörer mit Noise Cancelling bekämpfen Lärm mit noch mehr Schall.",
                                     "Kopfhörer mit Neuskänzeling bekämpfen Lärm mit noch mehr Schall."))
        # the same mishearing in a line that also has a number: the number is not an excuse
        self.assertFalse(self.passes("Kopfhörer mit Noise Cancelling bekämpfen Lärm um vierzig Prozent.",
                                     "Kopfhörer mit Neuskänzeling bekämpfen Lärm um 40%."))
        # a short line: "Trifft" heard as "rift", with and without a number in it (a 2-token line: one error is half of it)
        self.assertFalse(self.passes("Trifft null", "rift 0"))
        self.assertFalse(self.passes("Trifft zu.", "rift zu."))
        # the unit counts as a word: "Trifft null Grad" has 3 tokens, and one wrong token of 3 is inside the short-line limit
        # exactly as it is for "Trifft zu Hause" (and for the same line with the number written out in both texts)
        self.assertEqual(self.passes("Trifft null Grad", "rift 0°"), self.passes("Trifft null Grad", "rift null Grad"))

    def test_a_number_the_voice_leaves_out_still_fails(self):
        self.assertFalse(self.passes("Die Kerze brennt etwa vierzig Prozent länger.", "Die Kerze brennt etwa länger."))
        self.assertFalse(self.passes("It is seven hundredths of a second.", "It is of a second."))

    def test_a_word_wrong_next_to_a_number_still_fails(self):
        self.assertFalse(self.passes("The satellites fly twenty thousand kilometers above the planet today.",
                                     "The satellites fly 20,000 kilometers above the plane tonight."))

    def test_a_swapped_unit_next_to_a_number_still_fails(self):
        # the unit is a content word: only its spelling is made equal (km = kilometers), never its meaning
        for script, heard in (("It takes thirty seconds to heat", "It takes 30 minutes to heat"),
                              ("Sie kreisen zwanzigtausend Kilometer hoch", "Sie kreisen 20.000 Meter hoch"),
                              ("Ein Liter kostet zwei Euro", "Ein Liter kostet 2 Dollar"),
                              ("three hundred meters", "300 kilometers"), ("zweieinhalb Stunden", "2,5 Minuten"),
                              ("zwanzig Euro", "20 Dollar"), ("Das sind etwa vierzig Prozent", "Das sind etwa 40 Grad"),
                              ("eine Stunde", "eine Sekunde"), ("Es dauert genau eine Stunde", "Es dauert genau 1 Sekunde")):
            self.assertFalse(self.passes(script, heard), (script, heard))
            self.assertGreater(mv.word_error_rate(script, heard, nw.spoken_words), 0.0, (script, heard))

    def test_a_dropped_unit_next_to_a_number_still_fails(self):
        for script, heard in (("It takes thirty seconds to heat", "It takes 30 to heat"),
                              ("Wir warten fast eine Stunde", "Wir warten fast eine"),
                              ("Draußen sind es null Grad", "Draußen sind es 0"),
                              ("Sie wiegt etwa vierzig Kilogramm", "Sie wiegt etwa 40"),
                              ("Es kostet nur zwei Euro", "Es kostet nur 2")):
            self.assertFalse(self.passes(script, heard), (script, heard))

    def test_the_same_unit_in_another_spelling_passes(self):
        for script, heard in (("It takes thirty seconds to heat", "It takes 30 s to heat"),
                              ("Sie kreisen zwanzigtausend Kilometer hoch", "Sie kreisen 20.000 km hoch"),
                              ("Ein Liter kostet zwei Euro", "Ein Liter kostet 2 €"),
                              ("Es dauert eine Stunde", "Es dauert 1 Stunde"),
                              ("A coffee costs five dollars today", "A coffee costs $5 today"),
                              ("Es sind null Grad Celsius", "Es sind 0°C"),
                              ("The fridge sits at minus five degrees Celsius", "The fridge sits at -5 °C")):
            self.assertTrue(self.passes(script, heard), (script, heard))

    def test_fractions_and_times_keep_their_token(self):
        # "millionths" heard as "million" (the real mishearing of line 9 in the GPS run) and "hundredths" as "hundred"
        self.assertFalse(self.passes("one millionth of a second", "1 million of a second"))
        self.assertFalse(self.passes("seven hundredths of a second", "seven hundred of a second"))
        self.assertTrue(self.passes("seven hundredths of a second", "700ths of a second"))
        self.assertGreater(mv.word_error_rate("A delay of one millionth of a second", "A delay of 1 million of a second",
                                              nw.spoken_words), 0.0)
        # "einmal" gets no extra token that dropping "ein" could hide
        self.assertFalse(self.passes("noch einmal", "noch mal"))
        self.assertTrue(self.passes("noch einmal", "noch 1 mal"))
        self.assertTrue(self.passes("Das passiert dreimal am Tag", "Das passiert 3-mal am Tag"))

    def test_a_different_number_of_the_same_kind_is_not_caught_by_design(self):
        # documented price of the tolerance: the value and the scale of a number are not checked, "dreißig" and "13" are both <num>
        self.assertTrue(self.passes("Es sind dreißig Grad", "Es sind 13 Grad"))
        self.assertEqual(nw.spoken_words("thirty thousand"), nw.spoken_words("30"))
        self.assertEqual(nw.spoken_words("three hundred"), nw.spoken_words("three thousand"))
        self.assertEqual(nw.spoken_words("zwanzig zwanzig"), nw.spoken_words("20"))  # a stutter inside a run is hidden too

    def test_plain_lines_are_graded_as_before(self):
        self.assertTrue(self.passes("Your fridge does not make cold.", "your fridge does not make cold"))
        self.assertFalse(self.passes("Your fridge does not make cold.", "your fridge dose nuts make bold"))
        self.assertTrue(self.passes("a non-stop ride on the earcup test today", "a nonstop ride on the ear cup test today"))


class WholeScriptGateTests(unittest.TestCase):
    """mv.check_srt_accuracy: Whisper's word cues of the whole narration against the whole script."""

    @staticmethod
    def cues(*texts):
        return [{"index": k + 1, "start": k * 0.4, "end": k * 0.4 + 0.3, "text": t} for k, t in enumerate(texts)]

    def test_digits_in_the_cues_are_not_a_difference(self):
        script = ["About thirty GPS satellites circle the Earth, twenty thousand kilometers up.",
                  "They gain thirty-eight millionths of a second a day."]
        heard = ("About", "30", "GPS", "satellites", "circle", "the", "Earth,", "20,000", "kilometers", "up.",
                 "They", "gain", "38", "millionths", "of", "a", "second", "a", "day.")
        ok, wer, msg, diffs = mv.check_srt_accuracy(self.cues(*heard), script)
        self.assertTrue(ok)
        self.assertEqual(wer, 0.0)
        self.assertEqual(diffs, [])
        self.assertIn("0 differing spot(s)", msg)

    def test_german_symbols_in_the_cues_are_not_a_difference(self):
        script = ["Es ist weit unter null Grad.", "Das sind fast vierzig Prozent.", "Der Sender heißt DCF siebenundsiebzig."]
        heard = ("Es", "ist", "weit", "unter", "0°.", "Das", "sind", "fast", "40%.", "Der", "Sender", "heißt", "DCF77.")
        ok, wer, _msg, diffs = mv.check_srt_accuracy(self.cues(*heard), script)
        self.assertTrue(ok)
        self.assertEqual(wer, 0.0)
        self.assertEqual(diffs, [])

    def test_real_mishearings_next_to_numbers_are_still_listed_and_fail(self):
        script = ["Kopfhörer mit Noise Cancelling bekämpfen Lärm um vierzig Prozent mit noch mehr Schall."]
        heard = ("Kopfhörer", "mit", "Neuskänzeling", "bekämpfen", "Lärm", "um", "40%", "mit", "noch", "mehr", "Schall.")
        ok, wer, msg, _diffs = mv.check_srt_accuracy(self.cues(*heard), script)
        self.assertFalse(ok)
        self.assertGreater(wer, mv.SRT_WER_LIMIT)
        self.assertIn("neuskänzeling", msg)
        self.assertNotIn("<num>", msg)  # the number itself is not a difference


    def test_a_unit_written_in_another_spelling_is_not_a_difference(self):
        script = ["Sie kreisen zwanzigtausend Kilometer hoch.", "Das sind dreihundert Meter Fehler.", "Es kostet fünf Euro."]
        heard = ("Sie", "kreisen", "20.000", "km", "hoch.", "Das", "sind", "300", "m", "Fehler.", "Es", "kostet", "5", "€.")
        ok, wer, _msg, diffs = mv.check_srt_accuracy(self.cues(*heard), script)
        self.assertTrue(ok)
        self.assertEqual(wer, 0.0)
        self.assertEqual(diffs, [])

    def test_a_swapped_unit_in_the_cues_is_listed_and_fails(self):
        script = ["Sie kreisen zwanzigtausend Kilometer hoch."]
        heard = ("Sie", "kreisen", "20.000", "Meter", "hoch.")
        ok, wer, msg, diffs = mv.check_srt_accuracy(self.cues(*heard), script)
        self.assertFalse(ok)
        self.assertGreater(wer, mv.SRT_WER_LIMIT)
        self.assertEqual(diffs, ['script "kilometer" -> subtitle "meter"'])
        self.assertIn('"kilometer" -> subtitle "meter"', msg)


class DifferencesAreListedAfterTheSameNormalisationTests(unittest.TestCase):
    def test_word_differences_can_use_the_voice_words(self):
        self.assertEqual(mv.word_differences("Im Jahr zweitausendzehn", "Im Jahr 2010", words=nw.spoken_words), [])
        self.assertEqual(mv.word_differences("Im Jahr zweitausendzehn", "Im Jahr 2010"),
                         ['script "zweitausendzehn" -> subtitle "2010"'])  # the default stays the caption normalisation


if __name__ == "__main__":
    unittest.main()
