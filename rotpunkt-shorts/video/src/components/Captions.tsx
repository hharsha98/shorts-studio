import React, { useMemo } from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { C, W, Y } from "../theme";
import { textWidth } from "../text";
import { ease } from "../anim";
import type { CaptionChunk, Word } from "../types";

const MAX_W = 920;
const BASE = 56;
const MIN = 42;
const HOLD = 0.6; // a chunk stays this long after its last word when nothing follows straight away

type Layout = { size: number; lines: Word[][] };

const lineWidth = (words: Word[], size: number): number =>
  words.reduce((s, w, i) => s + textWidth(w.text, size, 700) + (i ? size * 0.26 : 0), 0);

/** One line if it fits at >= 50 px; otherwise two lines split where the longer line is shortest (balanced). */
const layoutChunk = (words: Word[]): Layout => {
  for (let size = BASE; size >= 50; size -= 2) {
    if (lineWidth(words, size) <= MAX_W) return { size, lines: [words] };
  }
  for (let size = BASE; size >= MIN; size -= 2) {
    let best: Word[][] | null = null;
    let bestW = Infinity;
    for (let k = 1; k < words.length; k++) {
      const a = words.slice(0, k);
      const b = words.slice(k);
      const w = Math.max(lineWidth(a, size), lineWidth(b, size));
      if (w <= MAX_W && w < bestW) {
        best = [a, b];
        bestW = w;
      }
    }
    if (best) return { size, lines: best };
  }
  return { size: MIN, lines: [words] };
};

/** Burned-in captions: a short phrase at a time, the spoken word in amber, the rest of the phrase readable ahead. */
export const Captions: React.FC<{ chunks: CaptionChunk[] }> = ({ chunks }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  let index = -1;
  for (let i = 0; i < chunks.length; i++) {
    if (chunks[i].start <= t) index = i;
    else break;
  }
  const chunk = index >= 0 ? chunks[index] : null;
  const next = index + 1 < chunks.length ? chunks[index + 1] : null;
  const visible = chunk !== null && t < Math.min(chunk.end + HOLD, next ? next.start : Infinity);

  const layout = useMemo(() => (chunk ? layoutChunk(chunk.words) : null), [chunk]);
  if (!visible || !chunk || !layout) return null;

  const enter = ease(frame, Math.round(chunk.start * fps), 5);
  const lineH = Math.round(layout.size * 1.22);

  return (
    <div style={{ position: "absolute", left: 0, width: W, top: Y.captionTop, display: "flex", justifyContent: "center" }}>
      <div
        style={{
          padding: "20px 34px 22px",
          borderRadius: 30,
          background: "rgba(5,9,16,0.80)",
          border: "1.5px solid rgba(255,255,255,0.10)",
          boxShadow: "0 18px 50px rgba(0,0,0,0.35)",
          opacity: 0.4 + 0.6 * enter,
          transform: `translateY(${(1 - enter) * 10}px) scale(${0.97 + 0.03 * enter})`,
        }}
      >
        {layout.lines.map((line, li) => (
          <div key={li} style={{ height: lineH, display: "flex", justifyContent: "center", alignItems: "center", whiteSpace: "nowrap" }}>
            {line.map((w, wi) => {
              const active = t >= w.start && t < w.end;
              const spoken = t >= w.end;
              const color = active ? C.amber : spoken ? C.text : "rgba(244,246,250,0.55)";
              return (
                <span key={wi} style={{ fontSize: layout.size, fontWeight: 700, color, marginLeft: wi ? layout.size * 0.26 : 0, lineHeight: 1 }}>
                  {w.text}
                </span>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
};
