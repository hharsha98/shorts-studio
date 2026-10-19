import React from "react";
import { Composition } from "remotion";
import { FPS, H, W } from "./theme";
import { InterviewShort, calculateShortMetadata } from "./InterviewShort";
import { sampleProps } from "./sample";

/**
 * Render one Short with, for example:
 *   npx remotion render src/index.ts InterviewShort out.mp4 --props=../work/companies/<slug>/<problem>/de/props.json
 * The props (scene windows, cues and captions timed by the narration) come from make_company_short.py.
 */
export const RemotionRoot: React.FC = () => (
  <Composition
    id="InterviewShort"
    component={InterviewShort}
    width={W}
    height={H}
    fps={FPS}
    durationInFrames={Math.round(sampleProps.durationSeconds * FPS)}
    defaultProps={sampleProps}
    calculateMetadata={calculateShortMetadata}
  />
);
