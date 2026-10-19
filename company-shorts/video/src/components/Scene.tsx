import React, { useMemo } from "react";
import { C, CONTENT_W, MARGIN, Y } from "../theme";
import { fitText } from "../text";
import type { Fit } from "../text";
import { clamp01, ease, pop } from "../anim";
import type { SceneCtx } from "../types";

const EXIT = 6;
const ENTER_DELAY = 4;

/**
 * Visible window of a scene, plus its enter and exit motion. The outgoing scene is gone (fast ease-in fade) before the
 * incoming one is half visible, so two scenes never read on top of each other. The cover scene (frame 0) has no enter motion.
 */
export const SceneShell: React.FC<{ ctx: SceneCtx; noEnter?: boolean; children: React.ReactNode }> = ({ ctx, noEnter, children }) => {
  const { frame, fps, start, end } = ctx;
  if (frame < start || frame >= end + EXIT) return null;
  const enter = noEnter ? 1 : pop(frame, start + ENTER_DELAY, fps, 150, 18);
  const exit = clamp01((frame - end) / EXIT);
  const opacity = clamp01(enter * 1.6) * (1 - exit) * (1 - exit);
  const y = (1 - enter) * 46 - exit * 30;
  return (
    <div style={{ position: "absolute", inset: 0, opacity, transform: `translateY(${y}px)` }}>
      {children}
    </div>
  );
};

export const Lines: React.FC<{
  fit: Fit;
  weight?: number;
  color?: string;
  align?: "left" | "center" | "right";
  lineHeight?: number;
  style?: React.CSSProperties;
}> = ({ fit, weight = 700, color = C.text, align = "left", lineHeight = 1.15, style }) => (
  <div style={{ fontSize: fit.size, fontWeight: weight, color, textAlign: align, lineHeight, ...style }}>
    {fit.lines.map((line, i) => (
      <div key={i} style={{ whiteSpace: "nowrap" }}>
        {line}
      </div>
    ))}
  </div>
);

/** Scene heading in the top part of the frame with the amber accent bar. Returns its height for layout. */
export const titleHeight = (fit: Fit): number => Math.round(fit.lines.length * fit.size * 1.12) + 30;

export const useTitleFit = (text: string, max = 60): Fit =>
  useMemo(() => fitText(text, { max, min: 42, maxW: CONTENT_W, maxLines: 2, weight: 800 }), [text, max]);

export const SceneTitle: React.FC<{ ctx: SceneCtx; fit: Fit; top?: number }> = ({ ctx, fit, top = Y.sceneTop }) => {
  const bar = ease(ctx.frame, ctx.start + 4, 14);
  return (
    <div style={{ position: "absolute", left: MARGIN, top, width: CONTENT_W }}>
      <Lines fit={fit} weight={800} lineHeight={1.12} />
      <div style={{ marginTop: 16, width: 110 * bar, height: 8, borderRadius: 4, background: C.amber }} />
    </div>
  );
};

/** Small grey footnote line under the caption panel. */
export const Footnote: React.FC<{ text: string; opacity?: number; icon?: React.ReactNode }> = ({ text, opacity = 1, icon }) => (
  <div
    style={{
      position: "absolute",
      left: MARGIN,
      width: CONTENT_W,
      top: Y.footnote,
      display: "flex",
      justifyContent: "center",
      alignItems: "center",
      gap: 12,
      opacity,
      color: C.sub,
      fontSize: 26,
      fontWeight: 500,
      textAlign: "center",
    }}
  >
    {icon}
    <span>{text}</span>
  </div>
);
