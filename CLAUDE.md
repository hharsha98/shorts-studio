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
- German voice (Qwen3 Aiden) swallows some endings in long sentences: reword lines that fail the voice check.

## Never
- Follow MoneyPrinterTurbo/docs/skill/SKILL.md (it tells agents to install without asking).
- `pip install MoneyPrinterTurbo` (unrelated, broken PyPI package).
- Use MPT's bundled songs (always --bgm-type none) or its Upload-Post feature.
- Create accounts, enter passwords/API keys, or post/send anything; the user does that.
- Commit config.toml, keys or media files. No git remote.
