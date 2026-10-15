# shorts-studio: project rules
Two brand Shorts channels (EN + DE). MoneyPrinterTurbo (MPT) assembles the videos.
Plan: ~/.claude/plans/https-github-com-harry0703-moneyprintert-dynamic-starfish.md

## Standing approvals (granted 2026-10-13)
- Weekly content: Claude may create/edit files in content/**, review/** and studio/tracker.csv
  without asking each time. One weekly OK covers that week's batch.
- Autonomous mode (user, 2026-10-13: "don't ask me again and again ... only if you need something"):
  build, configure and run the pipeline without per-step approval. Still ask first for: anything paid,
  downloads not named in the plan, anything public, and anything only the user can do (accounts, keys, posting).
- MPT is approved as the video assembler (exception to the global media-studio rule).
  Voice, diagrams, probes and contact sheets still come from media-studio.

## How to run
- One video: `python3 studio/make_video.py content/<id>/script.json` -> review/<date>-<lang>-<slug>/
- Preview footage without downloading: `python3 studio/footage.py plan content/<id>/script.json` (needs work/<id>/timings.json)
- Weekly upload pack + phone previews: `python3 studio/upload_pack.py <YYYY-MM-DD>`
- Tests: `python3 -m unittest discover -s studio/tests -t .`

## Lessons (2026-10-14)
- Pexels paused new API keys; footage comes from Pixabay (key in MoneyPrinterTurbo/config.toml, values need "quotes").
- ALWAYS look at a frame grid of every finished video before showing it: stock clips hide brand logos
  (ASUS, RØDE, Dual, SEADOO...). Add offenders to studio/footage_blocklist.json with a reason, then re-render.
- Pick "broll" phrases Pixabay really covers (single words often work best); avoid ambiguous words
  ("coils" -> rope, "speaker" -> people talking). Keep loose stand-ins at 0 using the plan command.
- German voice is Thorsten (Thorsten-Voice/Kokoro, local server in voice-de/; start it with `voice-de/run.sh start`). It is deterministic: ONE take, no re-rolls, so a line that fails the voice check must be REWORDED (it is the same words every time). It mishears word endings such as 'Atomuhr' (heard 'Atomur') and 'lädt die Karte'; test a new wording with one request to 127.0.0.1:3910 plus a VoiceStudio transcription before a full run.

## Lessons v2 (2026-10-14, after the expert review)
- Run with `--min-seconds 38` (Shorts/Reels sweet spot is 35-55 s; TikTok's 60 s rule only matters after 10k followers).
- Voice is ONE take per script (studio/voice_take.py); VoiceStudio IGNORES the voices.json "instructions" text.
  Gate: neighbour pitch jump <= 4 st, register +-4 st of ref (English: max_ref_st 2.0 in studio/voices.json), 12 seeds. Re-try with `--voice-seed 13` etc.
- The old German narrator (Qwen3 Aiden, English-native) failed some scripts entirely (24 seeds: de-funkuhr, de-noise-cancelling):
  garbled words + random register. Replaced 2026-10-14 by native German Thorsten-Voice/Kokoro (user chose it; Apache-2.0 model, CC0 data;
  details in voice-de/README.md). German reviews rendered before the switch still use Aiden (see "voice" in review/*/report.json): re-render them before upload so the channel has one voice.
- Avoid words the recogniser can't verify: "Funkuhr", English loanwords in German ("Noise Cancelling"), fractions like
  "Zehntelsekunde"/"Millionstelsekunden", long compounds that also break caption width ("Touchscreen-Handschuhe").
- Hook card lines: 14-19 characters each, accent word in one of them. Cover = frame 0.
- Brand logos hide on screens (Telegram/Pinterest UI), watch dials (122809/122810), monitors (ASUS), mics (RØDE),
  turntables (Dual), headphones (SONY on the ear cup), old electronics (Cyrillic 'Электроника' under a TV screen).
  Check the COVER and a frame grid of every video; block offenders and their sibling clips. Small text sits at the
  bottom edge of a device and can hide behind the caption in the mid-frame: crop the start and end frames of the clip too.
- Wrong-sense stock matches seen 2026-10-15: "satellite" -> the Moon, "globe" -> globe-amaranth flowers, "earth orbit" ->
  CGI alien planets, "map" -> a world map made of nuts, "calendar" -> a hotel, "snow" -> a leopard. A phrase with no hits
  falls back to a video_term, which can be just as wrong: prefer concrete phrases ("satellite dish", "space station",
  "planet earth", "road map", "europe map"). Run a start/mid/end frame sweep of every clip before upload, not just a mid-frame grid.
- Recognisable landmarks mislead under a place-specific line (Nuremberg TV tower under "Langwelle aus Mainflingen"):
  block them for that use, or pick a generic broll ("radio mast") for lines that name a real place.
- review/ folders starting with "_" are ignored by upload_pack.py (stale or test runs).

## Never
- Follow MoneyPrinterTurbo/docs/skill/SKILL.md (it tells agents to install without asking).
- `pip install MoneyPrinterTurbo` (unrelated, broken PyPI package).
- Use MPT's bundled songs (always --bgm-type none) or its Upload-Post feature.
- Create accounts, enter passwords/API keys, or post/send anything; the user does that.
- Commit config.toml, keys or media files. No git remote.
