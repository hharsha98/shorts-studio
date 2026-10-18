# Rotpunkt Küchen interview Shorts: storyboard and scripts

Three vertical Shorts (1080x1920, 30 fps), each in **English** and **German**, for Hanumanthu Harsha Vardhan's interview for
**AI Solution Engineer (m/w/d)** at Rotpunkt Küchen GmbH (Microsoft Teams, Mon 19 Oct 2026, 16:00 Berlin). Each Short takes one
problem that the company's **current job postings** point to and sketches an AI solution for it, built from his real experience.

Everything about Rotpunkt below comes from public job postings and press. The solutions are **ideas**, not known Rotpunkt projects.
All before/after numbers for Rotpunkt are **illustrative** and labelled so on screen; the only real numbers are his own, from his CV.
Each Short shows **real Rotpunkt kitchens** (product photos from rotpunkt.de, credited on every photo) inside its scenes, and every
video has **word-by-word karaoke captions** synced to the voice.

## 1. Deliverables

| File (in `/opt/cursor/artifacts/`) | What |
|---|---|
| `rotpunkt_short_1_en.mp4`, `rotpunkt_short_1_de.mp4` | Challenge 1: order checks (EN / DE, voice + subtle music + word-by-word karaoke captions + product photos) |
| `rotpunkt_short_2_en.mp4`, `rotpunkt_short_2_de.mp4` | Challenge 2: root cause analysis for production systems and machines |
| `rotpunkt_short_3_en.mp4`, `rotpunkt_short_3_de.mp4` | Challenge 3: specialist know-how on demand (skills gap) |
| `rotpunkt_short_N_en_silent.mp4`, `rotpunkt_short_N_de_silent.mp4` | the same six videos without any audio track (captions only), for muted playback or a fallback |
| `rotpunkt_storyboard.md` | this document |

Source code: `rotpunkt-shorts/` in the repository (Remotion project, build tool, scripts, research snapshot). Rebuild: see `README.md`.

## 2. Sources: every posting used

Fetched 18 Oct 2026, 21:55–22:05 UTC. The professional roles come from the **job widget embedded on the careers page**
(rotpunktkuechen.de/karriere/fachkraefte, Connectoor widget `6a7af22645b909b7b58b4e76`), which is the company's own, complete list
at that moment (8 hits). Dates are the widget's creation dates unless a mirror is named. A full snapshot with all quotes is in
`research/postings.json`.

| # | Posting | Site | Date | Named contact | URL |
|---|---|---|---|---|---|
| 1 | Datenmanager IDM (m/w/d) | Bünde | 12.10.2026 | Ewald Häring | https://app.connectoor.de/jobview?jobid=6acce3be45b90924b38b73d1 |
| 2 | IT-Applikationsmanager (Produktionssysteme) (m/w/d) | Bünde | 31.08.2026 (ZipRecruiter: 03.10.2026) | Ewald Häring | https://app.connectoor.de/jobview?jobid=6a955fdb45b90999418bbee6 · https://www.ziprecruiter.de/jobs/615827602-it-applikationsmanager-produktionssysteme-m-w-d-bei-rotpunkt-kuechen |
| 3 | Teamleiter Produktion (m/w/d) | Bünde | 20.08.2026 | Carolin Diestelhorst | https://app.connectoor.de/jobview?jobid=6a86b81945b909b22d8b79cc |
| 4 | Verlader (m/w/d) | Bünde | 20.08.2026 | – | https://app.connectoor.de/jobview?jobid=6a86c4c045b909727e8b9266 |
| 5 | Maschinenbediener (m/w/d) | Bünde | 18.08.2026 | – | https://app.connectoor.de/jobview?jobid=6a84589245b909f8448b8c7d |
| 6 | Sachbearbeiter in der Kundenbetreuung (m/w/d) | Bünde | 11.08.2026 (ZipRecruiter: 24.09.2026) | – | https://app.connectoor.de/jobview?jobid=6a7aff1b45b90929ff8b54bc · https://www.ziprecruiter.de/jobs/606641169-sachbearbeiter-in-der-kundenbetreuung-m-w-d-bei-rotpunkt-kuechen |
| 7 | Materialdisponent (m/w/d) | Bünde | 11.08.2026 | – | https://app.connectoor.de/jobview?jobid=6a7afe5645b909ea958b49ba |
| 8 | Elektriker/ Elektroniker am Standort Getmold (m/w/d) | Preußisch Oldendorf | 11.08.2026 | Carolin Diestelhorst | https://app.connectoor.de/jobview?jobid=6a7afcbd45b909727e8b6c7e |
| 9 | AI Solution Engineer (m/w/d) (the role he applied for; not in the widget list at fetch time, still live) | Bünde | Indeed: 20.09.2026 | invite from Ewald Häring | https://app.connectoor.de/jobview?jobid=6aaf8faf45b90998048b79fe · https://de.indeed.com/viewjob?jk=54b6a3713d326641 |
| 10 | Ausbildung zum Industriekaufmann (m/w/d), start 01.08.2027 | Bünde | ZipRecruiter: 08.10.2026 | – | https://www.ziprecruiter.de/jobs/619824806-ausbildung-zum-industriekaufmann-m-w-d-bei-rotpunkt-kuechen |
| 11 | Ausbildung Elektroniker für Betriebstechnik (m/w/d), start 01.08.2027 | Bünde | ZipRecruiter: 08.10.2026 | – | https://www.ziprecruiter.de/jobs/619824810-ausbildung-elektroniker-fuer-betriebstechnik-m-w-d-bei-rotpunkt-kuechen |
| 12 | Ausbildung Holzmechaniker (m/w/d), start 01.08.2027 | Bünde | careers page | – | https://www.rotpunktkuechen.de/karriere/ausbildung |

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

| Theme | Postings | Evidence | AI fit with his proven work | Chosen |
|---|---|---|---|---|
| **A. Order intake and order/product data** (dealer orders with many variants, export, data exchange between systems, catalogue data for the sales process) | 6, 2, 1, 9; press | „prüfst Kundenbestellungen auf technische Umsetzbarkeit“, „insbesondere aus den Exportmärkten per Telefon und E-Mail“, „mind. 3 Jahre … Ausarbeitung von Küchenmöbelbestellungen“ (6); „Varianten, Maße, Positionierungen und Abhängigkeiten“, „Auftrags-, Produkt- und Produktionsdaten zuverlässig … ausgetauscht“, „EDI-Prozesse, Schnittstellen“ (2); „IDM Daten in mehreren Sprachvarianten“, „Digitalisierung des Sales Prozess“ (1); press: Auftragsabwicklung, Variantenreichtum, ~80 % export (Part F of the brief) | High: LLM extraction + RAG over rules and documents + validation, integrated by REST API (MARA pattern) | **Short 1** |
| **B. Keeping production systems, interfaces and machines running** | 2, 5, 8, 3, 11; press | „gehst den Ursachen auf den Grund, wenn irgendwo etwas hakt“, „analysierst technische Probleme“, „Rückmeldungen und Workflows zwischen Maschinen und unseren Systemen“ (2); „analysierst, behebst und dokumentierst Funktionsstörungen an Maschinen“ (5); „hohe Verfügbarkeit unserer Produktionsanlagen“, „Wartungsarbeiten gemäß Wartungsplan“ (8); press: new machines arriving | Highest: exactly MARA (root cause analysis with LLM agents over manuals, error texts and logs, in production at Siemens Amberg) | **Short 2** |
| **C. Specialist know-how that is hard to hire and slow to teach** (skills gap) | 6, 1, 2, 5, 7, 3, 10–12; HR conference talk | „mind. 3 Jahre“ (6); „Berufserfahrung in der Erstellung von IDM-Daten“, Furnidata (1); „Berufserfahrung in der Möbel- oder Küchenindustrie“, COE/GOE, MOS, Insight2020 „ein Plus“ (2); edge banders, panel saws, CNC (5); „Mehrjährige Berufserfahrung in der Möbelbranche“ (7); „schulst die Prozesse“ (3); three apprenticeships and an own training workshop; a Rotpunkt HR officer was announced as a speaker at a congress on the skills shortage (section 4) | High: local RAG with source citations and faithfulness metrics (FAU research, published), on-prem, access control | **Short 3** |
| D. Logistics and material flow | 4, 7, 3; press (logistics hub) | „Vollständigkeit der Auflieger durch Scannen“ (4); „teilweise JIT“, „Lieferengpässe“, „Kennzahlen“ (7); „Logistikaufträge im ERP-System“, „Materialfluss“ (3) | Medium: possible, but nothing on his CV in planning or forecasting, so it would be a weaker, less honest pitch | not chosen |
| E. A mixed system landscape under digitalisation | 2, 3, 7, 1, 9; press (€50 m incl. IT) | ERP „vorzugsweise Cyncly Insight“ (3), „Microsoft Navision“ (7), „VBA, VBScript und Microsoft SQL“, AutoCAD (2), Furnidata (1) | Cross-cutting: every Short integrates read-only first, through APIs, with local models | built into all three |

System names found in the postings (useful questions for the interview; deliberately **not** shown in the videos because they are
third-party products): Cyncly Insight / Insight2020, COE/GOE, MOS, Microsoft Navision, Furnidata (IDM), VBA/VBScript/MS SQL, AutoCAD,
IMA/Homag edge banders and CNC, Schelling panel saws.

## 4. Interviewers (public professional information only)

Neither person is named or shown in the videos. Only public, professional sources were used.

**Ewald Häring — Leiter IT & Digitalisierung (Head of IT).**
- Title from his own e-mail signature in the invitation (brief, Part E); "IT-Leitung" in Rotpunkt's LinkedIn post on the 2025 apprentice
  intake, which also names a retrainee "Fachinformatiker Systemintegration" (https://de.linkedin.com/posts/rotpunkt-k%C3%BCchen-gmbh_neuer-ausbildungsjahrgang-sieben-neue-gesichter-activity-7363863882789986304-eCNq).
- He is the **named contact for both open IT postings** (careers-page widget data): *IT-Applikationsmanager (Produktionssysteme)* and
  *Datenmanager IDM*, and he invited the AI Solution Engineer candidate.
- What he likely owns day to day (inferred from those postings): production-near applications and their interfaces (EDI, machine feedback,
  "wenn irgendwo etwas hakt"), product master data and IDM catalogue data for the sales process, a small IT team with two open roles plus
  the new AI role, the IT part of the €50 m digitalisation, information security and GDPR.
- Weighting: **Shorts 1 and 2 sit directly in his systems** (order and product data flows; production systems and interfaces). Short 3 is
  built around his security concerns (own servers, access rights, GDPR).
- Uncertain: no public LinkedIn or XING profile of his was found, so his career history is unknown. **Name clash:** searches also return a
  surgeon "Dr./Prof. Ewald Häring" in Minden; that is a different person.

**Carolin Diestelhorst — Personalreferentin (HR officer).**
- Public LinkedIn profile, as shown in search-engine snippets (https://linkedin.com/in/carolin-diestelhorst-30b6051bb): Personalreferentin at
  Rotpunkt since 01/2018; earlier at Rotpunkt *Sachbearbeiterin Lohnabrechnung* (payroll, 2011–2017) and *Verkaufssachbearbeiterin*
  (sales administration, 2006–2011). LinkedIn itself was not opened (login wall), so these dates may be out of date.
- Named **Ansprechpartnerin** on two current postings: *Teamleiter Produktion* and *Elektriker/ Elektroniker am Standort Getmold*.
- Listed as a Rotpunkt speaker at the "Personaltage Löhne" (12–13 Dec 2023), a congress on fighting the skills shortage in the furniture
  industry (IHK Ostwestfalen blog, 22 Nov 2023: https://blog.ostwestfalen.ihk.de/standort-infrastruktur/moebelindustrie-laedt-ein-personaltage-in-der-werretalhalle-loehne/).
  Her public posts (2025) are about company driving-safety trainings.
- What she likely owns day to day: recruiting for many roles that need rare, multi-year experience; onboarding and training; staff programmes.
  Her early years in sales administration mean the order-handling work in Short 1 is familiar ground.
- Weighting: **Short 3 is aimed at her area** (know-how that is hard to hire and slow to teach), and it states the HR-relevant design rule
  "supports people, never rates them" (no CV screening or performance scoring: those uses would be high-risk under the EU AI Act and
  need the works council). Short 1 picks up the "3+ years of order experience" requirement.
- Uncertain: she was only in cc, so she may not join; her exact remit is not public; the snippet data may lag.

## 5. The three problems chosen, and why

1. **Order checks (Short 1).** The strongest business case: an order error costs little at the desk and a lot once it is in production (the
   general "rule of ten" of quality costs). Four postings and the press point to it, it sits in Mr Häring's data flows, and it uses the exact
   building blocks of MARA (LLM agents, retrieval, validation, REST integration).
2. **Root cause analysis (Short 2).** The best match to his real work: MARA cut root cause analysis at Siemens Amberg from 30–120 to 8–15
   minutes per fault on 16 SMT machines. The IT posting even asks for someone who "geht den Ursachen auf den Grund, wenn irgendwo etwas hakt".
3. **Know-how on demand (Short 3).** The most cross-cutting problem: almost every posting asks for rare, multi-year experience. It speaks to
   HR as well as IT, and it rests on his published FAU research (local RAG, 0.97 faithfulness).

Logistics (theme D) was left out on purpose: it is a real topic, but nothing on his CV backs it, and the Shorts should only claim what he has done.

## 6. Voices, music and the honesty rules

- **English voice: Kokoro-82M "af_heart"** (Apache-2.0), the pipeline's English narrator (the user's choice in this repo, 2026-10-15). The
  repo's own server runs it on Apple MLX, which this Linux machine does not have, so the same model and voice ran through Kokoro's reference
  PyTorch package (`kokoro` 0.9.4, model `hexgrad/Kokoro-82M`), locally and free. It returns a time for every word, so captions are exact.
- **German voice: Microsoft "de-DE-KatjaNeural"**, through the free Edge read-aloud service (`edge-tts`, no key). Why: it is one of the two
  standard, widely used German neural voices (with Conrad), studio-recorded by a native speaker; it keeps one female narrator across both
  languages; and when all German lines were voiced with both and transcribed with Whisper, Katja's "KI" came back as "KI" in every line,
  while **Conrad's came back as "Kaj" twice ("Kajassistent", "Kajagenten")**, which would jar in an AI pitch. Katja speaks 7 % faster than her default so each German Short stays under a minute. "EDI" and "ERP" are
  spoken from the spelled forms "E-D-I" and "E-R-P" (she otherwise reads them as words), and the one "KI-Agent" in Short 1 from "K-I-Agent"
  (she otherwise says "Kai-Agent"); the captions keep the written forms. The pipeline's
  German voice (Thorsten) was not available on this machine. Licence note: the Edge service is fine for a private interview presentation;
  for publishing, use the same voice through Azure Speech (paid) or switch to Thorsten.
- **Music:** a quiet pad composed for these videos by the build script (no licence needed), about 18 dB under the voice and ducked further
  while she speaks; final mix −16 LUFS. The silent versions have no audio track at all.
- **Captions:** word-by-word karaoke style in every EN and DE video. The current phrase (1–2 lines, broken at natural points) sits in a
  dark panel; an amber pill slides onto each word exactly when the voice says it (word times come from the speech engines: Kokoro's
  token timestamps for EN, Edge's word boundaries for DE) and the word pops slightly as it lands; spoken words turn white, coming words wait
  dimmed. Spelled-out spoken forms (E-D-I, E-R-P) still show as EDI / ERP.
- **Product photos (real Rotpunkt kitchens):** six photos from the company's public website, shown inside the scenes and credited small on
  every photo as "Images: rotpunkt.de" (German videos: "Bilder: rotpunkt.de"). rotpunkt.de redirects to www.rotpunktkuechen.de, where the
  photos are published. Every photo was fetched successfully, so no generic stand-in was needed. Each was checked by eye for logos,
  watermarks or text (none). The **logo is not used anywhere**, so nothing looks like an official company video. The photos remain the
  company's property: they are downloaded at build time into a git-ignored folder, not committed, and meant only for this private
  interview presentation (ask before publishing anything with them). Sources and placement: `research/images.json`.

  | Short | Scene | Photo (source URL on rotpunktkuechen.de) | What is drawn over it |
  |---|---|---|---|
  | 1 | cover | [wood island with steel hood](https://www.rotpunktkuechen.de/fileadmin/_processed_/8/4/csm_01-zerox-sy-ver-loft-brown-oak_gallery__1400x875_31bc567624.webp) | a dealer order sheet with one flagged line; a magnifier with "!" on the island |
  | 1 | the problem | [island and tall units with oven niche](https://www.rotpunktkuechen.de/fileadmin/40_Inspiration/Minisammlung-Startseite/Rotpunkt_MK07_Hauptschuss__1200.jpg) | callouts: *Variants* on the fronts, *Dimensions* along the island, *Dependencies* at the oven niche |
  | 2 | cover | [dark-oak kitchen with island](https://www.rotpunktkuechen.de/fileadmin/_processed_/5/5/csm_MK_11_Zerox_SY_VER_Loft_Dark_Oak__header__1200_94c6bedc92.webp) | "Line stopped" status pill, slowly turning gears |
  | 2 | the problem | [green kitchen](https://www.rotpunktkuechen.de/fileadmin/_processed_/1/0/csm_06-smala-sc-velvet-green_gallery__1400x875_bc6a077a07.webp) | the stopped line in the centre, with the scattered knowledge sources around it |
  | 3 | cover | [white and wood kitchen with glass cabinets](https://www.rotpunktkuechen.de/fileadmin/40_Inspiration/Minisammlung-Startseite/Rotpunkt_MK09_Hauptschuss__1200.jpg) | a question bubble and an answer card with its source |
  | 3 | the idea | [white kitchen with wood island](https://www.rotpunktkuechen.de/fileadmin/_processed_/1/4/csm_Rotpunkt_HM01_Hauptschuss_Final__1200_7ec0652391.webp) | the knowledge assistant's chat badge |
- **Honesty rules applied:** illustrative numbers carry an ILLUSTRATIVE / BEISPIELWERTE stamp, a footnote "Example values, not your company's
  data. To be measured in a pilot." and are called illustrative in the narration; real numbers appear only in "REAL RESULT" cards with
  "Source: candidate's CV"; the rule of ten is labelled a general principle. No Rotpunkt logo or brand colours (no red dot); the company
  name appears only in the photo credit (the viewers are addressed as "you"); product photos are credited on screen; quotes from the
  postings are short and attributed to the posting title. The closing card says
  "AI Solution Engineer candidate", never that he works there, and labels the AI voice. The interviewers are not named or shown.
  Third-party product names from the postings stay out of the videos.

## 7. Short 1 — Order checks ("Catch order errors before production")

- **Problem:** experienced staff check every dealer order (often from export markets, by phone and e-mail) for technical feasibility; with
  many variants, dimensions and dependencies, one missed detail means rework, and the later it is found the more it costs.
- **Idea:** an order check assistant. An AI agent reads each order (EDI, PDF, e-mail, any language) and extracts the lines; it checks them
  against the company's own product rules and catalogue/master data (RAG); fixed rule checks flag each conflict with its source; a clerk
  decides; only approved orders reach the ERP. Local LLM, read-only first, GDPR in mind.
- **Built before (real):** MARA at Siemens Amberg (M.Sc. thesis, in production): 12 LLM agents, retrieval over manuals and logs in under
  200 ms, on-prem LLMs for data protection, about 78 % of suggestions accepted at first review.
- **Illustrative pilot targets:** checking time per order 20 → 5 min; errors found only in production, index 100 → 25.
- **Pilot:** one product line, read-only next to the team, success measured with the department.

<!-- AUTO:short1:scenes -->
| # | Scene | EN | DE | On screen (EN labels; DE uses the German labels) |
|---|---|---|---|---|
| 1 | Hook (cover, frame 0) | 0:00.0–0:04.2 | 0:00.0–0:04.6 | Catch order errors / before production — An AI idea based on your current job postings — **product photo** `s1-hook.webp` (Images: rotpunkt.de) |
| 2 | Evidence: quotes from the postings | 0:04.2–0:11.2 | 0:04.6–0:11.1 | Sachbearbeiter in der Kundenbetreuung: „Berufserfahrung (mind. 3 Jahre) in der Ausarbeitung von Küchenmöbelbestellungen“; Sachbearbeiter in der Kundenbetreuung: „…du prüfst Kundenbestellungen auf technische Umsetzbarkeit“; Sachbearbeiter in der Kundenbetreuung: „…insbesondere aus den Exportmärkten per Telefon und E-Mail“ |
| 3 | The problem | 0:11.2–0:15.8 | 0:11.1–0:16.7 | The later an error is found, the more it costs: Desk check ×1 · Production ×10 · At the customer ×100 — **product photo** `s1-pain.jpg` (Images: rotpunkt.de) |
| 4 | The idea | 0:15.8–0:18.5 | 0:16.7–0:20.5 | One idea: An order check assistant (AI agent + your product rules + human approval) |
| 5 | Architecture, built step by step | 0:18.5–0:35.9 | 0:20.5–0:40.4 | Incoming order → AI agent (LLM) → Your product rules (RAG) → Rule checks + clerk → ERP → production; badges: Local LLM · Read-only first · GDPR in mind · Human decides |
| 6 | Pilot targets (stamped ILLUSTRATIVE) | 0:35.9–0:43.0 | 0:40.4–0:47.2 | [ILLUSTRATIVE] Checking time per order: 20 → 5 min; Errors found only in production (index): 100 → 25 — Example values, not your company's data. To be measured in a pilot. |
| 7 | Built before (REAL RESULT, from the CV) | 0:43.0–0:47.3 | 0:47.2–0:51.5 | [REAL RESULT] MARA · Siemens Amberg: 12 LLM agents working together; < 200 ms retrieval over manuals and logs; On-prem LLMs, for data protection; ~78 % of suggestions accepted at first review — Source: candidate's CV |
| 8 | A first pilot | 0:47.3–0:49.9 | 0:51.5–0:54.7 | A first pilot: One product line · Read-only, next to the team · Success measured with the department |
| 9 | Closing card | 0:49.9–0:53.9 | 0:54.7–0:58.7 | Hanumanthu Harsha Vardhan — AI Solution Engineer candidate — github.com/hharsha98 (Idea sketch based on public job postings · illustrative numbers · AI voice) |

Length: **EN 53.9 s**, **DE 58.7 s** (narration plus a 2.5 s hold on the closing card).
<!-- /AUTO -->

**English narration**

<!-- AUTO:short1:en -->
1. `0:00.1–0:03.7` *(hook)* Order errors are cheap at the desk, and expensive in production.
2. `0:04.2–0:10.7` *(evidence)* Your postings show who catches them today: experienced staff checking every dealer order, often for export.
3. `0:11.2–0:15.3` *(pain)* Variants, dimensions, dependencies: one missed detail means rework.
4. `0:15.8–0:18.0` *(idea)* One idea: an order check assistant.
5. `0:18.5–0:22.7` *(arch)* It reads each order, from EDI, PDF or email, in any language.
6. `0:23.0–0:27.3` *(arch)* An AI agent extracts the lines and checks them against your product rules.
7. `0:27.5–0:30.3` *(arch)* Conflicts come with their source, and a clerk decides.
8. `0:30.5–0:35.4` *(arch)* Only approved orders reach the ERP, with local models and GDPR in mind.
9. `0:35.9–0:42.5` *(metrics)* Illustrative pilot targets: checking time from twenty minutes to five, and far fewer errors found in production.
10. `0:43.0–0:46.8` *(proof)* The same building blocks already run in production at Siemens Amberg.
11. `0:47.3–0:49.4` *(pilot)* A pilot could start with one product line.
12. `0:49.9–0:51.4` *(closing)* Happy to explore it with you.

130 words, 51.4 s of narration. Voice: `kokoro:af_heart`.
<!-- /AUTO -->

**German narration (Deutsch)**

<!-- AUTO:short1:de -->
1. `0:00.1–0:04.1` *(hook)* Ein Bestellfehler kostet am Schreibtisch wenig, in der Fertigung viel.
2. `0:04.6–0:10.6` *(evidence)* Ihre Stellenanzeigen zeigen: Erfahrene Fachleute prüfen jede Händlerbestellung, oft für den Export.
3. `0:11.1–0:16.2` *(pain)* Varianten, Maße, Abhängigkeiten: Ein übersehenes Detail heißt Nacharbeit.
4. `0:16.7–0:20.0` *(idea)* Eine Idee: ein KI-Assistent für die Auftragsprüfung.
5. `0:20.5–0:25.5` *(arch)* Er liest jede Bestellung, per EDI, als PDF oder E-Mail, in jeder Sprache.
6. `0:25.8–0:30.1` *(arch)* Ein KI-Agent erfasst die Positionen und prüft sie gegen Ihre Produktregeln.
7. `0:30.3–0:34.1` *(arch)* Konflikte werden mit Quelle markiert, die Entscheidung trifft der Mensch.
8. `0:34.3–0:39.9` *(arch)* Nur freigegebene Aufträge gehen ins ERP, mit lokalen Modellen und der DSGVO im Blick.
9. `0:40.4–0:46.7` *(metrics)* Beispielhafte Pilotziele: Prüfzeit von zwanzig auf fünf Minuten, deutlich weniger Fehler in der Fertigung.
10. `0:47.2–0:51.0` *(proof)* Die gleichen Bausteine laufen bereits produktiv bei Siemens in Amberg.
11. `0:51.5–0:54.2` *(pilot)* Ein Pilot könnte mit einer Produktlinie starten.
12. `0:54.7–0:56.2` *(closing)* Mehr dazu gern im Gespräch.

121 words, 56.2 s of narration. Voice: `edge:de-DE-KatjaNeural@+7%`.
<!-- /AUTO -->

## 8. Short 2 — Root cause analysis ("Root cause in minutes, not hours")

- **Problem:** when a machine or an interface stops, the answer is spread across manuals, machine and interface logs, old tickets and a few
  experienced people, and every minute of searching costs output.
- **Idea:** a root cause assistant. It reads the error text and the logs, searches manuals and past fixes (RAG), AI agents rank the likely
  causes with evidence and a next check, a technician confirms, and the confirmed fix becomes knowledge for the next shift. Local LLM, data
  stays on site, every answer traceable.
- **Built before (real):** MARA: root cause analysis 30–120 → 8–15 min per fault on 16 SMT machines, 12 LLM agents, 82.2 % root-cause hits
  on 1,811 historical error codes.
- **Illustrative pilot targets:** time to root cause per fault 60 → 20 min; faults solved without an expert call 40 → 70 %.
- **Pilot:** one line and its most frequent faults, read-only access to logs, measured with maintenance and IT.

<!-- AUTO:short2:scenes -->
| # | Scene | EN | DE | On screen (EN labels; DE uses the German labels) |
|---|---|---|---|---|
| 1 | Hook (cover, frame 0) | 0:00.0–0:04.6 | 0:00.0–0:05.8 | Root cause in / minutes, not hours — An AI idea based on your current job postings — **product photo** `s2-hook.webp` (Images: rotpunkt.de) |
| 2 | Evidence: quotes from the postings | 0:04.6–0:08.8 | 0:05.8–0:11.4 | IT-Applikationsmanager (Produktionssysteme): „…gehst den Ursachen auf den Grund, wenn irgendwo etwas hakt“; Maschinenbediener: „…analysierst, behebst und dokumentierst Funktionsstörungen an Maschinen“; Elektriker/ Elektroniker am Standort Getmold: „…stellst eine hohe Verfügbarkeit unserer Produktionsanlagen sicher“ |
| 3 | The problem | 0:08.8–0:13.9 | 0:11.4–0:17.4 | Where the answer hides today: Line stopped ← Manuals · Machine and interface logs · Old tickets · Experienced colleagues — **product photo** `s2-pain.webp` (Images: rotpunkt.de) |
| 4 | The idea | 0:13.9–0:16.6 | 0:17.4–0:21.4 | One idea: A root cause assistant (AI agents + your manuals and logs + a technician who confirms) |
| 5 | Architecture, built step by step | 0:16.6–0:29.7 | 0:21.4–0:35.5 | Fault reported → Knowledge search (RAG) → AI agents (LLM) → Technician confirms → The fix becomes knowledge; badges: Local LLM · Data stays on site · Every answer traceable · Human decides |
| 6 | Built before (REAL RESULT, from the CV) | 0:29.7–0:39.5 | 0:35.5–0:45.3 | [REAL RESULT] MARA · Siemens Amberg: 30–120 → 8–15 min root cause analysis per fault; 16 SMT machines on the line; 12 LLM agents working together; 82.2 % root-cause hits on 1,811 historical error codes — Source: candidate's CV |
| 7 | Pilot targets (stamped ILLUSTRATIVE) | 0:39.5–0:43.6 | 0:45.3–0:49.9 | [ILLUSTRATIVE] Time to root cause per fault: 60 → 20 min; Faults solved without an expert call: 40 → 70 % — Example values, not your company's data. To be measured in a pilot. |
| 8 | A first pilot | 0:43.6–0:46.8 | 0:49.9–0:54.2 | A first pilot: One line and its most frequent faults · Read-only access to logs · Measured with maintenance and IT |
| 9 | Closing card | 0:46.8–0:50.7 | 0:54.2–0:58.2 | Hanumanthu Harsha Vardhan — AI Solution Engineer candidate — github.com/hharsha98 (Idea sketch based on public job postings · illustrative numbers · AI voice) |

Length: **EN 50.7 s**, **DE 58.2 s** (narration plus a 2.5 s hold on the closing card).
<!-- /AUTO -->

**English narration**

<!-- AUTO:short2:en -->
1. `0:00.1–0:04.1` *(hook)* When a machine or interface stops, every minute of searching costs output.
2. `0:04.6–0:08.3` *(evidence)* Your postings ask for people who find the root cause when something sticks.
3. `0:08.8–0:13.4` *(pain)* The answers sit in manuals, logs, old tickets, and a few experienced heads.
4. `0:13.9–0:16.1` *(idea)* One idea: a root cause assistant.
5. `0:16.6–0:20.7` *(arch)* It reads the error and the logs, and searches manuals and past fixes.
6. `0:21.0–0:25.0` *(arch)* AI agents rank likely causes, each with evidence and a next check.
7. `0:25.3–0:29.2` *(arch)* A technician confirms, and the fix becomes knowledge for the next shift.
8. `0:29.7–0:39.0` *(proof)* Real result at Siemens Amberg: on 16 machines, root cause analysis went from 30 to 120 minutes per fault, down to 8 to 15.
9. `0:39.5–0:43.1` *(metrics)* Here, the numbers stay illustrative until a pilot measures them.
10. `0:43.6–0:46.3` *(pilot)* A pilot could start with one line and its top faults.
11. `0:46.8–0:48.2` *(closing)* Happy to explore it with you.

132 words, 48.2 s of narration. Voice: `kokoro:af_heart`.
<!-- /AUTO -->

**German narration (Deutsch)**

<!-- AUTO:short2:de -->
1. `0:00.1–0:05.3` *(hook)* Steht eine Maschine oder eine Schnittstelle, kostet jede Minute Fehlersuche bares Geld.
2. `0:05.8–0:10.9` *(evidence)* Ihre Stellenanzeigen suchen Menschen, die den Ursachen auf den Grund gehen, wenn etwas hakt.
3. `0:11.4–0:16.9` *(pain)* Die Antworten stecken in Handbüchern, Logs, alten Tickets und in wenigen erfahrenen Köpfen.
4. `0:17.4–0:20.9` *(idea)* Eine Idee: ein KI-Assistent für die Ursachenanalyse.
5. `0:21.4–0:25.6` *(arch)* Er liest Fehlermeldung und Logs und durchsucht Handbücher und frühere Lösungen.
6. `0:25.8–0:30.7` *(arch)* KI-Agenten bewerten mögliche Ursachen, jeweils mit Beleg und nächstem Prüfschritt.
7. `0:31.0–0:35.0` *(arch)* Das Team bestätigt, und jede Lösung wird zu Wissen für die nächste Schicht.
8. `0:35.5–0:44.8` *(proof)* Echtes Ergebnis bei Siemens in Amberg: An 16 Maschinen sank die Ursachenanalyse von 30 bis 120 auf 8 bis 15 Minuten pro Störung.
9. `0:45.3–0:49.4` *(metrics)* Für Ihre Linien bleiben die Zahlen Beispielwerte, bis ein Pilot sie misst.
10. `0:49.9–0:53.7` *(pilot)* Ein Pilot könnte mit einer Linie und ihren häufigsten Störungen starten.
11. `0:54.2–0:55.7` *(closing)* Mehr dazu gern im Gespräch.

131 words, 55.7 s of narration. Voice: `edge:de-DE-KatjaNeural@+7%`.
<!-- /AUTO -->

## 9. Short 3 — Know-how on demand ("Years of know-how, one question away")

- **Problem:** many open roles need years of very specific experience (kitchen orders, catalogue data, edge banding machines). That know-how
  is hard to hire, slow to teach, and sits with a few experts, who get interrupted by questions.
- **Idea:** a knowledge assistant. A colleague asks in plain words; it searches work instructions, product rules, manuals and solved cases
  (RAG); every answer names its source (document and page); if the documents don't cover it, it says so and names an expert. It runs on the
  company's servers, respects access rights, and never rates people.
- **Built before (real):** local RAG research at FAU Erlangen-Nürnberg (FAPS), published at EBL 2026: 0.97 faithfulness, answer accuracy
  85 → 92 %, query latency 500 → 150 ms, local stack (Ollama, FAISS, Docker).
- **Illustrative pilot targets:** questions to experts per week and team 40 → 15; weeks until a new colleague works independently 12 → 8.
- **Pilot:** one team (for example order handling), only approved documents, feedback from new colleagues.

<!-- AUTO:short3:scenes -->
| # | Scene | EN | DE | On screen (EN labels; DE uses the German labels) |
|---|---|---|---|---|
| 1 | Hook (cover, frame 0) | 0:00.0–0:04.7 | 0:00.0–0:04.8 | Years of know-how, / one question away — An AI idea based on your current job postings — **product photo** `s3-hook.jpg` (Images: rotpunkt.de) |
| 2 | Evidence: quotes from the postings | 0:04.7–0:08.2 | 0:04.8–0:09.1 | Sachbearbeiter in der Kundenbetreuung: „Berufserfahrung (mind. 3 Jahre) in der Ausarbeitung von Küchenmöbelbestellungen“; Datenmanager IDM: „Berufserfahrung in der Erstellung von IDM-Daten oder im Umgang mit Stammdaten“; Maschinenbediener: „Erfahrung mit industriellen Kantenanleim-Maschinen“ |
| 3 | The problem | 0:08.2–0:12.9 | 0:09.1–0:14.9 | Specialist know-how today: Hard to hire · Slow to teach · With a few experts; Few experts ← questions · interruptions ← New colleagues |
| 4 | The idea | 0:12.9–0:17.5 | 0:14.9–0:19.8 | One idea: A knowledge assistant (answers from your own documents, always with the source) — **product photo** `s3-idea.webp` (Images: rotpunkt.de) |
| 5 | Architecture, built step by step | 0:17.5–0:34.1 | 0:19.8–0:37.2 | A colleague asks → Your documents (RAG) → Answer with its source → Not covered? It says so; badges: On your servers · Access rights respected · GDPR in mind · Never rates people |
| 6 | Built before (REAL RESULT, from the CV) | 0:34.1–0:41.6 | 0:37.2–0:44.9 | [REAL RESULT] Local RAG · FAU Erlangen-Nürnberg: 0.97 faithfulness to the source documents; 85 → 92 % answer accuracy; 500 → 150 ms query latency; Local stack: Ollama · FAISS · Docker — Source: candidate's CV · DOI 10.53192/EBL20260344 |
| 7 | Pilot targets (stamped ILLUSTRATIVE) | 0:41.6–0:46.6 | 0:44.9–0:50.4 | [ILLUSTRATIVE] Questions to experts per week, per team: 40 → 15; Weeks until a new colleague works independently: 12 → 8 weeks — Example values, not your company's data. To be measured in a pilot. |
| 8 | A first pilot | 0:46.6–0:50.3 | 0:50.4–0:55.1 | A first pilot: One team, for example order handling · Only approved documents · Feedback from new colleagues |
| 9 | Closing card | 0:50.3–0:54.3 | 0:55.1–0:59.1 | Hanumanthu Harsha Vardhan — AI Solution Engineer candidate — github.com/hharsha98 (Idea sketch based on public job postings · illustrative numbers · AI voice) |

Length: **EN 54.3 s**, **DE 59.1 s** (narration plus a 2.5 s hold on the closing card).
<!-- /AUTO -->

**English narration**

<!-- AUTO:short3:en -->
1. `0:00.1–0:04.2` *(hook)* Many of your open roles ask for years of very specific experience.
2. `0:04.7–0:07.7` *(evidence)* Kitchen orders, catalogue data, edge banding machines.
3. `0:08.2–0:12.4` *(pain)* That know-how is hard to hire, slow to teach, and sits with a few experts.
4. `0:12.9–0:17.0` *(idea)* One idea: an assistant that answers questions from your own documents.
5. `0:17.5–0:23.4` *(arch)* A colleague asks in plain words. It searches instructions, rules, manuals and solved cases.
6. `0:23.7–0:29.3` *(arch)* Each answer shows its source. If the documents don't cover it, it says so and names an expert.
7. `0:29.6–0:33.6` *(arch)* It runs on your servers, respects access rights, and never rates people.
8. `0:34.1–0:41.1` *(proof)* In published research at FAU, a local system like this reached 0.97 faithfulness to its sources.
9. `0:41.6–0:46.1` *(metrics)* Illustrative targets: fewer interruptions for experts, and faster onboarding.
10. `0:46.6–0:49.8` *(pilot)* A pilot could start with one team, such as order handling.
11. `0:50.3–0:51.8` *(closing)* Happy to explore it with you.

131 words, 51.8 s of narration. Voice: `kokoro:af_heart`.
<!-- /AUTO -->

**German narration (Deutsch)**

<!-- AUTO:short3:de -->
1. `0:00.1–0:04.3` *(hook)* Viele Ihrer offenen Stellen verlangen jahrelange, sehr spezielle Erfahrung.
2. `0:04.8–0:08.6` *(evidence)* Küchenbestellungen, Katalogdaten, Kantenanleimmaschinen.
3. `0:09.1–0:14.4` *(pain)* Dieses Wissen ist schwer zu finden, braucht lange Einarbeitung und liegt bei wenigen Fachleuten.
4. `0:14.9–0:19.3` *(idea)* Eine Idee: ein Assistent, der aus Ihren eigenen Dokumenten antwortet.
5. `0:19.8–0:25.7` *(arch)* Man fragt in einfachen Worten, er durchsucht Anweisungen, Regeln, Handbücher und gelöste Fälle.
6. `0:25.9–0:31.9` *(arch)* Jede Antwort nennt ihre Quelle. Steht es nicht drin, sagt er das und nennt eine Fachperson.
7. `0:32.1–0:36.7` *(arch)* Er läuft auf Ihren Servern, achtet auf Zugriffsrechte und bewertet niemals Menschen.
8. `0:37.2–0:44.4` *(proof)* In veröffentlichter Forschung an der Uni Erlangen erreichte ein lokales System dieser Art eine Quellentreue von 0,97.
9. `0:44.9–0:49.9` *(metrics)* Beispielhafte Ziele: weniger Unterbrechungen für Fachleute, schnellere Einarbeitung.
10. `0:50.4–0:54.6` *(pilot)* Ein Pilot könnte mit einem Team starten, etwa in der Auftragsbearbeitung.
11. `0:55.1–0:56.6` *(closing)* Mehr dazu gern im Gespräch.

118 words, 56.6 s of narration. Voice: `edge:de-DE-KatjaNeural@+7%`.
<!-- /AUTO -->

## 10. How the videos were made and checked

- **Pipeline:** narration scripts (`scripts/shortN.json`, EN + DE, with cue words that time the animations) → speech (Kokoro for EN,
  Edge/Katja for DE) with per-word timings → Whisper check of every line against the script (the pipeline's "did it say what the script
  says" step) → Remotion 4.0.534 (the pinned template from [media-studio](https://github.com/hharsha98/media-studio), cloned as a reference)
  renders the animated diagrams and word-highlighted captions → ffmpeg mixes voice and music → frame sheets reviewed by eye.
  MoneyPrinterTurbo was not needed: it assembles stock footage, and these Shorts are pure motion graphics (no stock clips, so no hidden logos).
- **Checks done:**
  - Format: all twelve files are 1080x1920, 30 fps, H.264; the voiced ones have AAC audio with the mix at −16 LUFS, and the silent ones have
    no audio track. Lengths: EN 53.9 / 50.7 / 54.3 s, DE 58.7 / 58.2 / 59.1 s.
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
- **Suggested use in the interview:** show Short 2 first if the talk turns to his MARA thesis, Short 1 when processes and ERP come up, Short 3
  when HR or onboarding comes up; end with the question from his cover letter: "Welchen Geschäftsprozess möchten Sie als Erstes mit AI automatisieren?"
