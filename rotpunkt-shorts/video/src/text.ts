import { FONT } from "./theme";

let ctx: CanvasRenderingContext2D | null = null;

export const textWidth = (text: string, size: number, weight = 700): number => {
  if (!ctx) ctx = document.createElement("canvas").getContext("2d");
  if (!ctx) return text.length * size * 0.62;
  ctx.font = `${weight} ${size}px "${FONT}"`;
  return ctx.measureText(text).width * 1.01;
};

export type Fit = { size: number; lines: string[] };

/** A word wider than the box is split into hyphenated pieces (long German compounds at the smallest size). */
const breakWord = (word: string, size: number, maxW: number, weight: number): string[] => {
  const parts: string[] = [];
  let cur = "";
  for (const ch of Array.from(word)) {
    if (cur && textWidth(`${cur}${ch}-`, size, weight) > maxW) {
      parts.push(`${cur}-`);
      cur = ch;
    } else {
      cur += ch;
    }
  }
  if (cur) parts.push(cur);
  return parts;
};

export const wrap = (text: string, size: number, maxW: number, weight: number, allowBreak: boolean): { lines: string[]; fits: boolean } => {
  const words = text.trim().split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let fits = true;
  let cur = "";
  for (const word of words) {
    if (textWidth(word, size, weight) > maxW) {
      if (!allowBreak) {
        fits = false;
      } else {
        if (cur) lines.push(cur);
        const parts = breakWord(word, size, maxW, weight);
        cur = parts.pop() ?? "";
        lines.push(...parts);
        continue;
      }
    }
    const next = cur ? `${cur} ${word}` : word;
    if (cur && textWidth(next, size, weight) > maxW) {
      lines.push(cur);
      cur = word;
    } else {
      cur = next;
    }
  }
  if (cur) lines.push(cur);
  return { lines, fits };
};

/** Largest size between max and min at which the text fits maxW in at most maxLines lines without breaking words. */
export const fitText = (text: string, opts: { max: number; min: number; maxW: number; maxLines: number; weight?: number }): Fit => {
  const weight = opts.weight ?? 700;
  for (let size = opts.max; size >= opts.min; size -= 1) {
    const r = wrap(text, size, opts.maxW, weight, false);
    if (r.fits && r.lines.length <= opts.maxLines) return { size, lines: r.lines };
  }
  for (let size = opts.min; size >= 16; size -= 1) {
    const r = wrap(text, size, opts.maxW, weight, true);
    if (r.lines.length <= opts.maxLines) return { size, lines: r.lines };
  }
  return { size: 16, lines: wrap(text, 16, opts.maxW, weight, true).lines };
};
