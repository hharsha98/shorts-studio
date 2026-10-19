import React, { useMemo } from "react";
import { C, CONTENT_W, MARGIN, Y, tint } from "../theme";
import { fitText, textWidth } from "../text";
import { clamp01, ease, pop } from "../anim";
import { Icon } from "../icons";
import { Lines, SceneShell, SceneTitle, titleHeight, useTitleFit } from "../components/Scene";
import type { Labels, SceneCtx } from "../types";

const BAR_MAX = 600;
const BAR_H = 74;
const BAR_GAP = 18;
const ITEM_GAP = 76;
const VALUE_SIZE = 46;

const format = (n: number, unit: string): string => {
  const s = String(Math.round(n));
  return unit ? `${s} ${unit}` : s;
};

export const MetricsScene: React.FC<{ ctx: SceneCtx; m: Labels["metrics"] }> = ({ ctx, m }) => {
  const { frame, fps } = ctx;
  const titleFit = useTitleFit(m.title, 64);
  const labelFits = useMemo(() => m.items.map((it) => fitText(it.label, { max: 42, min: 30, maxW: CONTENT_W, maxLines: 2, weight: 700 })), [m.items]);
  const footFit = useMemo(() => fitText(m.footnote, { max: 30, min: 22, maxW: CONTENT_W - 56, maxLines: 2, weight: 500 }), [m.footnote]);
  const stampW = textWidth(m.stamp, 36, 800) + m.stamp.length * 5 + 56;
  const stampP = pop(frame, ctx.start + 6, fps, 200, 14);

  const itemH = (i: number) => Math.round(labelFits[i].lines.length * labelFits[i].size * 1.2) + 20 + BAR_H * 2 + BAR_GAP;
  const blockH = 84 + 30 + 44 + 56 + m.items.reduce((s, _, i) => s + itemH(i), 0) + ITEM_GAP * (m.items.length - 1) + 60 + footFit.lines.length * footFit.size * 1.3;
  const areaTop = Y.sceneTop + titleHeight(titleFit) + 20;
  const top0 = Math.round(areaTop + Math.max(0, (Y.sceneBottom - areaTop - blockH) / 2));
  const legendTop = top0 + 84 + 30;
  const tops: number[] = [];
  let y = legendTop + 44 + 56;
  m.items.forEach((_, i) => {
    tops.push(y);
    y += itemH(i) + ITEM_GAP;
  });
  const footTop = y - ITEM_GAP + 60;

  return (
    <SceneShell ctx={ctx}>
      <SceneTitle ctx={ctx} fit={titleFit} />
      <div
        style={{
          position: "absolute",
          left: MARGIN,
          top: top0,
          width: stampW,
          height: 84,
          boxSizing: "border-box",
          border: `5px solid ${C.amber}`,
          borderRadius: 14,
          background: tint(C.amber, 0.1),
          color: C.amber,
          fontSize: 36,
          fontWeight: 800,
          letterSpacing: 5,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          opacity: clamp01(stampP * 2),
          transform: `rotate(-4deg) scale(${1.5 - 0.5 * stampP})`,
          transformOrigin: "left center",
        }}
      >
        {m.stamp}
      </div>
      <div style={{ position: "absolute", left: MARGIN, top: legendTop, display: "flex", gap: 36, alignItems: "center", fontSize: 30, fontWeight: 600, color: C.sub }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ width: 30, height: 30, borderRadius: 8, background: C.slate }} />
          {m.legend[0]}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ width: 30, height: 30, borderRadius: 8, background: C.amber }} />
          {m.legend[1]}
        </div>
      </div>
      {m.items.map((it, i) => {
        const at = ctx.cue(`metrics.${i}`, ctx.start + 12 + i * 30);
        const appear = pop(frame, at - 4, fps, 160, 17);
        const g1 = ease(frame, at, 16);
        const g2 = ease(frame, at + 10, 22);
        const max = Math.max(it.before, it.after);
        const w1 = (BAR_MAX * it.before) / max;
        const w2 = (BAR_MAX * it.after) / max;
        const barTop = tops[i] + Math.round(labelFits[i].lines.length * labelFits[i].size * 1.2) + 20;
        return (
          <div key={i} style={{ opacity: clamp01(appear * 1.5) }}>
            <div style={{ position: "absolute", left: MARGIN, top: tops[i], width: CONTENT_W }}>
              <Lines fit={labelFits[i]} weight={700} lineHeight={1.2} />
            </div>
            <div style={{ position: "absolute", left: MARGIN, top: barTop, width: w1 * g1, height: BAR_H, borderRadius: 16, background: C.slate }} />
            <div
              style={{
                position: "absolute",
                left: MARGIN + w1 * g1 + 22,
                top: barTop,
                height: BAR_H,
                display: "flex",
                alignItems: "center",
                fontSize: VALUE_SIZE,
                fontWeight: 800,
                color: C.sub,
                opacity: g1,
                whiteSpace: "nowrap",
              }}
            >
              {format(it.before * g1, it.unit)}
            </div>
            <div
              style={{
                position: "absolute",
                left: MARGIN,
                top: barTop + BAR_H + BAR_GAP,
                width: w2 * g2,
                height: BAR_H,
                borderRadius: 16,
                background: `linear-gradient(90deg, ${C.amber} 0%, #FFC94D 100%)`,
                boxShadow: `0 0 30px ${tint(C.amber, 0.32)}`,
              }}
            />
            <div
              style={{
                position: "absolute",
                left: MARGIN + w2 * g2 + 22,
                top: barTop + BAR_H + BAR_GAP,
                height: BAR_H,
                display: "flex",
                alignItems: "center",
                fontSize: VALUE_SIZE,
                fontWeight: 800,
                color: C.amber,
                opacity: g2,
                whiteSpace: "nowrap",
              }}
            >
              {format(it.before + (it.after - it.before) * g2, it.unit)}
            </div>
          </div>
        );
      })}
      <div style={{ position: "absolute", left: MARGIN, top: footTop, width: CONTENT_W, display: "flex", gap: 16, alignItems: "flex-start", opacity: ease(frame, ctx.start + 14, 12) }}>
        <Icon name="info" size={40} color={C.sub} />
        <Lines fit={footFit} weight={500} color={C.sub} lineHeight={1.3} />
      </div>
    </SceneShell>
  );
};
