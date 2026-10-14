# Remotion backup

`~/MediaStudio/video` is not a git repo, so the files we changed there are copied here.
These are the CURRENT versions (not the originals media-studio's setup created).

What we changed compared to media-studio's original template:
- `src/ShortsPanel.tsx`: new (diagram panels: flow / stat / compare). Later 3 helpers were exported for reuse.
- `src/WordCaptions.tsx`: new (one-word-at-a-time captions with the pop-in spring).
- `src/Root.tsx`: added the `ShortsPanel` and `WordCaptions` compositions; the original `Teaser*` compositions are untouched.
- `public/fonts/BeVietnamPro-Bold.ttf`: copied from MoneyPrinterTurbo (SIL OFL font).

To restore after re-running `/media-studio:setup`: copy the three `.tsx` files back into `~/MediaStudio/video/src/`
and the font into `~/MediaStudio/video/public/fonts/`.
