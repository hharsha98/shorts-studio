#!/usr/bin/env python3
"""Number tolerance for the VOICE-quality comparisons (word error rate and letter error rate).

Why: the scripts spell numbers as words (the voice reads them reliably), but the transcriber (faster-whisper) often writes
them as digits or symbols:

    script "twenty thousand kilometers"   heard "20,000 km"
    script "zweitausendzehn"              heard "2010"
    script "vierzig Prozent"              heard "40%"
    script "null Grad"                    heard "0°"
    script "DCF siebenundsiebzig"         heard "DCF77"

The audio was fine, but the word-for-word comparison failed. So both sides go through spoken_words() first: every maximal
run of number tokens becomes ONE placeholder token, "<num>". "twenty thousand" and "20,000" are then both ["<num>"].

The unit next to a number is NOT part of the run. It is a content word (a swapped or dropped unit is a real error), so it
stays, written in one standard spelling on both sides: "twenty thousand kilometers" and "20,000 km" are both
["<num>", "kilometer"], but "thirty seconds" ["<num>", "second"] differs from "30 minutes" ["<num>", "minute"], and a unit the
voice leaves out is a missing token.

This is used ONLY by the voice-quality checks (make_video.grade_line and make_video.check_srt_accuracy). The captions
never see it: studio/captions.py keeps its own normalize_words(), and the caption words are always the script's own words.

What counts as a number token (see the tables below for the exact words):
  * a token with a digit ("20000", "77", "2010", "30er", "1930s"); a token that mixes letters and digits is split, so
    "DCF77" is ["dcf", <num>]. The "," "." around digits are punctuation and are dropped like everywhere else
  * English number words: zero .. nineteen, twenty .. ninety, hundred, thousand, million, billion (trillion), the decades
    (thirties). A hyphenated "thirty-eight" is two tokens in the same run
  * German number words: a token that is COMPLETELY made of the morphemes null, ein, eins, eine, zwei, drei, vier, fünf,
    sechs, sieben, acht, neun, zehn, elf, zwölf, zwanzig .. neunzig, dreißig, hundert, tausend, und, million(en),
    milliarde(n), halb, einhalb (plus sechzehn / siebzehn, whose stems are irregular, and the spelling dreissig).
    "zweitausendzehn", "achtunddreißig", "zweieinhalb", "siebenundsiebzig" and "zwanzigtausend" are numbers; "einem",
    "einen", "Achtung" or "Zeitung" are not (the whole token must split into morphemes, and "und" alone is never enough)
  * a German tens/hundred/thousand number with -er / -ern / -ers ("dreißiger", "neunziger": the 30s, the 90s)

What joins a run:
  * inside a run only: "and" / "und" (also "and a"), "a" between numbers, "half" after "and (a)", "point" / "komma"
    between numbers ("three point five" = "3.5"); a leading "minus" / "plus" / "negative" before a number; a leading "a"
    before hundred / thousand / million / billion ("a hundred meters" = "100 m"); a detached "k" / "bn" ("5 k")

What stays outside the run, as a standard token right after the <num> (the table is POST_WORDS):
  * percent / prozent / "%" -> "percent"; degrees / grad / "°" -> "degree", and celsius / fahrenheit / C / F right after
    a degree word -> "celsius" / "fahrenheit"
  * a currency word or symbol -> "euro" / "dollar" / "pound" / "cent" ("5 €", "€5", "fünf Euro", "five dollars", "$5");
    a leading symbol moves behind its number
  * a measuring unit, whatever the spelling: m / meter / meters / metre / Metern -> "meter", km / kilometers -> "kilometer",
    s / sec / seconds / Sekunden -> "second", h / hours / Stunden -> "hour", kg, g, l, ml, min, Hz, ... (see UNITS). The
    transcriber writes "300 m" for "three hundred meters"; both are ["<num>", "meter"]
  * a fraction word: tenth(s), hundredth(s), thousandth(s), millionth(s), billionth(s), Zehntel, Hundertstel, Tausendstel,
    Millionstel -> "tenth", "hundredth", ... "seven hundredths" ["<num>", "hundredth"] is not "seven hundred" ["<num>"],
    and the digit form "700ths" (what the transcriber writes for it) is ["<num>", "hundredth"] too. A fraction word that
    does NOT follow a number ("the tenth floor") is a number itself, like the "10th" the transcriber writes
  * "mal" right after a number: "<num>mal" is ONE token ("dreimal", "3-mal" and "3 mal" are all ["<num>mal"]), so
    "einmal" does not add a token that "mal" alone would not have

Choices to know about:
  * "ein" / "eine" are number tokens (the German article is also the number one). The article is then compared as <num>
    on both sides, which only means it is not scored. A unit after it is still scored ("eine Stunde" is
    ["<num>", "hour"], "eine Sekunde" is ["<num>", "second"]). "einem", "einer", "einen" are not numbers, as above.
  * "acht" is a number even in "Acht geben"; "elf" and "one" are numbers even as the creature / pronoun. Both sides are
    treated the same, so this only decides what is not scored.
  * An attached "s" ("1930s", "80s") is the decade plural, never "seconds": write "20 s" or "20 seconds" for seconds.
  * Limits, the price of the tolerance: the VALUE and the SCALE of a number are not checked. "dreißig" heard as
    "dreizehn" (30 vs 13), "thirty thousand" heard as "30", "three hundred" heard as "three thousand" are all one <num>;
    so is a stutter inside a run ("zwanzig zwanzig"). Only the fraction words above are told apart (millionths vs
    millions, hundredths vs hundred). The other words of the line are still scored, and a number the voice leaves out is
    still a missing token.
  * Not handled: ordinals (first, dritte, "3."), clock times ("8:30" vs "acht Uhr dreißig"), fractions ("1/2" vs "one half").

Pure functions, Python standard library only. Tests: studio/tests/test_number_words.py.
"""

from __future__ import annotations

import functools
import re
import unicodedata

from captions import normalize_words

NUM = "<num>"  # the placeholder every run of number tokens is replaced by
NUM_TIMES = NUM + "mal"  # "dreimal" / "3-mal" / "3 mal": one token, see _after_run


def _table(spec: dict[str, str]) -> dict[str, str]:
    """{standard word: "spelling spelling ..."} -> {spelling: standard word}."""
    return {spelling: standard for standard, spellings in spec.items() for spelling in spellings.split()}


# ---- English ------------------------------------------------------------------------------------------------------------
EN_NUMBER_WORDS = frozenset(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen "
    "nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand million billion trillion "
    "twenties thirties forties fifties sixties seventies eighties nineties".split())
BIG_WORDS = frozenset("hundred thousand million billion trillion".split())  # "a hundred" starts a run

# ---- German -------------------------------------------------------------------------------------------------------------
DE_MORPHEMES = tuple(sorted(
    "null ein eins eine zwei drei vier fünf sechs sieben acht neun zehn elf zwölf zwanzig dreißig dreissig vierzig fünfzig "
    "sechzig siebzig achtzig neunzig hundert tausend und zehntel hundertstel tausendstel millionstel milliarden millionen "
    "milliarde million halb einhalb sechzehn siebzehn".split(), key=len, reverse=True))
DE_TENS_ENDINGS = ("zwanzig", "dreißig", "dreissig", "vierzig", "fünfzig", "sechzig", "siebzig", "achtzig", "neunzig",
                   "hundert", "tausend")  # a number that ends like this may carry -er / -ern / -ers (dreißiger)
DE_DECADE_SUFFIXES = ("ern", "ers", "er")
DE_TIMES = "mal"  # dreimal = <num> + mal

# ---- fractions: a standard token behind the number ("seven hundredths"), not part of the run -------------------------------
FRACTIONS = _table({
    "tenth": "tenth tenths zehntel", "hundredth": "hundredth hundredths hundertstel",
    "thousandth": "thousandth thousandths tausendstel", "millionth": "millionth millionths millionstel",
    "billionth": "billionth billionths"})
DE_FRACTION_WORDS = tuple(sorted(("zehntel", "hundertstel", "tausendstel", "millionstel"), key=len, reverse=True))  # "siebenhundertstel"
_DIGIT_FRACTIONS = {2: "hundredth", 3: "thousandth", 6: "millionth", 9: "billionth"}  # "700ths" = 7 followed by 2 zeros

# ---- what joins a run ---------------------------------------------------------------------------------------------------
SIGNS = frozenset(("minus", "plus", "negative"))
AND_WORDS = frozenset(("and", "und"))
POINT_WORDS = frozenset(("point", "komma"))
SCALE_WORDS = frozenset(("k", "bn"))  # "5 k", "2 bn": a scale like thousand / billion, so part of the run

# ---- what stays outside the run, written in one standard spelling (spelling -> standard word) ----------------------------
PERCENT = _table({"percent": "percent prozent pct"})
DEGREES = _table({"degree": "degrees degree grad"})
AFTER_DEGREES = _table({"celsius": "celsius c", "fahrenheit": "fahrenheit f"})  # only straight after a degree word
CURRENCY = _table({"euro": "euro euros eur", "dollar": "dollar dollars usd", "pound": "pound pounds gbp", "cent": "cent cents"})
UNITS = _table({
    "meter": "m meter meters metre metres metern", "kilometer": "km kilometer kilometers kilometre kilometres kilometern",
    "centimeter": "cm centimeter centimeters centimetre centimetres zentimeter zentimetern",
    "millimeter": "mm millimeter millimeters millimetre millimetres millimetern",
    "kilogram": "kg kilogram kilograms kilogramm", "gram": "g gram grams gramm", "milligram": "mg milligram milligrams milligramm",
    "liter": "l liter liters litre litres", "milliliter": "ml milliliter milliliters millilitre millilitres",
    "second": "s sec second seconds sekunde sekunden", "millisecond": "ms millisecond milliseconds millisekunde millisekunden",
    "minute": "min minute minutes minuten", "hour": "h hour hours stunde stunden",
    "hertz": "hz hertz", "kilohertz": "khz kilohertz", "megahertz": "mhz megahertz", "gigahertz": "ghz gigahertz",
    "kilobyte": "kb kilobyte kilobytes", "megabyte": "mb megabyte megabytes", "gigabyte": "gb gigabyte gigabytes",
    "terabyte": "tb terabyte terabytes", "mph": "mph"})
POST_WORDS = {**PERCENT, **DEGREES, **CURRENCY, **UNITS}

# glued to digits in ONE token and read as part of the number itself ("1930s", "30er", "20th", "4k", "3x")
ATTACHED_SUFFIXES = SCALE_WORDS | frozenset(("s", "st", "nd", "rd", "th", "ths", "er", "ern", "ers", "ten", "te", "ter", "tes",
                                             "ste", "sten", "ster", "stes", "stem", "x"))

CURRENCY_SYMBOLS = {"€": "euro", "$": "dollar", "£": "pound"}
DEGREE_SYMBOLS = ("°", "º", "˚")  # read as the word "degrees" (normalize_words would drop them)
_LEADING_CURRENCY = re.compile(r"([€$£])\s*(?=\d)")  # "$5": the symbol is moved behind its number
PRE_MARK = ""  # private-use character: survives normalize_words, marks a leading currency symbol

# the kinds of token in spoken_words' working list
NUMBER, WORD, FRACTION, PRE = "number", "word", "fraction", "pre"

_DIGIT = re.compile(r"\d")
_CHUNKS = re.compile(r"\d+|\D+")
_MAX_TOKEN = 80  # a longer token is never a number word (keeps the splitting cheap)


# --------------------------------------------------------------------------------------------------------------------------
# Number words
# --------------------------------------------------------------------------------------------------------------------------


@functools.lru_cache(maxsize=None)
def _de_splits(token: str, pos: int, used_number: bool) -> bool:
    """Can token[pos:] be written with DE_MORPHEMES only, at least one of them being more than "und"?"""
    if pos == len(token):
        return used_number
    return any(token.startswith(m, pos) and _de_splits(token, pos + len(m), used_number or m != "und") for m in DE_MORPHEMES)


def is_german_number(token: str) -> bool:
    """A German number word: the WHOLE token splits into number morphemes ("zweitausendzehn"), or such a number ending in
    tens / hundred / thousand carries -er ("dreißiger"). "einem", "Achtung" or a lone "und" are not."""
    if not token or len(token) > _MAX_TOKEN:
        return False
    if _de_splits(token, 0, False):
        return True
    for suffix in DE_DECADE_SUFFIXES:
        if token.endswith(suffix):
            stem = token[:-len(suffix)]
            if stem.endswith(DE_TENS_ENDINGS) and _de_splits(stem, 0, False):
                return True
    return False


def is_number_word(token: str) -> bool:
    """An English or German number word (lowercase). Digits are not handled here."""
    return token in EN_NUMBER_WORDS or is_german_number(token)


def _digit_fraction(digits: str) -> str | None:
    """The fraction behind a digit form "700ths": one digit and zeros ("10ths" tenth, "700ths" hundredth, "1000ths" thousandth,
    "38000000ths" is not, it has two leading digits); None when the digits are no such fraction."""
    stem = digits.rstrip("0")
    zeros = len(digits) - len(stem)
    if len(stem) != 1:
        return None
    return "tenth" if (zeros, stem) == (1, "1") else _DIGIT_FRACTIONS.get(zeros)


# --------------------------------------------------------------------------------------------------------------------------
# Tokens -> runs -> placeholder
# --------------------------------------------------------------------------------------------------------------------------


def _items(text: str) -> list[tuple[str, str]]:
    """The text as (kind, word) pairs: NUMBER for digits and number words, FRACTION for a fraction word (the standard word),
    PRE for a currency symbol in front of a number (the standard word), WORD for the rest."""
    text = unicodedata.normalize("NFC", text or "")
    text = _LEADING_CURRENCY.sub(lambda m: f" {PRE_MARK}{CURRENCY_SYMBOLS[m.group(1)]} ", text)
    for symbol, word in CURRENCY_SYMBOLS.items():
        text = text.replace(symbol, f" {word} ")
    text = text.replace("%", " percent ")
    for symbol in DEGREE_SYMBOLS:
        text = text.replace(symbol, " degrees ")
    items: list[tuple[str, str]] = []
    for token in normalize_words(text):
        if token.startswith(PRE_MARK):
            items.append((PRE, token[len(PRE_MARK):]))
        elif _DIGIT.search(token):  # "DCF77" -> dcf + 77; "300m" -> 300 + m (a unit); "1930s" -> 1930 + s (part of the number)
            digits, after_digits = "", False
            for chunk in _CHUNKS.findall(token):
                if _DIGIT.match(chunk):
                    items.append((NUMBER, chunk))
                    digits, after_digits = chunk, True
                    continue
                fraction = _digit_fraction(digits) if after_digits and chunk == "ths" else None
                if fraction:  # "700ths" = seven hundredths
                    items.append((FRACTION, fraction))
                elif after_digits and chunk in ATTACHED_SUFFIXES:
                    items.append((NUMBER, chunk))
                elif after_digits and chunk in AFTER_DEGREES:  # "20C" = 20 degrees Celsius
                    items.extend(((WORD, "degrees"), (WORD, chunk)))
                else:
                    items.append((WORD, chunk))
                after_digits = False
        elif token in FRACTIONS:
            items.append((FRACTION, FRACTIONS[token]))
        elif token.endswith(DE_FRACTION_WORDS) and is_german_number(token):
            fraction_word = next(w for w in DE_FRACTION_WORDS if token.endswith(w))  # "siebenhundertstel"
            stem = token[:-len(fraction_word)]
            if stem and is_german_number(stem):
                items.append((NUMBER, stem))
            items.append((FRACTION, FRACTIONS[fraction_word]))
        elif is_number_word(token):
            items.append((NUMBER, token))
        elif token.endswith(DE_TIMES) and len(token) > len(DE_TIMES) and is_german_number(token[:-len(DE_TIMES)]):
            items.append((NUMBER, token[:-len(DE_TIMES)]))
            items.append((WORD, DE_TIMES))
        else:
            items.append((WORD, token))
    return items


def _connector_end(items: list[tuple[str, str]], j: int) -> int:
    """If a connector that belongs inside a run starts at items[j], the index after the number it leads to; else 0.
    "and 5", "and a half", "point 5", "a 100" (but not "and a few")."""
    n, word = len(items), items[j][1]
    if word in AND_WORDS:
        k = j + 1
        if k < n and items[k][1] == "a":
            k += 1
        if k < n and (items[k][0] == NUMBER or items[k][1] == "half"):
            return k + 1
    elif (word in POINT_WORDS or word == "a") and j + 1 < n and items[j + 1][0] == NUMBER:
        return j + 2
    return 0


def _run_end(items: list[tuple[str, str]], i: int) -> int:
    """The index after the run of number tokens that starts at items[i], or i when no run starts there. A fraction word
    that is not behind a number starts a run itself ("the tenth floor" = "the 10th floor")."""
    n = len(items)
    kind, word = items[i]
    if kind in (NUMBER, FRACTION):
        j = i + 1
    elif i + 1 < n and items[i + 1][0] == NUMBER and (word in SIGNS or (word == "a" and items[i + 1][1] in BIG_WORDS)):
        j = i + 2  # "minus five", "a hundred"
    else:
        return i
    while j < n:
        kind, word = items[j]
        if kind == NUMBER or (kind == WORD and word in SCALE_WORDS):
            j += 1
        elif _connector_end(items, j):
            j = _connector_end(items, j)
        else:
            break
    return j


def _after_run(items: list[tuple[str, str]], i: int, out: list[str], pre: str | None) -> int:
    """`out` ends with the <num> of a run that ended at items[i]. Append what stays outside the run (fraction word, then
    percent / degree / currency / unit, each in its standard spelling), or "mal" merged into the <num>. A currency symbol
    that stood in front of the number (`pre`) is written behind it, unless the text names its currency there too.
    Returns the index of the first item that is left."""
    n = len(items)
    if i < n and items[i][0] == FRACTION:
        out.append(items[i][1])
        i += 1
    elif i < n and items[i] == (WORD, DE_TIMES):
        out[-1] = NUM_TIMES
        return i + 1
    if i < n and items[i][0] == WORD and items[i][1] in POST_WORDS:
        standard = POST_WORDS[items[i][1]]
        out.append(standard)
        i += 1
        if standard == "degree" and i < n and items[i][0] == WORD and items[i][1] in AFTER_DEGREES:
            out.append(AFTER_DEGREES[items[i][1]])
            i += 1
    elif pre:
        out.append(pre)
    return i


def spoken_words(text: str) -> list[str]:
    """The words of `text` as the voice check compares them: captions.normalize_words, then every maximal run of number
    tokens (digits, number words, and what joins them, see the module doc) replaced by ONE "<num>" token. The unit,
    currency, percent, degree, fraction word or "mal" next to a number stays, in its standard spelling."""
    items = _items(text)
    out: list[str] = []
    i = 0
    while i < len(items):
        start, pre = i, None
        if items[i][0] == PRE:  # "$5": the run starts behind the symbol
            if i + 1 < len(items) and _run_end(items, i + 1) > i + 1:
                start, pre = i + 1, items[i][1]
            else:
                out.append(items[i][1])
                i += 1
                continue
        end = _run_end(items, start)
        if end > start:
            out.append(NUM)
            i = _after_run(items, end, out, pre)
        else:
            out.append(items[i][1])
            i += 1
    return out
