import React, { useMemo } from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import type { CalculateMetadataFunction } from "remotion";
import { FONT_CSS, FONT_FAMILY, useBeVietnamPro } from "./ShortsPanel";

/**
 * One-word-at-a-time captions for vertical Shorts (transparent background).
 *
 * The studio pipeline renders ONE track for the whole video and overlays it at x=0, y=1300 of the
 * 1080x1920 frame, so the canvas is only as tall as the captions need (1080x560). The caption box
 * top is the canvas top: everything above y=1300 (the diagram panels) stays free.
 *
 * The look copies what MoneyPrinterTurbo burned in before (white fill, black outline, Be Vietnam Pro
 * Bold, centred, spring pop-in), so the words are now the script's own words but nothing else changes.
 */

export type CaptionWord = { text: string; start: number; end: number };

export type WordCaptionsProps = {
  /** The script's words with their time on the narration timeline, in seconds. Never overlapping. */
  words: CaptionWord[];
  /** Pixels, as picked by make_video.pick_caption_style (it makes the widest word of the script fit). */
  fontSize: number;
  /** Outline width in pixels, drawn OUTSIDE the letters (like the old burned-in captions). */
  strokeWidth: number;
  /** Height of the caption box in pixels (the old MoneyPrinterTurbo box); the pop scales around its centre. */
  boxHeight: number;
  textColor: string;
  strokeColor: string;
  /** Total length of the track in seconds (drives the composition length). */
  seconds: number;
};

export const CAPTION_FPS = 30; // must match CAPTION_FPS in studio/visuals.py
export const CAPTION_W = 1080;
export const CAPTION_H = 560;

export const wordCaptionsDefaults: WordCaptionsProps = {
  words: [
    { text: "Kühlschranks", start: 0.2, end: 0.9 },
    { text: "Trifft", start: 0.9, end: 1.3 },
    { text: "zwängt,", start: 1.3, end: 1.9 },
  ],
  fontSize: 110,
  strokeWidth: 9,
  boxHeight: 223,
  textColor: "#FFFFFF",
  strokeColor: "#000000",
  seconds: 2.5,
};

export const calculateWordCaptionsMetadata: CalculateMetadataFunction<WordCaptionsProps> = ({ props }) => {
  const seconds = Number.isFinite(props.seconds) && props.seconds > 0 ? props.seconds : 1;
  return {
    durationInFrames: Math.max(1, Math.round(seconds * CAPTION_FPS)),
    defaultCodec: "prores",
    defaultVideoImageFormat: "png",
    defaultPixelFormat: "yuva444p10le",
    defaultProResProfile: "4444",
  };
};

// ---------------------------------------------------------------- look (calibrated against the old burned-in captions)
const FONT_FALLBACK = `"${FONT_FAMILY}", "Helvetica Neue", Arial, sans-serif`;
/**
 * Where the old captions put the letters: MoviePy centres the INK height of the word (outline included) in the
 * box, then adds the font ascent. So the baseline is (boxHeight - inkHeight) / 2 + ascent + strokeWidth, and a
 * word without ascenders or descenders sits a little differently from one with both. Copying that rule keeps
 * every word at the same place as before (checked against five real old frames, within 1 to 2 px).
 * Be Vietnam Pro Bold: ascent = 1.000 em (hhea), so the ascent in pixels equals the font size.
 */
const ASCENT_EM = 1.0;
const MAX_TEXT_W = 1000; // a word may never be wider than this at rest (the pop overshoots by about 10%)

const POP_SECONDS = 0.18; // MoneyPrinterTurbo: spring animation length
/** MoneyPrinterTurbo's pop_spring curve: overshoots to about 1.09 and settles at 1.0 within 0.18 s. */
export const popScale = (timeInWord: number, wordSeconds: number): number => {
  const duration = Math.min(POP_SECONDS, Math.max(0, wordSeconds));
  if (duration <= 0 || timeInWord >= duration) return 1;
  const p = Math.max(0, Math.min(timeInWord / duration, 1));
  const scale = 1 - Math.exp(-6 * p) * Math.cos(2.5 * Math.PI * p);
  return Math.max(0.05, Math.min(scale, 1.35));
};

/** The word on screen at time t: start <= t < end (words never overlap, so there is at most one). */
export const activeWord = (words: CaptionWord[], t: number): CaptionWord | null => {
  const eps = 1e-9;
  let lo = 0;
  let hi = words.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const w = words[mid];
    if (t < w.start - eps) hi = mid - 1;
    else if (t >= w.end - eps) lo = mid + 1;
    else return w;
  }
  return null;
};

type Ink = { width: number; ascent: number; descent: number };

let measureCtx: CanvasRenderingContext2D | null = null;
/** Width of the word and how far its letters reach above / below the baseline (without the outline). */
const measureInk = (text: string, size: number): Ink => {
  if (!measureCtx) measureCtx = document.createElement("canvas").getContext("2d");
  if (!measureCtx) return { width: text.length * size * 0.7, ascent: size * 0.8, descent: size * 0.2 }; // very conservative fallback
  measureCtx.font = `700 ${size}px "${FONT_FAMILY}"`;
  const m = measureCtx.measureText(text);
  return { width: m.width, ascent: m.actualBoundingBoxAscent, descent: m.actualBoundingBoxDescent };
};

export const WordCaptions: React.FC<WordCaptionsProps> = ({
  words,
  fontSize,
  strokeWidth,
  boxHeight,
  textColor,
  strokeColor,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const fontReady = useBeVietnamPro();

  const t = frame / fps;
  const word = fontReady ? activeWord(words, t) : null;

  // Shrink a word that is too wide for the frame (never grow): a safety net, make_video already sized the font.
  const layout = useMemo(() => {
    if (!word) return { size: fontSize, baseline: 0 };
    let size = fontSize;
    let ink = measureInk(word.text, size);
    if (ink.width + 2 * strokeWidth > MAX_TEXT_W) {
      size = Math.floor((fontSize * MAX_TEXT_W) / (ink.width + 2 * strokeWidth));
      ink = measureInk(word.text, size);
    }
    const inkHeight = Math.trunc(ink.ascent + ink.descent + 2 * strokeWidth);
    return { size, baseline: (boxHeight - inkHeight) / 2 + size * ASCENT_EM + strokeWidth };
  }, [word, fontSize, strokeWidth, boxHeight]);
  const { size, baseline } = layout;

  const cx = CAPTION_W / 2;
  const cy = boxHeight / 2; // the pop scales around the centre of the caption box
  const scale = word ? popScale(t - word.start, word.end - word.start) : 1;

  return (
    <AbsoluteFill style={{ fontFamily: FONT_FALLBACK }}>
      <style>{FONT_CSS}</style>
      {word ? (
        <svg width={CAPTION_W} height={CAPTION_H} viewBox={`0 0 ${CAPTION_W} ${CAPTION_H}`} style={{ position: "absolute", left: 0, top: 0 }}>
          <g transform={`translate(${cx} ${cy}) scale(${scale}) translate(${-cx} ${-cy})`}>
            <text
              x={cx}
              y={baseline}
              textAnchor="middle"
              fontFamily={FONT_FALLBACK}
              fontWeight={700}
              fontSize={size}
              fill={textColor}
              stroke={strokeColor}
              strokeWidth={strokeWidth * 2}
              strokeLinejoin="round"
              paintOrder="stroke"
              style={{ fontKerning: "none" }}
            >
              {word.text}
            </text>
          </g>
        </svg>
      ) : null}
    </AbsoluteFill>
  );
};
