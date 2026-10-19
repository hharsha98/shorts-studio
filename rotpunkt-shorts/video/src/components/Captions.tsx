import React, { useMemo } from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { C, W, Y, tint } from "../theme";
import { textWidth } from "../text";
import { clamp01, ease, lerp, pop } from "../anim";
import type { CaptionChunk, Word } from "../types";

const MAX_W = 930;
const BASE = 60;
const MIN = 44;
const WEIGHT = 800;
const HOLD = 0.6; // a phrase stays this long after its last word when nothing follows straight away
const PAD_X = 30;
const PAD_Y = 16;
const SLIDE_FRAMES = 4;

type Placed = { word: Word; x: number; width: number; line: number };
type Layout = { size: number; lineW: number[]; words: Placed[] };

const gapOf = (size: number) => size * 0.3;
const widthOf = (words: Word[], size: number): number =>
  words.reduce((s, w, i) => s + textWidth(w.text, size, WEIGHT) + (i ? gapOf(size) : 0), 0);

const place = (lines: Word[][], size: number): Layout => {
  const words: Placed[] = [];
  const lineW = lines.map((ln) => widthOf(ln, size));
  lines.forEach((ln, li) => {
    let x = 0;
    for (const w of ln) {
      const width = textWidth(w.text, size, WEIGHT);
      words.push({ word: w, x, width, line: li });
      x += width + gapOf(size);
    }
  });
  return { size, lineW, words };
};

/** One line if it fits at >= 52 px; otherwise two lines split where the longer one is shortest (balanced). */
const layoutChunk = (words: Word[]): Layout => {
  for (let size = BASE; size >= 52; size -= 2) {
    if (widthOf(words, size) <= MAX_W) return place([words], size);
  }
  for (let size = BASE; size >= MIN; size -= 2) {
    let best: Word[][] | null = null;
    let bestW = Infinity;
    for (let k = 1; k < words.length; k++) {
      const a = words.slice(0, k);
      const b = words.slice(k);
      const w = Math.max(widthOf(a, size), widthOf(b, size));
      if (w <= MAX_W && w < bestW) {
        best = [a, b];
        bestW = w;
      }
    }
    if (best) return place(best, size);
  }
  return place([words], MIN);
};

/**
 * Word-by-word karaoke captions: the phrase is on screen, the spoken word sits on an amber pill that slides from word to word
 * exactly on the voice's word timings and pops slightly as it lands; words already spoken are white, the rest wait dimmed.
 */
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

  const { size, lineW, words } = layout;
  const lineH = Math.round(size * 1.34);
  const maxW = Math.max(...lineW);
  const panelW = maxW + PAD_X * 2;
  const panelH = lineH * lineW.length + PAD_Y * 2;
  const lineX = (li: number) => PAD_X + (maxW - lineW[li]) / 2;
  const enter = ease(frame, Math.round(chunk.start * fps), 5);

  // the pill stays on the latest word that has started, so short gaps between words never make it flicker
  let cur = -1;
  words.forEach((p, i) => {
    if (p.word.start <= t) cur = i;
  });
  let pill: React.ReactNode = null;
  if (cur >= 0) {
    const c = words[cur];
    const startF = Math.round(c.word.start * fps);
    const prev = cur > 0 && words[cur - 1].line === c.line ? words[cur - 1] : null;
    const slide = prev ? ease(frame, startF, SLIDE_FRAMES) : 1;
    const x = prev ? lerp(prev.x, c.x, slide) : c.x;
    const w = prev ? lerp(prev.width, c.width, slide) : c.width;
    const grow = prev ? 1 : 0.6 + 0.4 * pop(frame, startF, fps, 260, 14);
    const padX = size * 0.2;
    const pillH = size * 1.2;
    pill = (
      <div
        style={{
          position: "absolute",
          left: lineX(c.line) + x - padX,
          top: PAD_Y + c.line * lineH + (lineH - pillH) / 2,
          width: w + padX * 2,
          height: pillH,
          borderRadius: pillH * 0.32,
          background: C.amber,
          boxShadow: `0 6px 22px ${tint(C.amber, 0.45)}`,
          transform: `scale(${grow})`,
        }}
      />
    );
  }

  return (
    <div style={{ position: "absolute", left: 0, width: W, top: Y.captionTop, display: "flex", justifyContent: "center" }}>
      <div
        style={{
          position: "relative",
          width: panelW,
          height: panelH,
          borderRadius: 30,
          background: "rgba(5,9,16,0.82)",
          border: "1.5px solid rgba(255,255,255,0.10)",
          boxShadow: "0 18px 50px rgba(0,0,0,0.35)",
          opacity: 0.35 + 0.65 * enter,
          transform: `translateY(${(1 - enter) * 12}px) scale(${0.96 + 0.04 * enter})`,
        }}
      >
        {pill}
        {words.map((p, i) => {
          const startF = Math.round(p.word.start * fps);
          const isCur = i === cur;
          const spoken = i < cur;
          const land = isCur ? ease(frame, startF, 6) : 1;
          const scale = isCur ? 1.12 - 0.12 * land : 1;
          const color = isCur ? C.ink : spoken ? C.text : "rgba(244,246,250,0.45)";
          return (
            <div
              key={i}
              style={{
                position: "absolute",
                left: lineX(p.line) + p.x,
                top: PAD_Y + p.line * lineH,
                width: p.width,
                height: lineH,
                lineHeight: `${lineH}px`,
                fontSize: size,
                fontWeight: WEIGHT,
                color,
                whiteSpace: "nowrap",
                textAlign: "center",
                transform: `scale(${scale})`,
                opacity: isCur || spoken ? 1 : clamp01(0.6 + 0.4 * enter),
              }}
            >
              {p.word.text}
            </div>
          );
        })}
      </div>
    </div>
  );
};
