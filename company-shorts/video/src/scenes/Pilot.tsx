import React, { useMemo } from "react";
import { C, CONTENT_W, MARGIN, Y, tint } from "../theme";
import { fitText } from "../text";
import { clamp01, ease, pop } from "../anim";
import { Icon } from "../icons";
import { Lines, SceneShell, SceneTitle, titleHeight, useTitleFit } from "../components/Scene";
import type { Labels, SceneCtx } from "../types";

const CHECK_D = 88;
const ROW_PAD = 34;
const ROW_GAP = 30;
const TEXT_W = CONTENT_W - CHECK_D - 36 - ROW_PAD * 2;

export const PilotScene: React.FC<{ ctx: SceneCtx; pilot: Labels["pilot"] }> = ({ ctx, pilot }) => {
  const { frame, fps } = ctx;
  const titleFit = useTitleFit(pilot.title, 68);
  const subFit = useMemo(() => fitText(pilot.sub, { max: 38, min: 28, maxW: CONTENT_W, maxLines: 1, weight: 500 }), [pilot.sub]);
  const fits = useMemo(() => pilot.items.map((t) => fitText(t, { max: 48, min: 32, maxW: TEXT_W, maxLines: 2, weight: 600 })), [pilot.items]);
  const heights = fits.map((f) => Math.round(Math.max(CHECK_D, f.lines.length * f.size * 1.22) + 2 * ROW_PAD));
  const subTop = Y.sceneTop + titleHeight(titleFit) + 10;
  const areaTop = subTop + subFit.size * 1.3 + 40;
  const blockH = heights.reduce((s, h) => s + h, 0) + ROW_GAP * (heights.length - 1);
  const top0 = Math.round(areaTop + Math.max(0, (Y.sceneBottom - 40 - areaTop - blockH) / 2));
  const tops: number[] = [];
  let y = top0;
  for (const h of heights) {
    tops.push(y);
    y += h + ROW_GAP;
  }
  return (
    <SceneShell ctx={ctx}>
      <SceneTitle ctx={ctx} fit={titleFit} />
      <div style={{ position: "absolute", left: MARGIN, top: subTop, width: CONTENT_W, opacity: ease(frame, ctx.start + 6, 12) }}>
        <Lines fit={subFit} weight={500} color={C.sub} />
      </div>
      {pilot.items.map((item, i) => {
        const at = ctx.cue(`pilot.${i}`, ctx.start + 8 + i * 12);
        const p = pop(frame, at, fps, 170, 15);
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: MARGIN,
              top: tops[i],
              width: CONTENT_W,
              height: heights[i],
              boxSizing: "border-box",
              borderRadius: 32,
              background: C.card,
              border: `2px solid ${C.line}`,
              display: "flex",
              alignItems: "center",
              gap: 36,
              padding: `0 ${ROW_PAD}px`,
              opacity: clamp01(p * 1.5),
              transform: `translateX(${(1 - p) * -70}px)`,
            }}
          >
            <div
              style={{
                width: CHECK_D,
                height: CHECK_D,
                borderRadius: CHECK_D / 2,
                background: tint(C.green, 0.18),
                border: `4px solid ${C.green}`,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flex: "none",
                transform: `scale(${0.6 + 0.4 * p})`,
              }}
            >
              <Icon name="check" size={56} color={C.green} stroke={5.5} />
            </div>
            <Lines fit={fits[i]} weight={600} lineHeight={1.22} />
          </div>
        );
      })}
    </SceneShell>
  );
};
