# Rotpunkt Küchen: worked example

Three vertical Shorts (1080x1920, 30 fps), each in **English** and **German**. This folder is a worked example of the
template, not an official Rotpunkt Küchen project. Each Short takes one problem that the company's public job postings
and press point to, and sketches an AI solution for it.

Everything about Rotpunkt below comes from public job postings and press. The solutions are **ideas**, not known Rotpunkt projects.
All before/after numbers for Rotpunkt are **illustrative** and labelled so on screen; the only real numbers are the author's, from his CV.
Each Short shows **real Rotpunkt kitchens** (product photos from rotpunkt.de, credited on every photo) inside its scenes, and every
video has **word-by-word karaoke captions** synced to the voice.

**v2 (19 Oct 2026), the version to show.** Narration stays at a natural pace and each finished card holds long enough to read
(about 60–75 s). The "AI idea sketch" corner label is gone. Short 2 is no longer a generic machine story: a front comes back and
the cause is traced to edge banding, the panel cut or the surface, with the Siemens multi-agent system shown only as proof of the pattern. Short 3 no longer
says the idea came from their job postings. Every video ends on their public logo with "An idea for Rotpunkt Küchen" and
"Concept by Hanumanthu Harsha Vardhan", and says it is a concept, not an official project.

## 1. Deliverables

The six voiced films, and a silent cut of each, are not stored in git.

| File | What |
|---|---|
| `rotpunkt_short_1_en_v2.mp4`, `rotpunkt_short_1_de_v2.mp4` | Order checks. Readable pace, no "AI idea sketch" label |
| `rotpunkt_short_2_en_v2.mp4`, `rotpunkt_short_2_de_v2.mp4` | A kitchen-front complaint traced back to edge banding, the panel cut or the finish |
| `rotpunkt_short_3_en_v2.mp4`, `rotpunkt_short_3_de_v2.mp4` | Specialist know-how, told as a concept in generic industry terms (no job-posting quotes) |
| `rotpunkt_short_N_{en,de}_v2_silent.mp4` | the same six without an audio track |

v2 is the reviewed cut. Do not replace those files with a casual re-render.

Source code: `rotpunkt-shorts/` in the repository (Remotion project, build tool, scripts, research snapshot). Rebuild: see `README.md`.

## 2. Sources: every posting used

Fetched 18 Oct 2026, 21:55–22:05 UTC. The professional roles come from the **job widget embedded on the careers page**
(rotpunktkuechen.de/karriere/fachkraefte, Connectoor widget `6a7af22645b909b7b58b4e76`), which is the company's own, complete list
at that moment (8 hits). Dates are the widget's creation dates unless a mirror is named. A full snapshot with all quotes is in
`research/postings.json`.

| # | Posting | Site | Date | URL |
|---|---|---|---|---|
| 1 | Datenmanager IDM (m/w/d) | Bünde | 12.10.2026 | https://app.connectoor.de/jobview?jobid=6acce3be45b90924b38b73d1 |
| 2 | IT-Applikationsmanager (Produktionssysteme) (m/w/d) | Bünde | 31.08.2026 (ZipRecruiter: 03.10.2026) | https://app.connectoor.de/jobview?jobid=6a955fdb45b90999418bbee6 · https://www.ziprecruiter.de/jobs/615827602-it-applikationsmanager-produktionssysteme-m-w-d-bei-rotpunkt-kuechen |
| 3 | Teamleiter Produktion (m/w/d) | Bünde | 20.08.2026 | https://app.connectoor.de/jobview?jobid=6a86b81945b909b22d8b79cc |
| 4 | Verlader (m/w/d) | Bünde | 20.08.2026 | https://app.connectoor.de/jobview?jobid=6a86c4c045b909727e8b9266 |
| 5 | Maschinenbediener (m/w/d) | Bünde | 18.08.2026 | https://app.connectoor.de/jobview?jobid=6a84589245b909f8448b8c7d |
| 6 | Sachbearbeiter in der Kundenbetreuung (m/w/d) | Bünde | 11.08.2026 (ZipRecruiter: 24.09.2026) | https://app.connectoor.de/jobview?jobid=6a7aff1b45b90929ff8b54bc · https://www.ziprecruiter.de/jobs/606641169-sachbearbeiter-in-der-kundenbetreuung-m-w-d-bei-rotpunkt-kuechen |
| 7 | Materialdisponent (m/w/d) | Bünde | 11.08.2026 | https://app.connectoor.de/jobview?jobid=6a7afe5645b909ea958b49ba |
| 8 | Elektriker/ Elektroniker am Standort Getmold (m/w/d) | Preußisch Oldendorf | 11.08.2026 | https://app.connectoor.de/jobview?jobid=6a7afcbd45b909727e8b6c7e |
| 9 | AI Solution Engineer (m/w/d) (public posting; not in the widget list at fetch time) | Bünde | Indeed: 20.09.2026 | https://app.connectoor.de/jobview?jobid=6aaf8faf45b90998048b79fe · https://de.indeed.com/viewjob?jk=54b6a3713d326641 |
| 10 | Ausbildung zum Industriekaufmann (m/w/d), start 01.08.2027 | Bünde | ZipRecruiter: 08.10.2026 | https://www.ziprecruiter.de/jobs/619824806-ausbildung-zum-industriekaufmann-m-w-d-bei-rotpunkt-kuechen |
| 11 | Ausbildung Elektroniker für Betriebstechnik (m/w/d), start 01.08.2027 | Bünde | ZipRecruiter: 08.10.2026 | https://www.ziprecruiter.de/jobs/619824810-ausbildung-elektroniker-fuer-betriebstechnik-m-w-d-bei-rotpunkt-kuechen |
| 12 | Ausbildung Holzmechaniker (m/w/d), start 01.08.2027 | Bünde | careers page | https://www.rotpunktkuechen.de/karriere/ausbildung |

Checked and **no further postings found**: Indeed company page (https://de.indeed.com/cmp/Rotpunkt-K%C3%BCchen/jobs, "keine offenen
Stellen"), XING company page (https://www.xing.com/pages/rotpunkt-kuechen-gmbh, "no vacancies"). **Not verifiable** from here:
LinkedIn company jobs (login wall, 404 for an anonymous fetch) and StepStone (server error 500). stellenangebote.info timed out; its
search snippet lists 6 positions including the three apprenticeships.

Press used for context: about €50 m invested since late 2023 in a logistics hub, the machine park and "die Digitalisierung aller
Unternehmensbereiche" ([möbelfertigung](https://www.moebelfertigung.com/news/rekordumsatz-trotz-schwieriger-marktlage)); "interne
Abläufe neu geordnet … Davon profitiert der Fachhandel direkt. In der Auftragsabwicklung" and a collection built on "Variantenreichtum"
([möbelfertigung](https://www.moebelfertigung.com/news/kollektion-2026-wird-zum-baukasten-fuer-zukunftsfaehigkeit)); "mehr Lkw neue
Maschinen bei uns anliefern, als Küchen das Werk verlassen" ([HK-Magazin](https://hk-magazin.com/allgemein/rotpunkt-kuechen-starke-entwicklung-im-ersten-quartal/)).

## 3. What the postings say together

Read side by side, the 12 postings point to five recurring problems. Quotes are verbatim from the postings.

| Theme | Postings | Evidence | Fit with work already done | Chosen |
|---|---|---|---|---|
| **A. Order intake and order/product data** (dealer orders with many variants, export, data exchange between systems, catalogue data for the sales process) | 6, 2, 1, 9; press | „prüfst Kundenbestellungen auf technische Umsetzbarkeit“, „insbesondere aus den Exportmärkten per Telefon und E-Mail“, „mind. 3 Jahre … Ausarbeitung von Küchenmöbelbestellungen“ (6); „Varianten, Maße, Positionierungen und Abhängigkeiten“, „Auftrags-, Produkt- und Produktionsdaten zuverlässig … ausgetauscht“, „EDI-Prozesse, Schnittstellen“ (2); „IDM Daten in mehreren Sprachvarianten“, „Digitalisierung des Sales Prozess“ (1); press: Auftragsabwicklung, Variantenreichtum, ~80 % export | High: LLM extraction + RAG over rules and documents + validation, integrated by REST API (the same multi-agent pattern) | **Short 1** |
| **B. Keeping production systems, interfaces and machines running** | 2, 5, 8, 3, 11; press | „gehst den Ursachen auf den Grund, wenn irgendwo etwas hakt“, „analysierst technische Probleme“, „Rückmeldungen und Workflows zwischen Maschinen und unseren Systemen“ (2); „analysierst, behebst und dokumentierst Funktionsstörungen an Maschinen“ (5); „hohe Verfügbarkeit unserer Produktionsanlagen“, „Wartungsarbeiten gemäß Wartungsplan“ (8); press: new machines arriving | Highest: exactly that multi-agent system with LangGraph (root cause analysis with LLM agents over manuals, error texts and logs, in production at Siemens Amberg) | **Short 2** |
| **C. Specialist know-how that is hard to hire and slow to teach** (skills gap) | 6, 1, 2, 5, 7, 3, 10–12 | „mind. 3 Jahre“ (6); „Berufserfahrung in der Erstellung von IDM-Daten“, Furnidata (1); „Berufserfahrung in der Möbel- oder Küchenindustrie“, COE/GOE, MOS, Insight2020 „ein Plus“ (2); edge banders, panel saws, CNC (5); „Mehrjährige Berufserfahrung in der Möbelbranche“ (7); „schulst die Prozesse“ (3); three apprenticeships and an own training workshop | High: local RAG with source citations and faithfulness metrics (FAU research, published), on-prem, access control | **Short 3** |
| D. Logistics and material flow | 4, 7, 3; press (logistics hub) | „Vollständigkeit der Auflieger durch Scannen“ (4); „teilweise JIT“, „Lieferengpässe“, „Kennzahlen“ (7); „Logistikaufträge im ERP-System“, „Materialfluss“ (3) | Medium: possible, but nothing in the author's experience is planning or forecasting, so it would be a weaker, less honest pitch | not chosen |
| E. A mixed system landscape under digitalisation | 2, 3, 7, 1, 9; press (€50 m incl. IT) | ERP „vorzugsweise Cyncly Insight“ (3), „Microsoft Navision“ (7), „VBA, VBScript und Microsoft SQL“, AutoCAD (2), Furnidata (1) | Cross-cutting: every Short integrates read-only first, through APIs, with local models | built into all three |

System names found in the postings (deliberately **not** shown in the videos, because they are
third-party products): Cyncly Insight / Insight2020, COE/GOE, MOS, Microsoft Navision, Furnidata (IDM), VBA/VBScript/MS SQL, AutoCAD,
IMA/Homag edge banders and CNC, Schelling panel saws.

## 4. The three problems chosen, and why

1. **Order checks (Short 1).** The strongest business case: an order error costs little at the desk and a lot once it is in production (the
   general "rule of ten" of quality costs). Four postings and the press point to it, it sits in the order and product data flows, and it uses the exact
   building blocks of that multi-agent system (LLM agents, retrieval, validation, REST integration).
2. **Root cause analysis (Short 2).** The closest match to work already done: that system cut root cause analysis at Siemens Amberg from 30–120 to 8–15
   minutes per fault on 16 SMT machines. The IT posting even asks for someone who "geht den Ursachen auf den Grund, wenn irgendwo etwas hakt".
3. **Know-how on demand (Short 3).** The most cross-cutting problem: almost every posting asks for rare, multi-year experience. It speaks to
   HR as well as IT, and it rests on published FAU research (local RAG, 0.97 faithfulness).

Logistics (theme D) was left out on purpose: it is a real topic, but nothing in the author's experience backs it, and the Shorts should only claim work he has done.

## 5. Voices, music and the honesty rules

- **English voice: Kokoro-82M "af_heart"** (Apache-2.0), the pipeline's English narrator (the user's choice in this repo, 2026-10-15). The
  repo's own server runs it on Apple MLX, which this Linux machine does not have, so the same model and voice ran through Kokoro's reference
  PyTorch package (`kokoro` 0.9.4, model `hexgrad/Kokoro-82M`), locally and free. It returns a time for every word, so captions are exact.
- **German voice: Microsoft "de-DE-KatjaNeural"**, through the free Edge read-aloud service (`edge-tts`, no key). Why: it is one of the two
  standard, widely used German neural voices (with Conrad), studio-recorded by a native speaker; it keeps one female narrator across both
  languages; and when all German lines were voiced with both and transcribed with Whisper, Katja's "KI" came back as "KI" in every line,
  while **Conrad's came back as "Kaj" twice ("Kajassistent", "Kajagenten")**, which would jar in an AI pitch. In v2 she speaks at her own pace; the earlier 7 % speed-up is gone, and each finished card holds so it can be read. "EDI" and "ERP" are
  spoken from the spelled forms "E-D-I" and "E-R-P" (she otherwise reads them as words), and the one "KI-Agent" in Short 1 from "K-I-Agent"
  (she otherwise says "Kai-Agent"); the captions keep the written forms. The pipeline's
  German voice (Thorsten) was not available on this machine. The Edge read-aloud service needs no key; for a published
  film, use the same voice through Azure Speech (paid) or switch to Thorsten.
- **Music:** a quiet pad composed for these videos by the build script (no licence needed), about 18 dB under the voice and ducked further
  while she speaks; final mix −16 LUFS. The silent versions have no audio track at all.
- **Captions:** word-by-word karaoke style in every EN and DE video. The current phrase (1–2 lines, broken at natural points) sits in a
  dark panel; an amber pill slides onto each word exactly when the voice says it (word times come from the speech engines: Kokoro's
  token timestamps for EN, Edge's word boundaries for DE) and the word pops slightly as it lands; spoken words turn white, coming words wait
  dimmed. Spelled-out spoken forms (E-D-I, E-R-P) still show as EDI / ERP.
- **Product photos (real Rotpunkt kitchens):** six photos from the company's public website, shown inside the scenes and credited small on
  every photo as "Images: rotpunkt.de" (German videos: "Bilder: rotpunkt.de"). rotpunkt.de redirects to www.rotpunktkuechen.de, where the
  photos are published. Every photo was fetched successfully, so no generic stand-in was needed. Each was checked by eye for logos,
  watermarks or text (none). The public logo (the red dot and the white wordmark, from rotpunktkuechen.de) appears only on the closing card, under the line
"An idea for Rotpunkt Küchen" / "Eine Idee für Rotpunkt Küchen" and above "Concept by Hanumanthu Harsha Vardhan", with the note
"A concept, not an official Rotpunkt project". It is not used as a watermark and the videos do not present themselves as official. The photos remain the
  company's property: they are downloaded at build time into a git-ignored folder and are not committed.
  Ask before publishing a film that uses them. Sources and placement: `research/images.json`.

  | Short | Scene | Photo (source URL on rotpunktkuechen.de) | What is drawn over it |
  |---|---|---|---|
  | 1 | cover | [wood island with steel hood](https://www.rotpunktkuechen.de/fileadmin/_processed_/8/4/csm_01-zerox-sy-ver-loft-brown-oak_gallery__1400x875_31bc567624.webp) | a dealer order sheet with one flagged line; a magnifier with "!" on the island |
  | 1 | the problem | [island and tall units with oven niche](https://www.rotpunktkuechen.de/fileadmin/40_Inspiration/Minisammlung-Startseite/Rotpunkt_MK07_Hauptschuss__1200.jpg) | callouts: *Variants* on the fronts, *Dimensions* along the island, *Dependencies* at the oven niche |
| 1 | the idea | [grey and oak kitchen](https://www.rotpunktkuechen.de/fileadmin/_processed_/6/e/csm_MK_02_Memory_RI_Beach_Grey_Zerox_SY_VER_Scandinavian_Oak2__header__1200_460dc71601.webp) | the order-check assistant |
| 2 | cover | [dark-oak kitchen with island](https://www.rotpunktkuechen.de/fileadmin/_processed_/5/5/csm_MK_11_Zerox_SY_VER_Loft_Dark_Oak__header__1200_94c6bedc92.webp) | a complaint card, "Edge chipped", over the photo (the photo itself shows no defect) |
| 2 | the problem | [front detail, glass and wood](https://www.rotpunktkuechen.de/fileadmin/40_Inspiration/Minisammlung-Startseite/Rotpunkt_MK10_Detail2_Glasfronten_Fronten__1200.jpg) | "Front came back", with batch records, machine logs, old complaints and people around it |
| 2 | the idea | [tall units and island](https://www.rotpunktkuechen.de/fileadmin/40_Inspiration/Minisammlung-Startseite/Rotpunkt_MK10_Hauptschuss__1200.jpg) | "Trace it back to the line" |
  | 3 | cover | [white and wood kitchen with glass cabinets](https://www.rotpunktkuechen.de/fileadmin/40_Inspiration/Minisammlung-Startseite/Rotpunkt_MK09_Hauptschuss__1200.jpg) | a question bubble and an answer card with its source |
  | 3 | the idea | [white kitchen with wood island](https://www.rotpunktkuechen.de/fileadmin/_processed_/1/4/csm_Rotpunkt_HM01_Hauptschuss_Final__1200_7ec0652391.webp) | the knowledge assistant's chat badge |
- **Honesty rules applied:** illustrative numbers carry an ILLUSTRATIVE / BEISPIELWERTE stamp, a footnote "Example values, not your company's
  data. To be measured in a pilot." and are called illustrative in the narration; real numbers appear only in "REAL RESULT" cards with
  "Source: candidate's CV"; the rule of ten is labelled a general principle. Short 2 says the front complaint is a scenario, not a known
  defect. The logo appears only on the closing card, which says "An idea for Rotpunkt Küchen", "Concept by Hanumanthu Harsha Vardhan" and
  "A concept, not an official Rotpunkt project", and the voice is labelled. The narration never says the author works there.
  Third-party product names from the postings stay out of the videos. Short 1 still quotes three lines from the customer-service
  posting; Shorts 2 and 3 do not quote postings.

## 6. Short 1 — Order checks ("Catch order errors before production")

- **Problem:** experienced staff check every dealer order (often from export markets, by phone and e-mail) for technical feasibility; with
  many variants, dimensions and dependencies, one missed detail means rework, and the later it is found the more it costs.
- **Idea:** an order check assistant. An AI agent reads each order (EDI, PDF, e-mail, any language) and extracts the lines; it checks them
  against the company's own product rules and catalogue/master data (RAG); fixed rule checks flag each conflict with its source; a clerk
  decides; only approved orders reach the ERP. Local LLM, read-only first, GDPR in mind.
- **Built before (real):** A multi-agent system with LangGraph at Siemens Amberg (M.Sc. thesis, in production): 12 LLM agents, retrieval over manuals and logs in under
  200 ms, on-prem LLMs for data protection, about 78 % of suggestions accepted at first review.
- **Illustrative pilot targets:** checking time per order 20 → 5 min; errors found only in production, index 100 → 25.
- **Pilot:** one product line, read-only next to the team, success measured with the department.

<!-- AUTO:short1:scenes -->
| # | Scene | EN | DE | On screen (EN labels; DE uses the German labels) |
|---|---|---|---|---|
| 1 | Hook (cover, frame 0) | 0:00.0–0:04.3 | 0:00.0–0:05.0 | Catch order errors / before production — An AI idea based on your current job postings — **product photo** `s1-hook.webp` (Images: rotpunkt.de) |
| 2 | Evidence: quotes from the postings | 0:04.3–0:12.5 | 0:05.0–0:13.1 | Sachbearbeiter in der Kundenbetreuung: „Berufserfahrung (mind. 3 Jahre) in der Ausarbeitung von Küchenmöbelbestellungen“; Sachbearbeiter in der Kundenbetreuung: „…du prüfst Kundenbestellungen auf technische Umsetzbarkeit“; Sachbearbeiter in der Kundenbetreuung: „…insbesondere aus den Exportmärkten per Telefon und E-Mail“ |
| 3 | The problem | 0:12.5–0:18.0 | 0:13.1–0:19.9 | The later an error is found, the more it costs: Desk check ×1 · Production ×10 · At the customer ×100 — **product photo** `s1-pain.jpg` (Images: rotpunkt.de) |
| 4 | The idea | 0:18.0–0:21.2 | 0:19.9–0:24.4 | One idea: An order check assistant (AI agent + your product rules + human approval) — **product photo** `s1-idea.webp` (Images: rotpunkt.de) |
| 5 | Architecture, built step by step | 0:21.2–0:39.8 | 0:24.4–0:46.8 | Incoming order → AI agent (LLM) → Your product rules (RAG) → Rule checks + clerk → ERP → production; badges: Local LLM · Read-only first · GDPR in mind · Human decides |
| 6 | Pilot targets (stamped ILLUSTRATIVE) | 0:39.8–0:48.0 | 0:46.8–0:55.1 | [ILLUSTRATIVE] Checking time per order: 20 → 5 min; Errors found only in production (index): 100 → 25 — Example values, not your company's data. To be measured in a pilot. |
| 7 | Built before (REAL RESULT, from the CV) | 0:48.0–0:53.3 | 0:55.1–1:00.8 | [REAL RESULT] Multi-agent system with LangGraph · Siemens Amberg: 12 LLM agents working together; < 200 ms retrieval over manuals and logs; On-prem LLMs, for data protection; ~78 % of suggestions accepted at first review — Source: candidate's CV |
| 8 | A first pilot | 0:53.3–0:56.0 | 1:00.8–1:04.2 | A first pilot: One product line · Read-only, next to the team · Success measured with the department |
| 9 | Closing card | 0:56.0–1:02.1 | 1:04.2–1:10.3 | Hanumanthu Harsha Vardhan — Concept by — github.com/hharsha98 (A concept, not an official Rotpunkt project · illustrative numbers · AI voice) |

Length: **EN 62.1 s**, **DE 70.3 s** (narration plus a 4.6 s hold on the closing card).
<!-- /AUTO -->

**English narration**

<!-- AUTO:short1:en -->
1. `0:00.2–0:03.7` *(hook)* Order errors are cheap at the desk, and expensive in production.
2. `0:04.3–0:10.8` *(evidence)* Your postings show who catches them today: experienced staff checking every dealer order, often for export.
3. `0:12.5–0:16.6` *(pain)* Variants, dimensions, dependencies: one missed detail means rework.
4. `0:18.0–0:20.2` *(idea)* One idea: an order check assistant.
5. `0:21.2–0:25.4` *(arch)* It reads each order, from EDI, PDF or email, in any language.
6. `0:25.7–0:30.0` *(arch)* An AI agent extracts the lines and checks them against your product rules.
7. `0:30.3–0:33.0` *(arch)* Conflicts come with their source, and a clerk decides.
8. `0:33.4–0:38.2` *(arch)* Only approved orders reach the ERP, with local models and GDPR in mind.
9. `0:39.8–0:46.4` *(metrics)* Illustrative pilot targets: checking time from twenty minutes to five, and far fewer errors found in production.
10. `0:48.0–0:51.7` *(proof)* The same building blocks already run in production at Siemens Amberg.
11. `0:53.3–0:55.5` *(pilot)* A pilot could start with one product line.
12. `0:56.0–0:57.5` *(closing)* Happy to explore it with you.

130 words, 57.5 s of narration. Voice: `kokoro:af_heart`.
<!-- /AUTO -->

**German narration (Deutsch)**

<!-- AUTO:short1:de -->
1. `0:00.2–0:04.4` *(hook)* Ein Bestellfehler kostet am Schreibtisch wenig, in der Fertigung viel.
2. `0:05.0–0:11.4` *(evidence)* Ihre Stellenanzeigen zeigen: Erfahrene Fachleute prüfen jede Händlerbestellung, oft für den Export.
3. `0:13.1–0:18.5` *(pain)* Varianten, Maße, Abhängigkeiten: Ein übersehenes Detail heißt Nacharbeit.
4. `0:19.9–0:23.4` *(idea)* Eine Idee: ein KI-Assistent für die Auftragsprüfung.
5. `0:24.4–0:29.8` *(arch)* Er liest jede Bestellung, per EDI, als PDF oder E-Mail, in jeder Sprache.
6. `0:30.2–0:34.7` *(arch)* Ein KI-Agent erfasst die Positionen und prüft sie gegen Ihre Produktregeln.
7. `0:35.0–0:39.0` *(arch)* Konflikte werden mit Quelle markiert, die Entscheidung trifft der Mensch.
8. `0:39.3–0:45.2` *(arch)* Nur freigegebene Aufträge gehen ins ERP, mit lokalen Modellen und der DSGVO im Blick.
9. `0:46.8–0:53.6` *(metrics)* Beispielhafte Pilotziele: Prüfzeit von zwanzig auf fünf Minuten, deutlich weniger Fehler in der Fertigung.
10. `0:55.1–0:59.2` *(proof)* Die gleichen Bausteine laufen bereits produktiv bei Siemens in Amberg.
11. `1:00.8–1:03.6` *(pilot)* Ein Pilot könnte mit einer Produktlinie starten.
12. `1:04.2–1:05.7` *(closing)* Mehr dazu gern im Gespräch.

121 words, 65.7 s of narration. Voice: `edge:de-DE-KatjaNeural@+0%`.
<!-- /AUTO -->

## 7. Short 2 — A front comes back ("Find the cause")

Reworked for v2. The story is about their kitchens, not a generic machine fault. Nothing in it claims Rotpunkt has this defect: the cards
say "A scenario, not a known defect".

- **Problem:** a kitchen front comes back and the customer is waiting. The cause could be the edge banding, the panel cut or the surface
  finish, and the trail runs through batch records, machine logs, old complaints and a few experienced people.
- **Idea:** trace that one complaint back to the line. The assistant reads the complaint and the photos, searches past cases and work
  instructions, and AI agents rank the likely causes with the evidence. The quality team confirms, and the fix is saved for the next batch.
- **Built before (real):** the same pattern, a multi-agent system with LangGraph at Siemens Amberg, on an electronics line: 30–120 → 8–15 min per fault, 16 machines,
  12 LLM agents, 82.2 % root-cause hits on 1,811 historical error codes. The card says this is a real result there, not a Rotpunkt figure.
- **Illustrative pilot targets:** days to trace one front complaint 5 → 1; repeat defects that still ship, index 100 → 40.
- **Pilot:** one front family, complaints and batch data read-only, measured with quality and production.

<!-- AUTO:short2:scenes -->
| # | Scene | EN | DE | On screen (EN labels; DE uses the German labels) |
|---|---|---|---|---|
| 1 | Hook (cover, frame 0) | 0:00.0–0:03.7 | 0:00.0–0:04.0 | A front comes back / Find the cause — Tracing one complaint back to the line — **product photo** `s2-hook.webp` (Images: rotpunkt.de) |
| 2 | Evidence: quotes from the postings | 0:03.7–0:08.6 | 0:04.0–0:09.5 | Edge banding: The band lifts, or the edge chips after delivery; Panel cutting: The cut is out of size, so the front no longer fits; Surface and finish: The colour or the grain does not match the batch |
| 3 | The problem | 0:08.6–0:15.4 | 0:09.5–0:17.9 | Where the answer hides: Front came back ← Batch records · Machine logs · Old complaints · Experienced people — **product photo** `s2-front.jpg` (Images: rotpunkt.de) |
| 4 | The idea | 0:15.4–0:19.1 | 0:17.9–0:22.9 | One idea: Trace it back to the line (complaint, batch and instructions, then a person confirms) — **product photo** `s2-idea.jpg` (Images: rotpunkt.de) |
| 5 | Architecture, built step by step | 0:19.1–0:34.2 | 0:22.9–0:39.7 | Complaint comes in → Past cases (RAG) → AI agents (LLM) → Quality team confirms → Saved for the next batch; badges: Local LLM · Data stays in the plant · Every answer traceable · Human decides |
| 6 | Built before (REAL RESULT, from the CV) | 0:34.2–0:45.9 | 0:39.7–0:50.7 | [REAL RESULT] Multi-agent system with LangGraph · Siemens Amberg: 30–120 → 8–15 min root cause analysis per fault; 16 machines on the line; 12 LLM agents working together; 82.2 % root-cause hits on 1,811 historical error codes — Source: candidate's CV. A real result there, not a Rotpunkt figure. |
| 7 | Pilot targets (stamped ILLUSTRATIVE) | 0:45.9–0:51.8 | 0:50.7–0:56.9 | [ILLUSTRATIVE] Days to trace one front complaint: 5 → 1 days; Repeat defects that still ship (index): 100 → 40 — Example values, not your company's data. To be measured in a pilot. |
| 8 | A first pilot | 0:51.8–0:55.5 | 0:56.9–1:01.8 | A first pilot: One front family · Complaints and batch data, read-only · Measured with quality and production |
| 9 | Closing card | 0:55.5–1:01.6 | 1:01.8–1:07.9 | Hanumanthu Harsha Vardhan — Concept by — github.com/hharsha98 (A concept, not an official Rotpunkt project · illustrative numbers · AI voice) |

Length: **EN 61.6 s**, **DE 67.9 s** (narration plus a 4.6 s hold on the closing card).
<!-- /AUTO -->

**English narration**

<!-- AUTO:short2:en -->
1. `0:00.2–0:03.2` *(hook)* A kitchen front comes back, and the customer is waiting.
2. `0:03.7–0:06.9` *(evidence)* Was it the edge banding, the panel cut, or the surface?
3. `0:08.6–0:14.0` *(pain)* The answer sits in batch records, machine logs, old complaints, and a few experienced people.
4. `0:15.4–0:18.1` *(idea)* One idea: trace that complaint back to the line.
5. `0:19.1–0:23.9` *(arch)* It reads the complaint and the photos, and searches past cases and work instructions.
6. `0:24.2–0:28.5` *(arch)* AI agents rank the likely causes, each one with the evidence behind it.
7. `0:28.8–0:32.6` *(arch)* The quality team confirms, and the fix is saved for the next batch.
8. `0:34.2–0:44.4` *(proof)* The same pattern already runs at Siemens Amberg: on 16 machines, root cause analysis went from 30 to 120 minutes per fault, down to 8 to 15.
9. `0:45.9–0:50.2` *(metrics)* For kitchen fronts, these targets stay illustrative until a pilot measures them.
10. `0:51.8–0:55.0` *(pilot)* A pilot could start with one front family and its complaints.
11. `0:55.5–0:57.0` *(closing)* Happy to explore it with you.

141 words, 57.0 s of narration. Voice: `kokoro:af_heart`.
<!-- /AUTO -->

**German narration (Deutsch)**

<!-- AUTO:short2:de -->
1. `0:00.2–0:03.5` *(hook)* Eine Küchenfront kommt zurück, und der Kunde wartet.
2. `0:04.0–0:07.8` *(evidence)* War es die Kantenleimung, der Plattenzuschnitt oder die Oberfläche?
3. `0:09.5–0:16.5` *(pain)* Die Antwort steckt in Chargen, Maschinenprotokollen, alten Reklamationen und bei wenigen erfahrenen Leuten.
4. `0:17.9–0:21.9` *(idea)* Eine Idee: die Reklamation bis zur Linie zurückverfolgen.
5. `0:22.9–0:28.2` *(arch)* Er liest die Reklamation und die Fotos und sucht in früheren Fällen und Arbeitsanweisungen.
6. `0:28.5–0:33.3` *(arch)* KI-Agenten bewerten die wahrscheinlichen Ursachen, jeweils mit dem Beleg dazu.
7. `0:33.6–0:38.1` *(arch)* Das Qualitätsteam bestätigt, und die Lösung gilt für die nächste Charge.
8. `0:39.7–0:49.2` *(proof)* Dasselbe Muster läuft bei Siemens in Amberg: An 16 Maschinen sank die Ursachenanalyse von 30 bis 120 auf 8 bis 15 Minuten.
9. `0:50.7–0:55.4` *(metrics)* Für Küchenfronten bleiben diese Ziele Beispielwerte, bis ein Pilot sie misst.
10. `0:56.9–1:01.2` *(pilot)* Ein Pilot könnte mit einer Frontfamilie und ihren Reklamationen starten.
11. `1:01.8–1:03.3` *(closing)* Mehr dazu gern im Gespräch.

121 words, 63.3 s of narration. Voice: `edge:de-DE-KatjaNeural@+0%`.
<!-- /AUTO -->

## 8. Short 3 — Know-how on demand ("Years of know-how, one question away")

v2 presents this as the author's own idea, in generic industry terms. It does not mention their job postings or quote them.

- **Problem:** in a kitchen factory the hardest knowledge takes years: which front fits which carcass, finishes and batches, and machine
  setup that lives in a few people's heads. It is slow to pass on.
- **Idea:** a knowledge assistant. A colleague asks in plain words; it searches work instructions, rules, manuals and solved cases
  (RAG); every answer names its source; if the documents don't cover it, it says so and names a person. It runs on the
  company's servers, respects access rights, and never rates people.
- **Built before (real):** local RAG research at FAU Erlangen-Nürnberg (FAPS), published at EBL 2026: 0.97 faithfulness, answer accuracy
  85 → 92 %, query latency 500 → 150 ms, local stack (Ollama, FAISS, Docker).
- **Illustrative pilot targets:** questions to experts per week and team 40 → 15; weeks until a new colleague works independently 12 → 8.
- **Pilot:** one team (for example order handling), only approved documents, feedback from new colleagues.

<!-- AUTO:short3:scenes -->
| # | Scene | EN | DE | On screen (EN labels; DE uses the German labels) |
|---|---|---|---|---|
| 1 | Hook (cover, frame 0) | 0:00.0–0:04.2 | 0:00.0–0:04.0 | Years of know-how, / one question away — One way to keep specialist knowledge on the line — **product photo** `s3-hook.jpg` (Images: rotpunkt.de) |
| 2 | Evidence: quotes from the postings | 0:04.2–0:08.7 | 0:04.0–0:10.1 | Order rules: Which front fits which carcass, and what may never be combined; Finishes: Colours, batches, and what the eye notices; The machines: Setup that lives in a few people's heads |
| 3 | The problem | 0:08.7–0:12.8 | 0:10.1–0:15.2 | Specialist knowledge today: Years to learn · Slow to pass on · Held by a few; Few experts ← questions · interruptions ← New colleagues |
| 4 | The idea | 0:12.8–0:17.9 | 0:15.2–0:20.9 | One idea: A knowledge assistant (answers from your own documents, always with the source) — **product photo** `s3-idea.webp` (Images: rotpunkt.de) |
| 5 | Architecture, built step by step | 0:17.9–0:35.7 | 0:20.9–0:40.6 | A colleague asks → Your documents (RAG) → Answer with its source → Not covered? It says so; badges: On your servers · Access rights respected · GDPR in mind · Never rates people |
| 6 | Built before (REAL RESULT, from the CV) | 0:35.7–0:44.2 | 0:40.6–0:49.9 | [REAL RESULT] Local RAG · FAU Erlangen-Nürnberg: 0.97 faithfulness to the source documents; 85 → 92 % answer accuracy; 500 → 150 ms query latency; Local stack: Ollama · FAISS · Docker — Source: candidate's CV · DOI 10.53192/EBL20260344 |
| 7 | Pilot targets (stamped ILLUSTRATIVE) | 0:44.2–0:50.3 | 0:49.9–0:56.8 | [ILLUSTRATIVE] Questions to experts per week, per team: 40 → 15; Weeks until a new colleague works independently: 12 → 8 weeks — Example values, not your company's data. To be measured in a pilot. |
| 8 | A first pilot | 0:50.3–0:54.1 | 0:56.8–1:01.8 | A first pilot: One team, for example order handling · Only approved documents · Feedback from new colleagues |
| 9 | Closing card | 0:54.1–1:00.1 | 1:01.8–1:08.0 | Hanumanthu Harsha Vardhan — Concept by — github.com/hharsha98 (A concept, not an official Rotpunkt project · illustrative numbers · AI voice) |

Length: **EN 60.1 s**, **DE 68.0 s** (narration plus a 4.6 s hold on the closing card).
<!-- /AUTO -->

**English narration**

<!-- AUTO:short3:en -->
1. `0:00.2–0:03.6` *(hook)* In a kitchen factory, the hardest knowledge takes years to learn.
2. `0:04.2–0:07.0` *(evidence)* Order rules, finishes, and how a machine is set up.
3. `0:08.7–0:11.4` *(pain)* It is slow to teach, and it sits with a few people.
4. `0:12.8–0:16.9` *(idea)* One idea: an assistant that answers questions from your own documents.
5. `0:17.9–0:23.8` *(arch)* A colleague asks in plain words. It searches instructions, rules, manuals and solved cases.
6. `0:24.1–0:29.8` *(arch)* Each answer shows its source. If the documents don't cover it, it says so and names an expert.
7. `0:30.1–0:34.1` *(arch)* It runs on your servers, respects access rights, and never rates people.
8. `0:35.7–0:42.6` *(proof)* In published research at FAU, a local system like this reached 0.97 faithfulness to its sources.
9. `0:44.2–0:48.7` *(metrics)* Illustrative targets: fewer interruptions for experts, and faster onboarding.
10. `0:50.3–0:53.5` *(pilot)* A pilot could start with one team, such as order handling.
11. `0:54.1–0:55.5` *(closing)* Happy to explore it with you.

130 words, 55.5 s of narration. Voice: `kokoro:af_heart`.
<!-- /AUTO -->

**German narration (Deutsch)**

<!-- AUTO:short3:de -->
1. `0:00.2–0:03.5` *(hook)* In einer Küchenfertigung braucht das wichtigste Wissen Jahre.
2. `0:04.0–0:08.4` *(evidence)* Auftragsregeln, Oberflächen, und wie eine Maschine eingerichtet wird.
3. `0:10.1–0:13.8` *(pain)* Die Einarbeitung dauert, und das Wissen liegt bei wenigen Leuten.
4. `0:15.2–0:19.9` *(idea)* Eine Idee: ein Assistent, der aus Ihren eigenen Dokumenten antwortet.
5. `0:20.9–0:27.2` *(arch)* Man fragt in einfachen Worten, er durchsucht Anweisungen, Regeln, Handbücher und gelöste Fälle.
6. `0:27.5–0:33.9` *(arch)* Jede Antwort nennt ihre Quelle. Steht es nicht drin, sagt er das und nennt eine Fachperson.
7. `0:34.2–0:39.0` *(arch)* Er läuft auf Ihren Servern, achtet auf Zugriffsrechte und bewertet niemals Menschen.
8. `0:40.6–0:48.3` *(proof)* In veröffentlichter Forschung an der Uni Erlangen erreichte ein lokales System dieser Art eine Quellentreue von 0,97.
9. `0:49.9–0:55.2` *(metrics)* Beispielhafte Ziele: weniger Unterbrechungen für Fachleute, schnellere Einarbeitung.
10. `0:56.8–1:01.3` *(pilot)* Ein Pilot könnte mit einem Team starten, etwa in der Auftragsbearbeitung.
11. `1:01.8–1:03.4` *(closing)* Mehr dazu gern im Gespräch.

118 words, 63.4 s of narration. Voice: `edge:de-DE-KatjaNeural@+0%`.
<!-- /AUTO -->

## 9. How the videos were made and checked

- **Pipeline:** narration scripts (`scripts/shortN.json`, EN + DE, with cue words that time the animations) → speech (Kokoro for EN,
  Edge/Katja for DE) with per-word timings → Whisper check of every line against the script (the pipeline's "did it say what the script
  says" step) → Remotion 4.0.534 (the pinned template from [media-studio](https://github.com/hharsha98/media-studio), cloned as a reference)
  renders the animated diagrams and word-highlighted captions → ffmpeg mixes voice and music → frame sheets reviewed by eye.
  MoneyPrinterTurbo was not needed: it assembles stock footage, and these Shorts are pure motion graphics (no stock clips, so no hidden logos).
- **Checks done (v2, the files to show):**
  - Format: all twelve v2 files are 1080x1920, H.264. Voiced files have AAC audio; silent files have no audio track.
    Lengths: EN 62.1 / 61.6 / 60.1 s, DE 70.3 / 67.9 / 68.0 s. All sit in the 60–75 s range.
  - Frames: a contact sheet of every v2 video (one frame every 4–5 s) plus stills of the new scenes (front complaint, know-how cards,
    logo closing card) were reviewed. The "AI idea sketch" label is gone, the logo card reads as a concept, captions sit clear of the
    content, and no photo is drawn on as if it showed a defect.
  - Frames: a contact sheet (one frame every 2 s) of every video, still frames at the end of every scene in both languages, frames just
    after every scene change, and caption crops at word midpoints (the pill sits on the spoken word) were all reviewed by eye. Text
    that did not fit, overlaps and covered credits were fixed before the final render.
  - Independent review: an AI video model watched the final EN Short 1 and found no issue (captions in sync, photos sharp, credits visible,
    callouts on the right objects, no logo, ILLUSTRATIVE clearly visible, clean audio). On a downscaled copy of DE Short 3 it reported two
    caption overlaps (0:32–0:36, 0:46–0:49). The full-resolution frames show no overlap: the badges end about 175 px and the footnote
    about 115 px above the caption panel.
  - Voice: Whisper checks every line twice (whole narration and the line on its own). English matches the script, apart from
    recogniser spellings ("catalog"). In German, one real slip was found and fixed: Katja read "KI-Agent" as "Kai-Agent" in Short 1, so that
    line is now spoken from "K-I-Agent" and re-checked as exact. "KI-Assistent" and "KI-Agenten" are read correctly as written (the
    spelled form would make them worse: "Kei Assistent", "Keine Agenten"). The remaining German differences are recogniser quirks: split
    compounds ("Stellen anzeigen"), "gerne" for "gern", the letter names in DSGVO, and the German final sound in "Logs".