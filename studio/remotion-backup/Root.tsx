import React from "react";
import { Composition } from "remotion";
import { FPS, Teaser, calculateTeaserMetadata, teaserDefaults } from "./Teaser";
import { PANEL_FPS, ShortsPanel, calculateShortsPanelMetadata, shortsPanelDefaults } from "./ShortsPanel";
import { CAPTION_FPS, CAPTION_H, CAPTION_W, WordCaptions, calculateWordCaptionsMetadata, wordCaptionsDefaults } from "./WordCaptions";

/**
 * One teaser component, three shapes. Render one with, for example:
 *   npx remotion render src/index.ts Teaser out/teaser.mp4 --props=props.json
 * Add your own compositions below; keep ids short and use no spaces.
 */
export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition id="Teaser" component={Teaser} width={1080} height={1080} fps={FPS} durationInFrames={FPS * 6} defaultProps={teaserDefaults} calculateMetadata={calculateTeaserMetadata} />
      <Composition id="TeaserVertical" component={Teaser} width={1080} height={1920} fps={FPS} durationInFrames={FPS * 6} defaultProps={teaserDefaults} calculateMetadata={calculateTeaserMetadata} />
      <Composition id="TeaserWide" component={Teaser} width={1920} height={1080} fps={FPS} durationInFrames={FPS * 6} defaultProps={teaserDefaults} calculateMetadata={calculateTeaserMetadata} />
      {/* Transparent 1080x1080 explainer panel for Shorts; props: {visual, seconds, lang}. Used by shorts-studio. */}
      <Composition id="ShortsPanel" component={ShortsPanel} width={1080} height={1080} fps={PANEL_FPS} durationInFrames={PANEL_FPS * 5} defaultProps={shortsPanelDefaults} calculateMetadata={calculateShortsPanelMetadata} />
      {/* Transparent 1080x560 one-word-at-a-time caption track, overlaid at y=1300; props: {words, fontSize, strokeWidth, boxHeight, textColor, strokeColor, seconds}. Used by shorts-studio. */}
      <Composition id="WordCaptions" component={WordCaptions} width={CAPTION_W} height={CAPTION_H} fps={CAPTION_FPS} durationInFrames={CAPTION_FPS * 3} defaultProps={wordCaptionsDefaults} calculateMetadata={calculateWordCaptionsMetadata} />
    </>
  );
};
