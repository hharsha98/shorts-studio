# Company Shorts template

One YAML file per company. The scenes (problem, root cause, solution, flow, result, proof card,
optional pilot, closing card) are filled from that file. A new company does not need a code change.

Run these from the project directory with the voice environment (`bash tools/setup.sh` once).

## 1. Draft a config from a job advert

```bash
~/.venvs/kokoro/bin/python prepare_company.py "https://example.com/jobs/123" \
  --company-site https://example.com
```

This fetches the advert and the site, downloads the logo and up to six images (cached, so a second run
does not download them again) and writes `companies/<slug>.yaml` plus `<slug>.research.txt` with the
advert text. If `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` is set, one short call fills the story.
Otherwise the story is left as TODOs for you to fill. Do not mention the job posting in the script.

## 2. Fill the YAML

See the schema below, and `companies/_example.yaml` for a finished neutral example.

## 3. Render

```bash
~/.venvs/kokoro/bin/python make_company_short.py \
  --company-config companies/_example.yaml --lang de
```

`--lang en` uses Kokoro `af_heart`. `--lang de` uses Microsoft Katja at her normal pace.
A config with two problems renders two videos; add `--problem <slug>` to render one.
Nothing is re-voiced or re-rendered when the config is unchanged: spoken lines are cached one by one,
images are cached by URL, and the whole video is skipped when its props have not changed.

## What every video contains

- Problem, root cause (a cost chart), solution, flow, illustrative before/after result,
  the Siemens proof card, an optional pilot, and the closing card.
- Closing card: the company logo, "An idea for <Company>" / "Eine Idee für <Company>",
  "Concept by Hanumanthu Harsha Vardhan", and a line that it is a concept, not an official project.
- Photos credited "Images: <domain>" / "Bilder: <domain>". A photo that cannot be fetched is dropped
  and the scene uses the drawn graphic instead. The log says so.
- Before/after numbers are stamped ILLUSTRATIVE / BEISPIELWERTE. The Siemens proof numbers are fixed in
  `template/copy.py` and cannot be edited from the config.
- No "AI idea sketch" label, and the compiler rejects the words "job posting" and "Stellenanzeige".

## Config schema

```yaml
version: 1
company:
  slug: acme            # file and cache name
  name: Acme GmbH       # used in "An idea for Acme GmbH"
  domain: acme.example  # used in the photo credit
  logo_url: https://acme.example/logo.svg   # or local:companies/logos/acme.svg
  logo_plate: light     # optional white chip, for a dark wordmark on the dark closing card
  images:               # named URLs, referenced by the problem
    hook: https://acme.example/hero.jpg
    pain: https://acme.example/line.jpg

problems:               # 1 or 2; each becomes its own 60–70 s video
  - slug: document-checks
    title: {en: Document checks, de: Dokumentenprüfung}
    hook:                 # the problem
      icon: order       # order (checklist), alert, knowledge or machine
      image: hook       # key from company.images
      sub: {en: "...", de: "..."}
      en: [["Catch ", {text: "missing fields", accent: true}], ["before they ship"]]
      de: [["Lücken finden"], ["bevor sie teuer werden"]]
    pain:                 # the root cause
      image: pain
      title: {en: "...", de: "..."}
      chips: {en: [A, B, C], de: [A, B, C]}          # exactly 3
      columns: {en: [Desk, Line, Customer], de: [Schreibtisch, Linie, Kunde]}
    idea:                 # the solution
      icon: agent
      title: {en: "...", de: "..."}
      sub: {en: "...", de: "..."}
    steps:                # the flow. 3 to 5 nodes. id is what narration cues refer to (arch.<id>)
      - {id: inputs, icon: inbox, title: {en: Incoming, de: Eingang}, sub: {en: "...", de: "..."}}
      - {id: agent, icon: agent, link: both, title: {en: AI agent, de: KI-Agent}, sub: {en: "...", de: "..."}}
      - {id: out, icon: factory, title: {en: Result, de: Ergebnis}, sub: {en: "...", de: "..."}}
    before_after:         # the result. 1 or 2 rows, always labelled as examples
      - {label: {en: Minutes, de: Minuten}, before: 20, after: 5, unit: {en: min, de: "Min."}}
    pilot:                # optional, exactly the three checklist lines if present
      en: ["One team", "Read-only", "Measured with them"]
      de: ["Ein Team", "Nur lesend", "Gemeinsam messen"]
    narration:
      en:
        - {scene: hook, text: "...."}
        - {scene: pain, text: "....", cues: {pain.chips: word, pain.0: word}}
        - {scene: idea, text: "One idea: ...."}
        - {scene: arch, text: "....", cues: {arch.inputs: word}}
        - {scene: metrics, text: "Illustrative targets: ...."}
        # proof and closing are added if you leave them out
      de:
        - {scene: hook, text: "...."}
```

A `say` field on a narration line is what the voice speaks when it would misread the written `text`
(for example German "E-R-P" while the caption stays "ERP"). `cues` name the word that reveals each
diagram part. Icons: inbox, agent, db, shield, factory, book, search, chat, alert, usercheck, loop.
