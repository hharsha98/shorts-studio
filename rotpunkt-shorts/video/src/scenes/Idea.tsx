import React, { useMemo } from "react";
import { C, CONTENT_W, MARGIN, W, tint } from "../theme";
import { fitText } from "../text";
import { clamp01, ease, pop } from "../anim";
import { Icon } from "../icons";
import { Lines, SceneShell } from "../components/Scene";
import type { Labels, SceneCtx } from "../types";

export const IdeaScene: React.FC<{ ctx: SceneCtx; idea: Labels["idea"] }> = ({ ctx, idea }) => {
  const { frame, fps, start } = ctx;
  const titleFit = useMemo(() => fitText(idea.title, { max: 92, min: 58, maxW: CONTENT_W, maxLines: 3, weight: 800 }), [idea.title]);
  const subFit = useMemo(() => fitText(idea.sub, { max: 38, min: 28, maxW: 900, maxLines: 2, weight: 500 }), [idea.sub]);
  const iconP = pop(frame, start + 2, fps, 140, 13);
  const kickerP = ease(frame, start + 4, 10);
  const titleP = pop(frame, start + 8, fps, 150, 16);
  const subP = ease(frame, start + 16, 12);
  const ring = 1 + 0.04 * Math.sin(frame / 8);
  const cy = 590;
  return (
    <SceneShell ctx={ctx}>
      <div
        style={{
          position: "absolute",
          left: W / 2 - 170,
          top: cy - 170,
          width: 340,
          height: 340,
          borderRadius: 170,
          background: `radial-gradient(circle, ${tint(C.amber, 0.22)} 0%, ${tint(C.amber, 0.06)} 60%, ${tint(C.amber, 0)} 72%)`,
          transform: `scale(${iconP * ring})`,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: W / 2 - 115,
          top: cy - 115,
          width: 230,
          height: 230,
          borderRadius: 115,
          border: `5px solid ${C.amber}`,
          background: tint(C.amber, 0.1),
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          transform: `scale(${iconP})`,
        }}
      >
        <Icon name={idea.icon} size={130} color={C.amber} stroke={3.2} />
      </div>
      <div style={{ position: "absolute", left: MARGIN, width: CONTENT_W, top: cy + 170, textAlign: "center" }}>
        <div style={{ fontSize: 38, fontWeight: 800, color: C.amber, letterSpacing: 5, textTransform: "uppercase", opacity: kickerP }}>{idea.kicker}</div>
        <div style={{ marginTop: 22, opacity: clamp01(titleP * 1.5), transform: `scale(${0.9 + 0.1 * titleP})` }}>
          <Lines fit={titleFit} weight={800} align="center" lineHeight={1.08} />
        </div>
        <div style={{ marginTop: 28, opacity: subP, transform: `translateY(${(1 - subP) * 14}px)` }}>
          <Lines fit={subFit} weight={500} color={C.sub} align="center" lineHeight={1.28} />
        </div>
      </div>
    </SceneShell>
  );
};
