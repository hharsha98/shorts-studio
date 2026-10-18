import React, { useMemo } from "react";
import { C, CONTENT_W, MARGIN, Y } from "../theme";
import { fitText } from "../text";
import { clamp01, ease, pop } from "../anim";
import { Lines, SceneShell, SceneTitle, titleHeight, useTitleFit } from "../components/Scene";
import type { Labels, SceneCtx } from "../types";

const PAD_X = 34;
const PAD_Y = 24;
const TEXT_W = CONTENT_W - PAD_X * 2 - 10;
const GAP = 24;

export const EvidenceScene: React.FC<{ ctx: SceneCtx; ev: Labels["evidence"] }> = ({ ctx, ev }) => {
  const titleFit = useTitleFit(ev.title);
  const cards = useMemo(
    () =>
      ev.cards.map((c) => {
        const role = fitText(c.role, { max: 27, min: 21, maxW: TEXT_W, maxLines: 1, weight: 700 });
        const quote = fitText(c.quote, { max: 40, min: 31, maxW: TEXT_W, maxLines: 3, weight: 600 });
        const gist = c.gist ? fitText(c.gist, { max: 31, min: 25, maxW: TEXT_W, maxLines: 2, weight: 500 }) : null;
        const height = Math.round(
          PAD_Y * 2 + role.size * 1.2 + 12 + quote.lines.length * quote.size * 1.24 + (gist ? 10 + gist.lines.length * gist.size * 1.25 : 0) + 4,
        );
        return { role, quote, gist, height };
      }),
    [ev.cards],
  );
  const top0 = Y.sceneTop + titleHeight(titleFit) + 36;
  const tops: number[] = [];
  let y = top0;
  for (const c of cards) {
    tops.push(y);
    y += c.height + GAP;
  }
  const noteTop = y + 6;
  const lastAt = ctx.cue(`evidence.${cards.length - 1}`, ctx.start + 40);

  return (
    <SceneShell ctx={ctx}>
      <SceneTitle ctx={ctx} fit={titleFit} />
      {cards.map((c, i) => {
        const at = ctx.cue(`evidence.${i}`, ctx.start + 10 + i * 18);
        const p = pop(ctx.frame, at, ctx.fps, 160, 17);
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: MARGIN,
              top: tops[i],
              width: CONTENT_W,
              height: c.height,
              boxSizing: "border-box",
              padding: `${PAD_Y}px ${PAD_X}px`,
              borderRadius: 26,
              background: C.card,
              border: `2px solid ${C.line}`,
              borderLeft: `8px solid ${C.amber}`,
              opacity: clamp01(p * 1.5),
              transform: `translateX(${(1 - p) * 90}px)`,
            }}
          >
            <Lines fit={c.role} weight={700} color={C.amber} lineHeight={1.2} />
            <div style={{ height: 12 }} />
            <Lines fit={c.quote} weight={600} lineHeight={1.24} />
            {c.gist ? (
              <>
                <div style={{ height: 10 }} />
                <Lines fit={c.gist} weight={500} color={C.sub} lineHeight={1.25} />
              </>
            ) : null}
          </div>
        );
      })}
      <div
        style={{
          position: "absolute",
          left: MARGIN,
          top: noteTop,
          width: CONTENT_W,
          textAlign: "center",
          color: C.faint,
          fontSize: 26,
          fontWeight: 500,
          opacity: ease(ctx.frame, lastAt + 6, 12),
        }}
      >
        {ev.note}
      </div>
    </SceneShell>
  );
};
