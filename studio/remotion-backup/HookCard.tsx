import React, { useMemo } from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import type { CalculateMetadataFunction } from "remotion";
import { FONT_CSS, FONT_FAMILY, useBeVietnamPro } from "./ShortsPanel";

/**
 * Hook card for vertical Shorts (transparent background): two big lines of text in the top third of the frame.
 *
 * The studio pipeline renders ONE track and overlays it at x=0, y=250 of the 1080x1920 frame, so the canvas is only
 * as tall as the text needs (1080x450, i.e. it covers y 250..700). The first frame already shows the complete card with
 * NO pop-in or fade-in: frame 0 of the finished video is the cover image. It stays fully visible until `holdSeconds`
 * and then fades out over `fadeSeconds`.
 *
 * White letters with a thick dark outline and a soft dark shadow stay readable on any footage; the accent word is
 * amber (#FFB000, like the diagram panels). Be Vietnam Pro Bold, centred.
 */

/** A run of text on one line; the accent word is its own run (the spaces around it stay with the plain runs). */
export type HookRun = { text: string; accent: boolean };

export type HookCardProps = {
  /** The two lines, each a list of runs (see studio/captions.py hook_segments). */
  lines: HookRun[][];
  /** Pixels, as picked by make_video.pick_hook_style (it makes the widest line fit into 1000 px). */
  fontSize: number;
  /** Outline width in pixels, drawn OUTSIDE the letters. */
  strokeWidth: number;
  textColor: string;
  strokeColor: string;
  accentColor: string;
  /** The card is fully visible until here (seconds), then fades out. */
  holdSeconds: number;
  fadeSeconds: number;
  /** Total length of the track in seconds (drives the composition length): holdSeconds + fadeSeconds. */
  seconds: number;
};

export const HOOK_FPS = 30; // must match HOOK_FPS in studio/visuals.py
export const HOOK_W = 1080;
export const HOOK_H = 450;

export const hookCardDefaults: HookCardProps = {
  lines: [
    [
      { text: "How does a ", accent: false },
      { text: "microwave", accent: true },
    ],
    [{ text: "actually heat food?", accent: false }],
  ],
  fontSize: 88,
  strokeWidth: 8,
  textColor: "#FFFFFF",
  strokeColor: "#000000",
  accentColor: "#FFB000",
  holdSeconds: 2.5,
  fadeSeconds: 0.25,
  seconds: 2.75,
};

export const calculateHookCardMetadata: CalculateMetadataFunction<HookCardProps> = ({ props }) => {
  const seconds = Number.isFinite(props.seconds) && props.seconds > 0 ? props.seconds : 1;
  return {
    durationInFrames: Math.max(1, Math.round(seconds * HOOK_FPS)),
    defaultCodec: "prores",
    defaultVideoImageFormat: "png",
    defaultPixelFormat: "yuva444p10le",
    defaultProResProfile: "4444",
  };
};

const FONT_FALLBACK = `"${FONT_FAMILY}", "Helvetica Neue", Arial, sans-serif`;
const MAX_LINE_W = 1000; // the widest line (outline included) may never be wider than this
const LINE_PITCH_EM = 1.2; // distance between the two baselines
const CENTRE_EM = 0.35; // baseline sits this far below the visual middle of a line of capitals and lowercase

/** 1 until holdSeconds, then straight down to 0 over fadeSeconds. Frame 0 is always fully visible. */
export const hookOpacity = (t: number, holdSeconds: number, fadeSeconds: number): number => {
  if (t <= holdSeconds) return 1;
  if (fadeSeconds <= 0) return 0;
  return Math.max(0, Math.min(1, 1 - (t - holdSeconds) / fadeSeconds));
};

let measureCtx: CanvasRenderingContext2D | null = null;
const measureWidth = (text: string, size: number): number => {
  if (!measureCtx) measureCtx = document.createElement("canvas").getContext("2d");
  if (!measureCtx) return text.length * size * 0.7; // very conservative fallback
  measureCtx.font = `700 ${size}px "${FONT_FAMILY}"`;
  return measureCtx.measureText(text).width;
};

export const HookCard: React.FC<HookCardProps> = ({
  lines,
  fontSize,
  strokeWidth,
  textColor,
  strokeColor,
  accentColor,
  holdSeconds,
  fadeSeconds,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const fontReady = useBeVietnamPro();
  const t = frame / fps;
  const opacity = hookOpacity(t, holdSeconds, fadeSeconds);

  // Shrink (never grow) when a line is too wide: a safety net, make_video already sized the font to fit.
  const size = useMemo(() => {
    if (!fontReady) return fontSize;
    const widest = Math.max(0, ...lines.map((runs) => measureWidth(runs.map((r) => r.text).join(""), fontSize)));
    if (widest + 2 * strokeWidth <= MAX_LINE_W) return fontSize;
    return Math.max(1, Math.floor((fontSize * (MAX_LINE_W - 2 * strokeWidth)) / widest));
  }, [fontReady, lines, fontSize, strokeWidth]);
  const stroke = Math.max(2, Math.round((strokeWidth * size) / fontSize));

  const cx = HOOK_W / 2;
  const cy = HOOK_H / 2;
  const pitch = size * LINE_PITCH_EM;
  const first = cy - ((lines.length - 1) * pitch) / 2;

  return (
    <AbsoluteFill style={{ fontFamily: FONT_FALLBACK }}>
      <style>{FONT_CSS}</style>
      {fontReady ? (
        <svg width={HOOK_W} height={HOOK_H} viewBox={`0 0 ${HOOK_W} ${HOOK_H}`} style={{ position: "absolute", left: 0, top: 0 }} opacity={opacity}>
          <defs>
            <filter id="hookShadow" x="-10%" y="-30%" width="120%" height="170%">
              <feDropShadow dx="0" dy={Math.round(size * 0.07)} stdDeviation={Math.round(size * 0.07)} floodColor="#000000" floodOpacity="0.7" />
            </filter>
          </defs>
          <g filter="url(#hookShadow)">
            {lines.map((runs, i) => (
              <text
                key={i}
                x={cx}
                y={first + i * pitch + size * CENTRE_EM}
                textAnchor="middle"
                fontFamily={FONT_FALLBACK}
                fontWeight={700}
                fontSize={size}
                fill={textColor}
                stroke={strokeColor}
                strokeWidth={stroke * 2}
                strokeLinejoin="round"
                paintOrder="stroke"
                xmlSpace="preserve"
                style={{ fontKerning: "none", whiteSpace: "pre" }}
              >
                {runs.map((run, k) => (
                  <tspan key={k} fill={run.accent ? accentColor : textColor}>
                    {run.text}
                  </tspan>
                ))}
              </text>
            ))}
          </g>
        </svg>
      ) : null}
    </AbsoluteFill>
  );
};
