import React, { useMemo } from "react";
import { C, CONTENT_W, MARGIN, Y, tint } from "../theme";
import { fitText, textWidth } from "../text";
import type { Fit } from "../text";
import { clamp01, ease, pop } from "../anim";
import { Lines, SceneShell } from "../components/Scene";
import type { Labels, SceneCtx } from "../types";

const PAD = 44;
const INNER = CONTENT_W - PAD * 2;
const COL_GAP = 24;
const COL_W = (INNER - COL_GAP) / 2;
const FACT_PAD = 22;

type FactLayout = { value: Fit; label: Fit; wide: boolean };

export const ProofScene: React.FC<{ ctx: SceneCtx; proof: Labels["proof"] }> = ({ ctx, proof }) => {
  const { frame, fps } = ctx;
  const head = useMemo(() => {
    const badgeW = textWidth(proof.badge, 24, 800) + 48 + proof.badge.length * 2;
    return {
      badgeW,
      kicker: fitText(proof.kicker, { max: 34, min: 24, maxW: INNER - badgeW - 20, maxLines: 1, weight: 700 }),
      title: fitText(proof.title, { max: 54, min: 34, maxW: INNER, maxLines: 3, weight: 800 }),
      sub: fitText(proof.sub, { max: 30, min: 22, maxW: INNER, maxLines: 2, weight: 500 }),
      source: fitText(proof.source, { max: 24, min: 19, maxW: INNER, maxLines: 2, weight: 500 }),
    };
  }, [proof]);
  const facts: FactLayout[] = useMemo(
    () =>
      proof.facts.map((f) => {
        const w = (f.wide ? INNER : COL_W) - FACT_PAD * 2;
        const value = fitText(f.value, { max: f.wide ? 66 : 60, min: 34, maxW: w, maxLines: 1, weight: 800 });
        const label = fitText(f.label, { max: 28, min: 22, maxW: w, maxLines: 2, weight: 500 });
        return { value, label, wide: !!f.wide };
      }),
    [proof.facts],
  );
  // rows: a wide fact fills its row, normal facts pair up
  const rows: number[][] = [];
  let pending: number[] = [];
  facts.forEach((f, i) => {
    if (f.wide) {
      if (pending.length) rows.push(pending);
      pending = [];
      rows.push([i]);
    } else {
      pending.push(i);
      if (pending.length === 2) {
        rows.push(pending);
        pending = [];
      }
    }
  });
  if (pending.length) rows.push(pending);
  const rowH = rows.map((r) =>
    Math.max(...r.map((i) => Math.round(FACT_PAD * 2 + facts[i].value.size * 1.08 + 8 + facts[i].label.lines.length * facts[i].label.size * 1.22))),
  );
  const factsH = rowH.reduce((s, h) => s + h, 0) + (rows.length - 1) * 20;
  const headH = 56 + 22 + head.title.lines.length * head.title.size * 1.1 + 10 + head.sub.lines.length * head.sub.size * 1.25 + 30;
  const cardH = Math.round(PAD + headH + factsH + 28 + head.source.lines.length * head.source.size * 1.3 + PAD);
  const top = Math.round((Y.sceneTop + 30 + Y.sceneBottom - cardH) / 2);
  const at = ctx.cue("proof", ctx.start + 4);
  const cardP = pop(frame, at - 6, fps, 140, 17);
  // the fact the narrator is saying right now (cues "proof.fact.<i>" from the script) gets an amber highlight
  let focus = -1;
  let focusAt = -1;
  proof.facts.forEach((_, i) => {
    const c = ctx.cue(`proof.fact.${i}`, -1);
    if (c >= 0 && frame >= c && c > focusAt) {
      focus = i;
      focusAt = c;
    }
  });
  const focusP = focus >= 0 ? ease(frame, focusAt, 6) : 0;

  return (
    <SceneShell ctx={ctx}>
      <div
        style={{
          position: "absolute",
          left: MARGIN,
          top,
          width: CONTENT_W,
          height: cardH,
          boxSizing: "border-box",
          padding: PAD,
          borderRadius: 36,
          background: "rgba(16,26,42,0.92)",
          border: `2.5px solid ${tint(C.green, 0.45)}`,
          boxShadow: `0 0 60px ${tint(C.green, 0.12)}, 0 24px 60px rgba(0,0,0,0.4)`,
          opacity: clamp01(cardP * 1.5),
          transform: `scale(${0.92 + 0.08 * cardP})`,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", height: 56 }}>
          <Lines fit={head.kicker} weight={700} color={C.sub} />
          <div style={{ flex: 1 }} />
          <div
            style={{
              height: 50,
              width: head.badgeW,
              borderRadius: 25,
              background: tint(C.green, 0.18),
              border: `2px solid ${C.green}`,
              color: C.green,
              fontSize: 24,
              fontWeight: 800,
              letterSpacing: 2,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            {proof.badge}
          </div>
        </div>
        <div style={{ height: 22 }} />
        <Lines fit={head.title} weight={800} lineHeight={1.1} />
        <div style={{ height: 10 }} />
        <Lines fit={head.sub} weight={500} color={C.sub} lineHeight={1.25} />
        <div style={{ height: 30 }} />
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {rows.map((r, ri) => (
            <div key={ri} style={{ display: "flex", gap: COL_GAP, height: rowH[ri] }}>
              {r.map((i) => {
                const f = facts[i];
                const q = pop(frame, at + 6 + i * 6, fps, 170, 15);
                const hi = i === focus ? focusP : 0;
                return (
                  <div
                    key={i}
                    style={{
                      width: f.wide ? INNER : COL_W,
                      boxSizing: "border-box",
                      padding: FACT_PAD,
                      borderRadius: 22,
                      background: hi > 0 ? tint(C.amber, 0.05 + 0.07 * hi) : "rgba(255,255,255,0.05)",
                      border: `2px solid ${hi > 0 ? tint(C.amber, 0.3 + 0.7 * hi) : C.line}`,
                      boxShadow: hi > 0 ? `0 0 ${28 * hi}px ${tint(C.amber, 0.3)}` : "none",
                      opacity: clamp01(q * 1.5),
                      transform: `translateY(${(1 - q) * 20}px) scale(${1 + 0.02 * hi})`,
                    }}
                  >
                    <Lines fit={f.value} weight={800} color={C.amber} lineHeight={1.08} />
                    <div style={{ height: 8 }} />
                    <Lines fit={f.label} weight={500} color={C.sub} lineHeight={1.22} />
                  </div>
                );
              })}
            </div>
          ))}
        </div>
        <div style={{ height: 28 }} />
        <Lines fit={head.source} weight={500} color={C.faint} lineHeight={1.3} />
      </div>
    </SceneShell>
  );
};
