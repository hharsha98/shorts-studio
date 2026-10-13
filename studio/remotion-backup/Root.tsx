import React from "react";
import { Composition } from "remotion";
import { FPS, Teaser, calculateTeaserMetadata, teaserDefaults } from "./Teaser";
import { PANEL_FPS, ShortsPanel, calculateShortsPanelMetadata, shortsPanelDefaults } from "./ShortsPanel";

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
    </>
  );
};
