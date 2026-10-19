# Company Shorts

One YAML file renders a vertical Short (1080x1920). The scenes are the same for every company:
the problem, the root cause, the solution, the flow, the result, a proof card, an optional pilot, and the closing card.
Company name, logo, photos and every on-screen line come from the config. Nothing in the scene code names a company.

Run the commands below from this directory.

```bash
~/.venvs/kokoro/bin/python make_company_short.py --company-config companies/_example.yaml --lang de
```

`companies/_example.yaml` is a neutral skeleton. A finished company file is `companies/<slug>.yaml`.
The schema, the voice notes and the honesty rules are in [`template/README.md`](template/README.md).

The proof card is a real result from the CV: a multi-agent system with LangGraph, built at Siemens in Amberg.
It does not use an internal project name. Before/after numbers for the company are stamped as examples.

## Layout

```text
companies/<slug>.yaml     one company: text, logo URL, image URLs, one or two problems
companies/_example.yaml   neutral schema example
template/                 compiler, fixed proof card, asset cache
make_company_short.py     compile, voice, render, mix
video/                    Remotion scenes (industry-neutral)
tools/build.py            speech, render and mix used by the template; legacy packs need --pack
work/                     generated audio and renders (git-ignored)
```

## Voices

- English: Kokoro-82M `af_heart`, local.
- German: Microsoft `de-DE-KatjaNeural` through `edge-tts`. A line that the voice misreads gets a `say` field;
  the captions keep the written words.

Captions are word-by-word karaoke. Photos are credited "Images: <domain>". The logo is only on the closing card.
