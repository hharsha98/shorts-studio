# Your to-do list (things only you can do)

Claude does everything else: scripts, voices, videos, checks, captions, weekly analysis.
Tick a box by changing `[ ]` to `[x]`.

## Now (about 20 minutes)
- [ ] **Pexels key** (free stock clips). Sign up at https://www.pexels.com/api/ and request a key
      ("personal short-video project"). Then run `nano ~/shorts-studio/MoneyPrinterTurbo/config.toml`,
      go to line 85 and write `pexels_api_keys = ["YOUR-KEY"]`. Save with Ctrl+O, Enter, then Ctrl+X.
      Don't use TextEdit: it can turn `"` into curly quotes and break the file.
- [ ] **Listen to the voice samples** in `studio/voice-tests/`. Which English voice do you prefer (Aiden or Ryan)?
      Ask a native German speaker whether `de-Aiden.wav` / `de-Ryan.wav` sound natural or clearly foreign.

## Before the first post
- [ ] **Pick a brand name** (one idea for both languages). Check the handle is free on all 3 platforms.
      Also do a quick trademark search at https://register.dpma.de and https://euipo.europa.eu/eSearch/
  1. **How It Ticks** / **So tickt's** (my favourite: the same idiom works in both languages)
  2. **Inside Things** / **Von innen erklärt**
  3. **Explained in 60** / **Erklärt in 60**
- [ ] **Book the free IHK start-up advice** (Gründungsberatung) at your local IHK. Questions to ask:
  1. Do I need an Impressum from the very first post if I plan to earn money later?
  2. Which address can I use? (My German home address? A business-address service? Is my address in India OK?
     The law says "the address at which you are established".)
  3. When do I have to register a Gewerbe for a content channel plus video services for local businesses?
  4. Kleinunternehmerregelung (§19 UStG): does it make sense for me?
- [ ] **If you have a job or contract** (including a thesis contract or a disclosure agreement): check whether
      a side job (Nebentätigkeit) must be reported to the employer. Make sure the topics don't touch anything confidential.
- [ ] **Impressum page**, set up the way the IHK advises (Claude can draft the text). Put its link in each bio.
- [ ] **Create 6 accounts** (EN brand + DE brand on TikTok, YouTube, Instagram):
  - Use a new email for the brand, a password manager, and **2FA** (two-step login) everywhere.
  - **TikTok:** a *personal* account (business accounts can't join Creator Rewards).
  - **Instagram:** switch to a *Creator* account.
  - **YouTube:** one Google account can hold both channels (a "brand account" each).
  - Bio: one sentence about the channel + "AI-voiced" + the Impressum link.

## Every week (about 4.5–5.5 h at full scope)
- [ ] Watch the week's 6 videos in `review/` (about 8 min each). Tell Claude "approved" or what to change.
- [ ] Upload and schedule each video on all 3 platforms from your computer, in one sitting:
  - **YouTube Studio:** upload, then "Schedule". For "Altered or synthetic content", answer by YouTube's criteria
    (a generic narrator over unaltered clips is usually "No"). The caption already says "AI voice".
  - **TikTok** (tiktok.com/upload): schedule, and under more options switch on **"AI-generated content"**.
  - **Instagram** (Meta Business Suite): schedule, and switch on **"Add AI label"** in advanced settings.
  - Copy title, caption, hashtags and credits from each video's `caption.txt`.
- [ ] Reply to comments (about 1 h).
- [ ] After 7 days, add each video's numbers to `studio/tracker.csv`, or open the analytics pages in Chrome
      and let Claude read them.
- [ ] 30-minute weekly review with Claude.

## Check-ins
- **Week 1:** set your week-6 targets. For example: "continue if median 7-day views ≥ 500 and average % watched ≥ 50%
  on at least one platform".
- **Week 3:** if this takes more than 5 h a week, drop to YouTube + TikTok only, or 2 videos per language.
- **Week 6:** keep, adjust or change the topic, judged against your targets.
