import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { C, CONTENT_W, MARGIN, W, Y, tint } from "../theme";
import { fitText, textWidth } from "../text";
import { Lines } from "./Scene";
import type { Labels } from "../types";

/** Deep blue background with a faint drawing-board grid and two slow glows. Pure function of the frame. */
export const Background: React.FC = () => {
  const frame = useCurrentFrame();
  const t = frame / 30;
  return (
    <AbsoluteFill style={{ background: `linear-gradient(180deg, ${C.bgTop} 0%, ${C.bgBottom} 100%)`, overflow: "hidden" }}>
      <AbsoluteFill
        style={{
          backgroundImage: `linear-gradient(${C.grid} 1.5px, transparent 1.5px), linear-gradient(90deg, ${C.grid} 1.5px, transparent 1.5px)`,
          backgroundSize: "60px 60px",
          backgroundPosition: `0px ${(t * 6) % 60}px`,
        }}
      />
      <div
        style={{
          position: "absolute",
          width: 1500,
          height: 1500,
          left: -520 + 70 * Math.sin(t / 3.1),
          top: -300 + 50 * Math.cos(t / 3.7),
          background: `radial-gradient(circle, ${tint(C.amber, 0.11)} 0%, ${tint(C.amber, 0)} 62%)`,
        }}
      />
      <div
        style={{
          position: "absolute",
          width: 1600,
          height: 1600,
          left: 160 + 60 * Math.cos(t / 4.3),
          top: 900 + 60 * Math.sin(t / 3.3),
          background: `radial-gradient(circle, ${tint(C.blue, 0.09)} 0%, ${tint(C.blue, 0)} 60%)`,
        }}
      />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at center, rgba(0,0,0,0) 55%, rgba(0,0,0,0.38) 100%)" }} />
    </AbsoluteFill>
  );
};

export const TopBar: React.FC<{ top: Labels["top"] }> = ({ top }) => {
  const badgeW = textWidth(top.badge, 30, 800) + 40;
  const topic = fitText(top.topic, { max: 32, min: 20, maxW: CONTENT_W - badgeW - 24, maxLines: 1, weight: 700 });
  return (
    <div style={{ position: "absolute", left: MARGIN, right: MARGIN, top: Y.topBar, height: 60, display: "flex", alignItems: "center" }}>
      <div
        style={{
          width: badgeW,
          height: 54,
          borderRadius: 27,
          background: C.amber,
          color: C.ink,
          fontSize: 30,
          fontWeight: 800,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flex: "none",
        }}
      >
        {top.badge}
      </div>
      <div style={{ marginLeft: 20, flex: 1, minWidth: 0 }}>
        <Lines fit={topic} weight={700} color={C.text} />
      </div>
    </div>
  );
};

export const ProgressBar: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const p = Math.min(1, frame / Math.max(1, durationInFrames - 1));
  return (
    <div style={{ position: "absolute", left: 0, top: Y.progress, width: W, height: 7, background: "rgba(255,255,255,0.08)" }}>
      <div style={{ width: W * p, height: 7, background: tint(C.amber, 0.85) }} />
    </div>
  );
};
