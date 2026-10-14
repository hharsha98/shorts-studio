# Remotion backup

`~/MediaStudio/video` is not a git repo, so the files we changed there are copied here.
These are the CURRENT versions (not the originals media-studio's setup created).

What we changed compared to media-studio's original template:
- `src/ShortsPanel.tsx`: new (diagram panels: flow / stat / compare). Later 3 helpers were exported for reuse.
- `src/WordCaptions.tsx`: new (one-word-at-a-time captions with the pop-in spring). A caption word may carry its own
  `fontSize` (smaller than the base size; its outline shrinks with it), for the few words that are too wide at the base size.
- `src/HookCard.tsx`: new (the two-line hook card over the first seconds: Be Vietnam Pro Bold, white with a dark outline and
  shadow, one accent word in #FFB000; transparent 1080x450, overlaid at y=250; complete from frame 0 because frame 0 is the
  cover image, then a 0.25 s fade-out after `holdSeconds`).
- `src/Root.tsx`: added the `ShortsPanel`, `WordCaptions` and `HookCard` compositions; the original `Teaser*` compositions are untouched.
- `public/fonts/BeVietnamPro-Bold.ttf`: copied from MoneyPrinterTurbo (SIL OFL font).

To restore after re-running `/media-studio:setup`: copy the four `.tsx` files back into `~/MediaStudio/video/src/`
and the font into `~/MediaStudio/video/public/fonts/`.
