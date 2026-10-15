"""Unit tests for the German Thorsten voice: voice-de/server.py (its pure helpers and its HTTP layer with a fake engine), the
per-language routing in studio/voice_take.py, the one-take behaviour for a deterministic engine, and the preflight messages in
studio/make_video.py. No model, no network except 127.0.0.1 sockets of the fake server; the VoiceStudio side is faked.

Run from /Users/harsha/shorts-studio:
    python3 -m unittest discover -s studio/tests -t .
"""

import contextlib
import http.client
import importlib.util
import io
import json
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import wave
from pathlib import Path
from unittest import mock

STUDIO_DIR = Path(__file__).resolve().parent.parent
ROOT = STUDIO_DIR.parent
sys.path.insert(0, str(STUDIO_DIR))

import make_video as mv  # noqa: E402
import voice_take as vt  # noqa: E402
from studio.tests.test_voice_take import LINES, FakeVoice, TmpDirTest, simple_grade, tone  # noqa: E402

FULL = " ".join(LINES)


def load_server():
    """voice-de/server.py as a module (the folder name has a hyphen, so it cannot be imported the normal way). The file only
    imports the standard library at the top: torch and kokoro are loaded inside ThorstenEngine, which these tests never build."""
    spec = importlib.util.spec_from_file_location("voice_de_server", ROOT / "voice-de" / "server.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["voice_de_server"] = module
    spec.loader.exec_module(module)
    return module


srv = load_server()


# --------------------------------------------------------------------------------------
# voice-de/server.py: cutting text into pieces
# --------------------------------------------------------------------------------------


class SentenceSplitTests(unittest.TestCase):
    def test_splits_at_full_stop_question_mark_exclamation_and_ellipsis(self):
        text = "Das ist eins. Ist das zwei? Drei! Und vier… Fünf."
        self.assertEqual(srv.split_sentences(text), ["Das ist eins.", "Ist das zwei?", "Drei!", "Und vier…", "Fünf."])

    def test_a_text_without_end_sign_is_one_sentence(self):
        self.assertEqual(srv.split_sentences("Kein Satzzeichen am Ende"), ["Kein Satzzeichen am Ende"])
        self.assertEqual(srv.split_sentences("Eins. Zwei ohne Ende"), ["Eins.", "Zwei ohne Ende"])

    def test_line_breaks_and_double_spaces_become_single_spaces(self):
        self.assertEqual(srv.split_sentences("Eins.\n\nZwei   drei.\nVier."), ["Eins.", "Zwei drei.", "Vier."])

    def test_decimal_numbers_and_inner_dots_do_not_split(self):
        self.assertEqual(srv.split_sentences("Es sind 3.5 Grad warm. Fertig."), ["Es sind 3.5 Grad warm.", "Fertig."])

    def test_german_abbreviations_do_not_split(self):
        self.assertEqual(srv.split_sentences("Das sind ca. 5 Meter. Gut."), ["Das sind ca. 5 Meter.", "Gut."])
        self.assertEqual(srv.split_sentences("Das gilt z. B. für Uhren. Gut."), ["Das gilt z. B. für Uhren.", "Gut."])
        self.assertEqual(srv.split_sentences("Es geht um Wellen, d. h. um Schall. Ende."), ["Es geht um Wellen, d. h. um Schall.", "Ende."])

    def test_a_sentence_ending_in_a_letter_still_splits(self):
        self.assertEqual(srv.split_sentences("Das ist Vitamin C. Dann kommt D."), ["Das ist Vitamin C.", "Dann kommt D."])

    def test_closing_quote_stays_with_its_sentence(self):
        self.assertEqual(srv.split_sentences("Er sagte: „Nein.“ Dann ging er."), ["Er sagte: „Nein.“", "Dann ging er."])

    def test_both_real_scripts_split_into_their_lines_or_more(self):
        for name in ("2026-10-14-de-noise-cancelling", "2026-10-22-de-funkuhr"):
            path = ROOT / "content" / name / "script.json"
            if not path.is_file():
                self.skipTest(f"{path} not found")
            lines = [line["text"].strip() for line in json.loads(path.read_text(encoding="utf-8"))["lines"]]
            sentences = srv.split_sentences(" ".join(lines))
            self.assertGreaterEqual(len(sentences), len(lines))
            self.assertEqual(" ".join(sentences), " ".join(lines))  # nothing lost, nothing added
            self.assertTrue(all(len(s) <= srv.MAX_PIECE_CHARS for s in sentences))


class LongSentenceTests(unittest.TestCase):
    def test_a_short_sentence_stays_whole(self):
        self.assertEqual(srv.split_long("Ein kurzer Satz.", 50), ["Ein kurzer Satz."])

    def test_a_long_sentence_is_cut_at_the_comma_nearest_the_middle(self):
        sentence = "Erst kommt ein sehr langer Anfang mit vielen Wörtern, dann folgt der Rest des Satzes, der ebenfalls ziemlich lang ist"
        pieces = srv.split_long(sentence, 80)
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(len(p) <= 80 for p in pieces))
        self.assertEqual(" ".join(pieces), sentence)
        self.assertTrue(pieces[0].endswith(","))  # cut after a comma, not inside a word

    def test_without_commas_it_cuts_at_a_space(self):
        sentence = " ".join(["wort"] * 40)
        pieces = srv.split_long(sentence, 60)
        self.assertTrue(all(len(p) <= 60 for p in pieces))
        self.assertEqual(" ".join(pieces), sentence)

    def test_one_endless_word_is_cut_by_length(self):
        pieces = srv.split_long("a" * 130, 50)
        self.assertEqual([len(p) for p in pieces], [50, 50, 30])

    def test_speakable_needs_a_letter_or_digit(self):
        self.assertTrue(srv.speakable("Hallo."))
        self.assertTrue(srv.speakable("7"))
        self.assertFalse(srv.speakable("… !"))
        self.assertFalse(srv.speakable(""))


class PiecePlanTests(unittest.TestCase):
    def test_pauses_follow_the_sentences_and_the_last_has_none(self):
        plan = srv.plan_pieces("Eins. Ist das zwei? Drei! Vier…")
        self.assertEqual([p for p, _ in plan], ["Eins.", "Ist das zwei?", "Drei!", "Vier…"])
        self.assertEqual([pause for _, pause in plan], [srv.SENTENCE_PAUSE_S, srv.SENTENCE_PAUSE_LONG_S, srv.SENTENCE_PAUSE_S, 0.0])

    def test_sentence_pauses_are_between_a_quarter_and_a_third_of_a_second(self):
        # the existing silence snapping (voice_take.py) looks for >= 0.12 s of quiet at every line boundary
        for pause in (srv.SENTENCE_PAUSE_S, srv.SENTENCE_PAUSE_LONG_S):
            self.assertGreaterEqual(pause, 0.25)
            self.assertLessEqual(pause, 0.35)
        self.assertGreater(srv.SENTENCE_PAUSE_S, vt.SILENCE_MIN_S)

    def test_a_long_sentence_gets_short_pauses_inside_and_the_full_pause_after(self):
        sentence = ("Das ist der erste lange Teil mit vielen Wörtern drin, " * 5 + "und das ist der letzte lange Teil mit vielen Wörtern drin.")
        plan = srv.plan_pieces(sentence + " Danach kommt noch etwas.")
        pauses = [pause for _, pause in plan]
        self.assertEqual(len(plan), 3)  # the long sentence is cut in two, then the short one
        self.assertEqual(pauses[0], srv.PHRASE_PAUSE_S)  # inside the long sentence
        self.assertEqual(pauses[-2], srv.SENTENCE_PAUSE_S)  # after the long sentence
        self.assertTrue(all(p == srv.PHRASE_PAUSE_S for p in pauses[:-2]))
        self.assertEqual(pauses[-1], 0.0)

    def test_pieces_without_letters_are_dropped(self):
        plan = srv.plan_pieces("Eins. … Zwei.")
        self.assertEqual([p for p, _ in plan], ["Eins.", "Zwei."])

    def test_nothing_to_say_gives_an_empty_plan(self):
        self.assertEqual(srv.plan_pieces("... !!"), [])
        self.assertEqual(srv.plan_pieces("   "), [])


# --------------------------------------------------------------------------------------
# voice-de/server.py: request checking, the wav, the HTTP layer
# --------------------------------------------------------------------------------------


def request_body(**fields) -> bytes:
    return json.dumps(fields).encode("utf-8")


class ParseRequestTests(unittest.TestCase):
    def refused(self, raw: bytes) -> srv.RequestError:
        with self.assertRaises(srv.RequestError) as caught:
            srv.parse_request(raw)
        return caught.exception

    def test_minimal_request_gets_the_defaults(self):
        self.assertEqual(srv.parse_request(request_body(input="Hallo.")), {"text": "Hallo.", "speed": 1.0, "seed": None})

    def test_full_request_like_voice_take_sends_it(self):
        body = request_body(input="Hallo.", voice="thorsten", response_format="wav", seed=7, speed=1.1, instructions="ignored", model="x")
        self.assertEqual(srv.parse_request(body), {"text": "Hallo.", "speed": 1.1, "seed": 7})

    def test_voice_and_format_are_case_insensitive_and_may_be_empty(self):
        self.assertEqual(srv.parse_request(request_body(input="Hi.", voice="Thorsten", response_format="WAV"))["text"], "Hi.")
        self.assertEqual(srv.parse_request(request_body(input="Hi.", voice="", response_format=None))["text"], "Hi.")

    def test_bad_json_and_wrong_shape_are_400(self):
        for raw in (b"{nope", b"\xff\xfe", b"[1, 2]", b'"text"', b"null"):
            self.assertEqual(self.refused(raw).status, 400, raw)

    def test_input_must_be_a_non_empty_string(self):
        for body in ({}, {"input": ""}, {"input": "   "}, {"input": 5}, {"input": ["Hallo."]}, {"input": None}):
            error = self.refused(json.dumps(body).encode())
            self.assertEqual(error.status, 400, body)
            self.assertIn("input", str(error))

    def test_input_length_limit_is_the_same_as_voicestudio(self):
        self.assertEqual(srv.parse_request(request_body(input="a" * (srv.MAX_INPUT_CHARS - 1)))["text"][:1], "a")
        error = self.refused(request_body(input="a" * srv.MAX_INPUT_CHARS))
        self.assertEqual(error.status, 400)
        self.assertIn("4096", str(error))

    def test_only_the_thorsten_voice_and_wav_exist(self):
        error = self.refused(request_body(input="Hi.", voice="Ryan"))
        self.assertEqual(error.status, 400)
        self.assertIn("thorsten", str(error))
        self.assertIn("Ryan", str(error))
        self.assertEqual(self.refused(request_body(input="Hi.", voice=5)).status, 400)
        error = self.refused(request_body(input="Hi.", response_format="mp3"))
        self.assertEqual(error.status, 400)
        self.assertIn("wav", str(error))

    def test_speed_must_be_a_number_in_range(self):
        for speed in (0.1, 3, -1, "fast", True, [1.0]):
            self.assertEqual(self.refused(request_body(input="Hi.", speed=speed)).status, 400, speed)
        self.assertEqual(self.refused(b'{"input": "Hi.", "speed": NaN}').status, 400)
        self.assertEqual(srv.parse_request(request_body(input="Hi.", speed=0.5))["speed"], 0.5)
        self.assertEqual(srv.parse_request(request_body(input="Hi.", speed=2))["speed"], 2.0)

    def test_seed_must_be_a_whole_number_but_is_not_used(self):
        for seed in ("7", 1.5, True, [1]):
            self.assertEqual(self.refused(request_body(input="Hi.", seed=seed)).status, 400, seed)
        self.assertEqual(srv.parse_request(request_body(input="Hi.", seed=0))["seed"], 0)

    def test_a_text_with_nothing_to_say_is_422(self):
        self.assertEqual(self.refused(request_body(input="… !!")).status, 422)


class WavTests(unittest.TestCase):
    def test_wav_is_24khz_mono_16bit(self):
        data = srv.wav_bytes(tone(0.5))
        with wave.open(io.BytesIO(data)) as w:
            self.assertEqual((w.getframerate(), w.getnchannels(), w.getsampwidth()), (24000, 1, 2))
            self.assertEqual(w.getnframes(), 12000)

    def test_pieces_are_joined_with_their_pauses_and_no_pause_at_the_end(self):
        out = srv.join_pieces([tone(0.1), tone(0.2), tone(0.1)], [0.30, 0.35, 9.0])
        self.assertEqual(len(out), round((0.1 + 0.30 + 0.2 + 0.35 + 0.1) * 24000))
        self.assertEqual(max(abs(s) for s in out[2400:2400 + 7200]), 0)  # the pause is digital silence

    def test_synthesize_voices_every_piece_once_in_order(self):
        class Engine:
            def __init__(self):
                self.calls = []

            def speak(self, piece, speed=1.0):
                self.calls.append((piece, speed))
                return tone(0.1)

        engine = Engine()
        samples, pieces = srv.synthesize(engine, "Eins. Zwei? Drei.", 1.2)
        self.assertEqual(engine.calls, [("Eins.", 1.2), ("Zwei?", 1.2), ("Drei.", 1.2)])
        self.assertEqual(pieces, 3)
        self.assertEqual(len(samples), round((0.1 * 3 + 0.30 + 0.35) * 24000))


class FakeEngine:
    def __init__(self, fail_on=None):
        self.fail_on, self.calls = fail_on, []

    def speak(self, piece, speed=1.0):
        self.calls.append(piece)
        if self.fail_on and self.fail_on in piece:
            raise RuntimeError("the model broke")
        return tone(0.2)


class HttpLayerTests(unittest.TestCase):
    def setUp(self):
        self.engine = FakeEngine(fail_on="KAPUTT")
        self.server = srv.make_server(self.engine, 0)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def call(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                conn.request(method, path, body=body, headers=headers if headers is not None else {})
                resp = conn.getresponse()
                return resp.status, resp.getheader("Content-Type"), resp.read()
        finally:
            conn.close()

    def raw(self, request: bytes) -> bytes:
        """Send raw bytes, read the whole answer (the server closes the connection after it)."""
        with contextlib.redirect_stderr(io.StringIO()), socket.create_connection(("127.0.0.1", self.port), timeout=10) as sock:
            sock.sendall(request)
            reply = b""
            while chunk := sock.recv(4096):
                reply += chunk
        return reply

    def post(self, payload, content_type="application/json"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return self.call("POST", "/v1/audio/speech", data, {"Content-Type": content_type})

    def test_binds_to_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertEqual(srv.HOST, "127.0.0.1")

    def test_health(self):
        status, ctype, body = self.call("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "application/json")
        self.assertEqual(json.loads(body), {"status": "ok", "model": "thorsten-kokoro"})

    def test_speech_returns_a_wav_with_pauses_between_sentences(self):
        status, ctype, body = self.post({"input": "Erster Satz. Zweiter Satz?", "voice": "thorsten", "response_format": "wav", "seed": 5})
        self.assertEqual((status, ctype), (200, "audio/wav"))
        with wave.open(io.BytesIO(body)) as w:
            self.assertEqual((w.getframerate(), w.getnchannels(), w.getsampwidth()), (24000, 1, 2))
            self.assertAlmostEqual(w.getnframes() / 24000, 0.2 + 0.30 + 0.2, places=3)
        self.assertEqual(self.engine.calls, ["Erster Satz.", "Zweiter Satz?"])

    def test_refused_requests_say_why_in_json(self):
        cases = [
            (self.post(b"{nope"), 400, "JSON"),
            (self.post({"voice": "thorsten"}), 400, "input"),
            (self.post({"input": "Hi.", "voice": "Ryan"}), 400, "thorsten"),
            (self.post({"input": "Hi.", "response_format": "mp3"}), 400, "wav"),
            (self.post({"input": "… !"}), 422, "nothing to say"),
            (self.post({"input": "Hi."}, content_type="text/plain"), 415, "JSON"),
            (self.call("GET", "/nope"), 404, "Nothing here"),
            (self.call("POST", "/v1/other", b"{}", {"Content-Type": "application/json"}), 404, "Nothing here"),
        ]
        for (status, ctype, body), want_status, want_text in cases:
            self.assertEqual(status, want_status, body)
            self.assertEqual(ctype, "application/json")
            self.assertIn(want_text, json.loads(body)["error"])
        self.assertEqual(self.engine.calls, [])  # no refused request reached the model

    def test_an_oversized_body_is_refused_before_it_is_read(self):
        reply = self.raw(b"POST /v1/audio/speech HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: 99999999\r\n\r\n")
        self.assertIn(b" 413 ", reply.split(b"\r\n")[0])

    def test_a_missing_content_length_is_refused(self):
        reply = self.raw(b"POST /v1/audio/speech HTTP/1.0\r\nContent-Type: application/json\r\n\r\n")
        self.assertIn(b" 411 ", reply.split(b"\r\n")[0])

    def test_a_model_failure_is_a_500_and_the_server_keeps_serving(self):
        status, _ctype, body = self.post({"input": "Das ist KAPUTT."})
        self.assertEqual(status, 500)
        self.assertIn("the model broke", json.loads(body)["error"])
        status, ctype, _body = self.post({"input": "Ein ganz normaler Satz."})
        self.assertEqual((status, ctype), (200, "audio/wav"))


class ServerFilesTests(unittest.TestCase):
    def test_requirements_are_pinned_exactly(self):
        lines = [l.strip() for l in (ROOT / "voice-de" / "requirements.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
        for line in lines:
            if line.startswith(("kokoro @", "misaki @")):
                self.assertRegex(line, r"@ git\+https://github\.com/semidark/(kokoro|misaki)\.git@[0-9a-f]{40}$", line)
            else:
                self.assertRegex(line, r"^[A-Za-z0-9_.\-]+==[0-9][^\s]*$", line)
        names = {l.split("==")[0].split(" @")[0].lower().replace("_", "-") for l in lines}
        self.assertLessEqual({"torch", "numpy", "soundfile", "kokoro", "misaki", "huggingface-hub", "espeakng-loader"}, names)

    def test_model_card_commit_of_misaki_is_the_pinned_one(self):
        text = (ROOT / "voice-de" / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("semidark/misaki.git@6d252a2e02f3b030f22f56686f1a73786c16ffc8", text)

    def test_big_and_private_files_are_ignored_by_git(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        for entry in ("voice-de/.venv/", "voice-de/model/"):
            self.assertIn(entry, ignored)

    def test_run_script_is_valid_bash_and_executable(self):
        script = ROOT / "voice-de" / "run.sh"
        self.assertTrue(script.stat().st_mode & 0o100, "run.sh is not executable")
        self.assertEqual(subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True).returncode, 0)

    def test_run_script_explains_its_usage_for_an_unknown_word(self):
        proc = subprocess.run([str(ROOT / "voice-de" / "run.sh"), "bogus"], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("start", proc.stdout)
        self.assertIn("stop", proc.stdout)
        self.assertIn("status", proc.stdout)


# --------------------------------------------------------------------------------------
# voice_take.py: speech goes to the language's engine, transcription stays on VoiceStudio
# --------------------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class BackendRoutingTests(unittest.TestCase):
    def urls_for(self, backend, action):
        seen = []

        def fake_urlopen(req, timeout=None):
            seen.append(req.full_url)
            if req.full_url.endswith("/v1/audio/speech"):
                return FakeResponse(b"x" * 200)
            return FakeResponse(json.dumps({"text": "hallo", "words": [{"word": "hallo", "start": 0.1, "end": 0.4}]}).encode())

        with tempfile.TemporaryDirectory() as raw, mock.patch.object(vt.urllib.request, "urlopen", side_effect=fake_urlopen):
            wav = Path(raw) / "a.wav"
            vt.write_wav(wav, tone(0.1))
            action(backend, wav)
        return seen

    def test_speech_goes_to_the_engine_and_transcription_stays_on_voicestudio(self):
        backend = vt.VoiceStudioBackend("http://127.0.0.1:3900", "thorsten", "asr", "de", engine_url="http://127.0.0.1:3910/",
                                        engine_start_hint="voice-de/run.sh start")
        seen = self.urls_for(backend, lambda b, wav: (b.synth("Hallo.", 1), b.transcribe_text(wav), b.transcribe_words(wav)))
        self.assertEqual(seen, ["http://127.0.0.1:3910/v1/audio/speech", "http://127.0.0.1:3900/v1/audio/transcriptions",
                                "http://127.0.0.1:3900/v1/audio/transcriptions"])

    def test_without_an_engine_everything_goes_to_voicestudio_as_before(self):
        backend = vt.VoiceStudioBackend("http://127.0.0.1:3900/", "Ryan", "asr", "en", "be warm")
        seen = self.urls_for(backend, lambda b, wav: (b.synth("Hello.", 1), b.transcribe_text(wav)))
        self.assertEqual(seen, ["http://127.0.0.1:3900/v1/audio/speech", "http://127.0.0.1:3900/v1/audio/transcriptions"])

    def test_the_request_to_the_engine_carries_voice_format_and_seed(self):
        backend = vt.VoiceStudioBackend("http://vs", "thorsten", "asr", "de", engine_url="http://engine")
        sent = {}

        def fake_request(path, data, content_type, timeout, what, **kw):
            sent.update(path=path, body=json.loads(data), kw=kw)
            return b"x" * 200

        with mock.patch.object(backend, "_request", side_effect=fake_request):
            backend.synth("Hallo.", 4)
        self.assertEqual(sent["body"], {"input": "Hallo.", "voice": "thorsten", "response_format": "wav", "seed": 4})
        self.assertEqual(sent["kw"]["engine"][1], "http://engine")

    def test_engine_down_says_how_to_start_it(self):
        backend = vt.VoiceStudioBackend("http://vs", "thorsten", "asr", "de", engine_url="http://127.0.0.1:3910",
                                        engine_start_hint="voice-de/run.sh start")
        with mock.patch.object(vt.time, "sleep"), mock.patch.object(vt.urllib.request, "urlopen", side_effect=urllib.error.URLError("refused")):
            with self.assertRaises(vt.VoiceTakeError) as caught:
                backend.synth("Hallo.", 1)
        message = str(caught.exception)
        self.assertIn("http://127.0.0.1:3910", message)
        self.assertIn("voice-de/run.sh start", message)
        self.assertNotIn("VoiceStudio", message)  # it is not VoiceStudio that is down

    def test_engine_error_answer_names_the_engine(self):
        backend = vt.VoiceStudioBackend("http://vs", "thorsten", "asr", "de", engine_url="http://127.0.0.1:3910")
        error = urllib.error.HTTPError("http://127.0.0.1:3910/v1/audio/speech", 400, "Bad", {}, io.BytesIO(b'{"error": "bad voice"}'))
        with mock.patch.object(vt.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(vt.VoiceTakeError) as caught:
                backend.synth("Hallo.", 1)
        self.assertIn("The voice engine at http://127.0.0.1:3910 refused", str(caught.exception))
        self.assertIn("bad voice", str(caught.exception))

    def test_voicestudio_down_message_is_unchanged(self):
        backend = vt.VoiceStudioBackend("http://127.0.0.1:9", "Ryan", "asr", "en")
        with mock.patch.object(vt.time, "sleep"), mock.patch.object(vt.urllib.request, "urlopen", side_effect=urllib.error.URLError("refused")):
            with self.assertRaises(vt.VoiceTakeError) as caught:
                backend.synth("hi", 1)
        self.assertIn("Is VoiceStudio still running? Start or restart it and run this again.", str(caught.exception))


# --------------------------------------------------------------------------------------
# voice_take.py: a deterministic engine gets ONE take
# --------------------------------------------------------------------------------------


class DeterministicTakeTests(TmpDirTest):
    def produce(self, fake, **kw):
        args = dict(backend=fake, grade=simple_grade, voice="thorsten", model="thorsten-kokoro", asr_model="asr1", ref_f0=150.0,
                    work_dir=self.tmp / "work", cache_root=self.tmp / "cache", start_seed=1, log=lambda m: None, deterministic=True)
        args.update(kw)
        return vt.produce_narration(LINES, **args)

    def test_a_good_script_is_one_take_with_one_request(self):
        fake = FakeVoice()
        take = self.produce(fake)
        self.assertEqual(take["seed"], 1)
        self.assertEqual(fake.synth_calls, [(FULL, 1)])
        self.assertEqual(take["attempts"], [{"seed": 1, "accepted": True, "reason": "steady"}])
        self.assertEqual(take["patches"], [])
        self.assertTrue(all(g["ok"] for g in take["lines"]))

    def test_a_failing_line_is_reported_not_re_rolled_and_not_patched(self):
        fake = FakeVoice(misheard={(1, 2)})
        with self.assertRaises(vt.VoiceTakeError) as caught:
            self.produce(fake)
        message = str(caught.exception)
        self.assertEqual(fake.synth_calls, [(FULL, 1)])  # no second seed, no single-line patch request
        self.assertEqual(len(caught.exception.attempts), 1)
        self.assertIn("identical", message)
        self.assertIn("ONCE", message)
        self.assertIn("Reword", message)
        self.assertIn("line 2", message)
        self.assertIn(LINES[2], message)
        self.assertIn("garbled nonsense words here", message)  # what was heard
        self.assertNotIn("line 1:", message)
        self.assertNotIn("--voice-seed", message)  # a new seed is not advice for this engine

    def test_every_failing_line_is_listed_even_when_there_are_more_than_the_patch_limit(self):
        bad = {(1, i) for i in range(4)}
        self.assertGreater(len(bad), vt.MAX_PATCH_LINES)
        with self.assertRaises(vt.VoiceTakeError) as caught:
            self.produce(FakeVoice(misheard=bad))
        for i in range(4):
            self.assertIn(f"line {i}:", str(caught.exception))
        self.assertIn("4 line(s)", str(caught.exception))

    def test_the_same_script_with_a_normal_engine_still_patches_the_line(self):
        fake = FakeVoice(misheard={(1, 2)})
        take = self.produce(fake, deterministic=False, model="m1", voice="Ryan")
        self.assertEqual([p["line"] for p in take["patches"]], [2])
        self.assertGreater(len(fake.synth_calls), 1)

    def test_an_unsteady_take_is_not_re_rolled_either(self):
        fake = FakeVoice(pitch=lambda seed, i: 150.0 * (2 ** (6 / 12) if i == 2 else 1))
        with self.assertRaises(vt.VoiceTakeError) as caught:
            self.produce(fake)
        self.assertEqual(len(fake.synth_calls), 1)
        self.assertIn("identical", str(caught.exception))
        self.assertIn("semitones", str(caught.exception))
        self.assertEqual(len(caught.exception.attempts), 1)

    def test_a_rejection_is_not_remembered_so_a_fixed_engine_gets_a_fresh_try(self):
        cache = self.tmp / "cache"
        with self.assertRaises(vt.VoiceTakeError):
            self.produce(FakeVoice(misheard={(1, 2)}))
        self.assertEqual(list(cache.glob("**/rejected.json")), [])
        fake = FakeVoice()  # the next run: the engine now says it right
        self.assertTrue(self.produce(fake)["lines"][2]["ok"])
        self.assertEqual(fake.synth_calls, [(FULL, 1)])

    def test_an_accepted_take_is_reused_without_any_request(self):
        self.produce(FakeVoice())
        fake = FakeVoice()
        again = self.produce(fake)
        self.assertEqual(fake.synth_calls, [])
        self.assertTrue(again["cache"]["hit"])

    def test_max_takes_cannot_make_a_deterministic_engine_try_again(self):
        fake = FakeVoice(misheard={(1, 2), (2, 2), (3, 2)})
        with self.assertRaises(vt.VoiceTakeError):
            self.produce(fake, max_takes=6)
        self.assertEqual(len(fake.synth_calls), 1)

    def test_failure_message_without_failing_lines_gives_the_reason(self):
        text = vt.deterministic_failure_message({"seed": 1, "accepted": False, "reason": "pitch jumps +6 semitones"}, [])
        self.assertIn("pitch jumps +6 semitones", text)
        self.assertIn("ONCE", text)


# --------------------------------------------------------------------------------------
# make_video.py: preflight messages and the voice step per language
# --------------------------------------------------------------------------------------

TTS_OK = {"active": "mlx-audio", "active_model": "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-6bit"}
TTS_WRONG = {"active": "omnivoice", "active_model": "omnivoice-x"}
ENGINE_URL = "http://127.0.0.1:3910"


class PreflightTests(TmpDirTest):
    def write_voices(self, de_extra=None, en_extra=None):
        voices = {"en": {"voice": "Ryan", **(en_extra or {})}, "de": {"voice": "thorsten", **(de_extra if de_extra is not None else {"engine_url": ENGINE_URL})}}
        path = self.tmp / "voices.json"
        path.write_text(json.dumps(voices), encoding="utf-8")
        return path

    def run_preflight(self, language, *, tts=TTS_OK, engine=None, voicestudio_down=False, voices=None):
        """-> (result or raised GateError, list of addresses asked, printed text, ctx)"""
        asked = []

        def fake_http_get_json(path, timeout=10):
            asked.append(path)
            if voicestudio_down:
                raise urllib.error.URLError("refused")
            return {"/health": {"status": "ok"}, "/engines/tts": tts, "/engines/asr": {"active": "faster-whisper"}}[path]

        def fake_engine_get_json(url, path, timeout=10):
            asked.append(url + path)
            if isinstance(engine, Exception):
                raise engine
            return engine if engine is not None else {"status": "ok", "model": "thorsten-kokoro"}

        ctx = mv.Ctx(mv.parse_args(["content/x/script.json"]))
        out = io.StringIO()
        with mock.patch.object(mv, "VOICES_FILE", voices or self.write_voices()), mock.patch.object(mv, "http_get_json", side_effect=fake_http_get_json), \
                mock.patch.object(mv, "engine_get_json", side_effect=fake_engine_get_json), contextlib.redirect_stdout(out):
            try:
                result = mv.preflight_voice_services(ctx, language)
            except mv.GateError as exc:
                result = exc
        return result, asked, out.getvalue(), ctx

    def test_german_with_its_own_engine_checks_the_engine_and_never_asks_for_the_voicestudio_tts_engine(self):
        result, asked, printed, ctx = self.run_preflight("de", tts=TTS_WRONG)  # VoiceStudio's TTS is "wrong", which must not matter
        self.assertEqual(result, {"tts": {"active": "thorsten-kokoro", "active_model": "thorsten-kokoro"}, "asr_model": "faster-whisper",
                                  "engine_url": ENGINE_URL})
        self.assertEqual(asked, ["/health", ENGINE_URL + "/health", "/engines/asr"])
        self.assertNotIn("/engines/tts", asked)
        self.assertEqual({c["name"]: c["ok"] for c in ctx.checks}, {"VoiceStudio": True, "voice engine": True})
        self.assertIn("thorsten-kokoro", printed)
        self.assertIn("transcription faster-whisper", printed)

    def test_english_still_requires_the_qwen_engine_in_voicestudio(self):
        result, asked, _printed, ctx = self.run_preflight("en", tts=TTS_WRONG)
        self.assertIsInstance(result, mv.GateError)
        self.assertIn("MLX-Audio + Qwen3-TTS CustomVoice", str(result))
        self.assertEqual(asked, ["/health", "/engines/tts"])

    def test_english_good_path_is_what_it_was(self):
        result, asked, printed, ctx = self.run_preflight("en")
        self.assertEqual(result["tts"], TTS_OK)
        self.assertEqual(result["asr_model"], "faster-whisper")
        self.assertIsNone(result["engine_url"])
        self.assertEqual(asked, ["/health", "/engines/tts", "/engines/asr"])
        self.assertEqual(ctx.checks[0]["detail"], f"healthy; TTS mlx-audio / {TTS_OK['active_model']}; transcription faster-whisper")
        self.assertEqual(len(ctx.checks), 1)

    def test_unreachable_engine_says_how_to_start_it(self):
        result, _asked, _printed, _ctx = self.run_preflight("de", engine=urllib.error.URLError("Connection refused"))
        self.assertIsInstance(result, mv.GateError)
        message = str(result)
        self.assertIn("start it: voice-de/run.sh start", message)
        self.assertIn(ENGINE_URL, message)
        self.assertIn("German", message)
        self.assertIn("Connection refused", message)

    def test_an_engine_that_does_not_say_ok_is_refused(self):
        for answer in ({"status": "loading"}, {"model": "x"}, ["ok"]):
            result, _asked, _printed, _ctx = self.run_preflight("de", engine=answer)
            self.assertIsInstance(result, mv.GateError, answer)
            self.assertIn("did not say ok", str(result))
            self.assertIn("voice-de/run.sh", str(result))

    def test_voicestudio_is_still_needed_for_german_because_it_transcribes(self):
        result, asked, _printed, _ctx = self.run_preflight("de", voicestudio_down=True)
        self.assertIsInstance(result, mv.GateError)
        self.assertIn("VoiceStudio", str(result))
        self.assertEqual(asked, ["/health"])  # stopped there; the engine was not even asked

    def test_a_language_without_engine_url_uses_voicestudio(self):
        voices = self.write_voices(de_extra={})
        result, asked, _printed, _ctx = self.run_preflight("de", voices=voices)
        self.assertIsNone(result["engine_url"])
        self.assertIn("/engines/tts", asked)

    def test_engine_urls_are_read_leniently(self):
        with mock.patch.object(mv, "VOICES_FILE", self.write_voices()):
            self.assertEqual(mv.configured_engine_url("de"), ENGINE_URL)
            self.assertIsNone(mv.configured_engine_url("en"))
            self.assertIsNone(mv.configured_engine_url("fr"))
        broken = self.tmp / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        with mock.patch.object(mv, "VOICES_FILE", broken):
            self.assertIsNone(mv.configured_engine_url("de"))
        with mock.patch.object(mv, "VOICES_FILE", self.tmp / "missing.json"):
            self.assertIsNone(mv.configured_engine_url("de"))

    def test_voice_engine_url_accepts_only_http_addresses(self):
        self.assertEqual(mv.voice_engine_url({"engine_url": " http://127.0.0.1:3910/ "}), "http://127.0.0.1:3910")
        for cfg in ({}, {"engine_url": ""}, {"engine_url": "127.0.0.1:3910"}, {"engine_url": 3910}, {"engine_url": None}, None, "x"):
            self.assertIsNone(mv.voice_engine_url(cfg), cfg)


class VoiceStepRoutingTests(TmpDirTest):
    def make_ctx(self, language, *argv):
        ctx = mv.Ctx(mv.parse_args(["content/x/script.json", *argv]))
        ctx.script = {"id": "x", "language": language, "lines": [{"text": t, "visual": None} for t in LINES]}
        ctx.work = self.tmp / "work" / "x"
        ctx.report["voice"] = {}
        return ctx

    def run_step(self, ctx, fake, setup):
        made = {}

        def factory(url, voice, asr_model, language, instructions="", **kw):
            made.update(url=url, voice=voice, asr=asr_model, language=language, instructions=instructions, kw=kw)
            return fake

        with mock.patch.object(mv.voice_take, "VoiceStudioBackend", side_effect=factory), mock.patch.object(mv, "WORK_ROOT", self.tmp / "work"), \
                mock.patch.object(mv, "find_tool", return_value="/bin/true"), contextlib.redirect_stdout(io.StringIO()) as out:
            try:
                take = mv.step_voice(ctx, setup)
            except mv.GateError as exc:
                take = exc
        return take, made, out.getvalue()

    def german_setup(self, **cfg):
        merged = {"voice": "thorsten", "engine_url": ENGINE_URL, "deterministic": True, "ref_f0_hz": 150.0, **cfg}
        return {"voice_cfg": merged, "ref_f0": 150.0, "asr_model": "asr1", "tts_model": "thorsten-kokoro", "engine_url": ENGINE_URL}

    def english_setup(self):
        cfg = {"voice": "Ryan", "instructions": "be warm", "ref_f0_hz": 150.0}
        return {"voice_cfg": cfg, "ref_f0": 150.0, "asr_model": "asr1", "tts_model": "m1"}

    def test_german_speaks_through_its_engine_with_one_take_and_no_probe(self):
        ctx = self.make_ctx("de")
        fake = FakeVoice()
        take, made, printed = self.run_step(ctx, fake, self.german_setup())
        self.assertNotIsInstance(take, Exception)
        self.assertEqual(made["kw"], {"ffmpeg": "/bin/true", "mpt_dir": mv.MPT_DIR, "engine_url": ENGINE_URL, "engine_start_hint": "voice-de/run.sh start"})
        self.assertEqual(made["url"], mv.VOICESTUDIO_URL)  # transcription is still VoiceStudio
        self.assertEqual(made["language"], "de")
        self.assertEqual(made["instructions"], "")
        self.assertEqual(fake.synth_calls, [(FULL, 1)])  # no instruction probe (3 extra requests), no re-roll
        self.assertFalse((self.tmp / "work" / "_voice_probe.json").exists())
        self.assertIn("ONE take", printed)
        voice = ctx.report["voice"]
        self.assertEqual((voice["mode"], voice["seed"], voice["instructions_ignored"]), ("one take", 1, True))
        self.assertTrue(json.dumps(ctx.report))

    def test_german_failing_line_becomes_a_plain_gate_error_with_the_heard_words(self):
        ctx = self.make_ctx("de")
        fake = FakeVoice(misheard={(1, 3)})
        error, _made, _printed = self.run_step(ctx, fake, self.german_setup())
        self.assertIsInstance(error, mv.GateError)
        self.assertIn("line 3", str(error))
        self.assertIn("garbled nonsense words here", str(error))
        self.assertEqual(len(fake.synth_calls), 1)
        self.assertFalse(any(c["ok"] for c in ctx.checks if c["name"] == "voice take"))

    def test_english_is_routed_exactly_as_before(self):
        ctx = self.make_ctx("en")
        fake = FakeVoice()
        take, made, _printed = self.run_step(ctx, fake, self.english_setup())
        self.assertNotIsInstance(take, Exception)
        self.assertEqual(made["kw"], {"ffmpeg": "/bin/true", "mpt_dir": mv.MPT_DIR})  # no engine_url, no engine_start_hint
        self.assertEqual(made["instructions"], "be warm")
        self.assertTrue((self.tmp / "work" / "_voice_probe.json").is_file())  # the instructions probe still runs
        self.assertGreater(len(fake.synth_calls), 1)

    def test_voice_seed_flag_is_said_to_change_nothing_for_a_deterministic_engine(self):
        ctx = self.make_ctx("de", "--voice-seed", "5")
        _take, _made, printed = self.run_step(ctx, FakeVoice(), self.german_setup())
        self.assertIn("--voice-seed changes nothing", printed)


class VoicesJsonTests(unittest.TestCase):
    def setUp(self):
        self.voices = json.loads((STUDIO_DIR / "voices.json").read_text(encoding="utf-8"))

    def test_german_uses_the_thorsten_engine(self):
        de = self.voices["de"]
        self.assertEqual(de["voice"], "thorsten")
        self.assertEqual(de["engine_url"], "http://127.0.0.1:3910")
        self.assertIs(de["deterministic"], True)
        self.assertIsInstance(de["ref_f0_hz"], float)
        self.assertTrue(80 <= de["ref_f0_hz"] <= 300)
        self.assertEqual(de["ref_sample"], "studio/voice-tests/de-thorsten.wav")
        self.assertEqual(mv.voice_engine_url(de), "http://127.0.0.1:3910")

    def test_english_is_untouched(self):
        en = self.voices["en"]
        self.assertEqual(en["voice"], "Ryan")
        self.assertNotIn("engine_url", en)
        self.assertNotIn("deterministic", en)
        self.assertEqual(en["ref_f0_hz"], 196.9)
        self.assertTrue(en["instructions"])


class VoiceAccuracyDetailTests(unittest.TestCase):
    """The 'voice accuracy' sentence must not claim 'inside their WER limit' for a line that passed on its letters alone."""

    def test_all_lines_inside_the_word_limit(self):
        lines = [{"index": 0, "wer": 0.0, "threshold": 0.15}, {"index": 1, "wer": 0.11, "threshold": 0.15}]
        text = mv.voice_accuracy_detail(lines)
        self.assertEqual(text, "all 2 lines pass the voice check (combined word/letter score; worst word error 0.11)")

    def test_close_call_is_named(self):
        lines = [{"index": 4, "wer": 0.31, "threshold": 0.15}, {"index": 5, "wer": 0.05, "threshold": 0.15}]
        text = mv.voice_accuracy_detail(lines)
        self.assertIn("worst word error 0.31", text)
        self.assertIn("line(s) 4 have more word errors than the word limit", text)
        self.assertIn("listen to them before upload", text)
        self.assertNotIn("inside their WER limit", text)

    def test_patched_lines_are_counted(self):
        text = mv.voice_accuracy_detail([{"index": 0, "wer": 0.0, "threshold": 0.15}], patched=2)
        self.assertTrue(text.endswith("; 2 line(s) patched"))


if __name__ == "__main__":
    unittest.main()
