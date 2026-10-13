import React, { useEffect, useMemo, useState } from "react";
import {
  AbsoluteFill,
  Easing,
  cancelRender,
  continueRender,
  delayRender,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { CalculateMetadataFunction } from "remotion";

/**
 * Animated explainer panel for vertical Shorts (1080x1080, transparent background).
 * The studio pipeline renders one panel per spoken line and overlays it on the video.
 * Three layouts: "flow" (steps with arrows), "stat" (one big number), "compare" (myth vs fact).
 */

export type FlowVisual = { type: "flow"; title: string; steps: string[] };
export type StatVisual = { type: "stat"; value: string; label: string };
export type CompareSide = { heading: string; text: string };
export type CompareVisual = { type: "compare"; title: string; left: CompareSide; right: CompareSide };
export type PanelVisual = FlowVisual | StatVisual | CompareVisual;

export type ShortsPanelProps = {
  visual: PanelVisual;
  /** Total length of the panel in seconds (drives the composition length). */
  seconds: number;
  lang: "en" | "de";
};

export const PANEL_FPS = 30;

export const shortsPanelDefaults: ShortsPanelProps = {
  visual: {
    type: "flow",
    title: "How a fridge cools",
    steps: ["Compressor squeezes gas", "Hot gas loses heat", "Gas expands and chills", "Inside heat is absorbed"],
  },
  seconds: 5,
  lang: "en",
};

export const calculateShortsPanelMetadata: CalculateMetadataFunction<ShortsPanelProps> = ({ props }) => {
  const seconds = Number.isFinite(props.seconds) && props.seconds > 0 ? props.seconds : 2;
  return {
    durationInFrames: Math.max(1, Math.round(seconds * PANEL_FPS)),
    // Handy defaults when exporting from the Studio: a transparent ProRes file.
    defaultCodec: "prores",
    defaultVideoImageFormat: "png",
    defaultPixelFormat: "yuva444p10le",
    defaultProResProfile: "4444",
  };
};

// ---------------------------------------------------------------- design tokens
const ACCENT = "#FFB000";
const INK = "#0E1116";
const CARD_BG = "rgba(14,17,22,0.88)";
const FONT_FAMILY = "Be Vietnam Pro";
const FONT_FALLBACK = `"${FONT_FAMILY}", "Helvetica Neue", Arial, sans-serif`;
const CARD_W = 1032; // 24 px margin each side on the 1080 canvas
const CARD_PAD_X = 40;
const CARD_PAD_Y = 48;
const INNER_W = CARD_W - CARD_PAD_X * 2; // 952
const CARD_RADIUS = 48;
const ENTER_FRAMES = 10;
const EXIT_FRAMES = 8;

// ---------------------------------------------------------------- font loading
const FONT_CSS = `@font-face{font-family:"${FONT_FAMILY}";src:url(${staticFile(
  "fonts/BeVietnamPro-Bold.ttf",
)}) format("truetype");font-weight:700;font-style:normal;font-display:block;}`;

/** Loads the font before the first frame is captured (delayRender holds the screenshot). */
const useBeVietnamPro = (): boolean => {
  const [handle] = useState(() => delayRender("Loading Be Vietnam Pro Bold"));
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    document.fonts
      .load(`700 48px "${FONT_FAMILY}"`, "AaÄäÖöÜüß°−%0123456789")
      .then(() => {
        if (!cancelled) setReady(true);
      })
      .catch((err: unknown) => cancelRender(err));
    return () => {
      cancelled = true;
    };
  }, []);

  // Release the render only after React has committed the "ready" frame to the DOM.
  useEffect(() => {
    if (ready) continueRender(handle);
  }, [ready, handle]);

  return ready;
};

// ---------------------------------------------------------------- text fitting
let measureCtx: CanvasRenderingContext2D | null = null;
const textWidth = (text: string, size: number): number => {
  if (!measureCtx) measureCtx = document.createElement("canvas").getContext("2d");
  if (!measureCtx) return text.length * size * 0.7; // very conservative fallback
  measureCtx.font = `700 ${size}px "${FONT_FAMILY}"`;
  return measureCtx.measureText(text).width * 1.015; // small safety margin
};

type Fit = { size: number; lines: string[] };

/** Splits a word that is wider than the box into pieces with trailing hyphens. */
const breakWord = (word: string, size: number, maxW: number): string[] => {
  const parts: string[] = [];
  let cur = "";
  for (const ch of Array.from(word)) {
    if (cur && textWidth(`${cur}${ch}-`, size) > maxW) {
      parts.push(`${cur}-`);
      cur = ch;
    } else {
      cur += ch;
    }
  }
  if (cur) parts.push(cur);
  return parts;
};

const wrap = (text: string, size: number, maxW: number, allowBreak: boolean): { lines: string[]; fits: boolean } => {
  const words = text.trim().split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let fits = true;
  let cur = "";
  for (const word of words) {
    if (textWidth(word, size) > maxW) {
      if (!allowBreak) {
        fits = false;
      } else {
        if (cur) lines.push(cur);
        const parts = breakWord(word, size, maxW);
        cur = parts.pop() ?? "";
        lines.push(...parts);
        continue;
      }
    }
    const next = cur ? `${cur} ${word}` : word;
    if (cur && textWidth(next, size) > maxW) {
      lines.push(cur);
      cur = word;
    } else {
      cur = next;
    }
  }
  if (cur) lines.push(cur);
  return { lines, fits };
};

/**
 * Largest font size (between min and max) at which the text fits the width in at most maxLines lines
 * without breaking words. If even the minimum size cannot do that (very long German compounds),
 * the word is hyphen-broken instead, so text can never overflow its box.
 * When maxH is given, a size is only accepted if lines * size * lineHeight also fits that height
 * (so two wrapped lines shrink until they fit a short box, instead of spilling over its border).
 */
const fitText = (
  text: string,
  max: number,
  min: number,
  maxW: number,
  maxLines: number,
  maxH: number = Infinity,
  lineHeight: number = 1.14,
): Fit => {
  const tallEnough = (lines: number, size: number) => lines * size * lineHeight <= maxH;
  for (let size = max; size >= min; size -= 1) {
    const r = wrap(text, size, maxW, false);
    if (r.fits && r.lines.length <= maxLines && tallEnough(r.lines.length, size)) return { size, lines: r.lines };
  }
  for (let size = min; size >= 20; size -= 1) {
    const r = wrap(text, size, maxW, true);
    if (r.lines.length <= maxLines && tallEnough(r.lines.length, size)) return { size, lines: r.lines };
  }
  return { size: 20, lines: wrap(text, 20, maxW, true).lines };
};

const FitText: React.FC<{
  fit: Fit;
  color?: string;
  align?: "left" | "center";
  lineHeight?: number;
}> = ({ fit, color = "#FFFFFF", align = "left", lineHeight = 1.14 }) => (
  <div style={{ fontSize: fit.size, lineHeight, color, textAlign: align, fontWeight: 700 }}>
    {fit.lines.map((line, i) => (
      <div key={i} style={{ whiteSpace: "nowrap" }}>
        {line}
      </div>
    ))}
  </div>
);

// ---------------------------------------------------------------- motion helpers
const enter = (frame: number, start: number, fps: number, duration = 12): number =>
  spring({
    frame: Math.max(0, frame - start),
    fps,
    config: { damping: 15, stiffness: 170, mass: 0.7 },
    durationInFrames: duration,
  });

const smooth = (frame: number, start: number, fps: number, duration = 12): number =>
  spring({
    frame: Math.max(0, frame - start),
    fps,
    config: { damping: 200 },
    durationInFrames: duration,
  });

const clamp01 = (n: number): number => Math.min(1, Math.max(0, n));

// ---------------------------------------------------------------- small pieces
const AccentBar: React.FC<{ progress?: number }> = ({ progress = 1 }) => (
  <div style={{ width: 96 * progress, height: 8, borderRadius: 4, background: ACCENT }} />
);

const Arrow: React.FC<{ height: number; progress: number }> = ({ height, progress }) => {
  const p = clamp01(progress);
  // Not started yet: draw nothing (a 0-length line with a round cap would show as a stray dot).
  if (p <= 0.01) return <div style={{ width: 48, height }} />;
  const y = 5 + (height - 12) * p;
  return (
    <svg
      width={48}
      height={height}
      viewBox={`0 0 48 ${height}`}
      style={{ display: "block", overflow: "visible", opacity: clamp01(p * 4) }}
    >
      <line x1={24} y1={3} x2={24} y2={y} stroke={ACCENT} strokeWidth={7} strokeLinecap="round" />
      <polyline
        points={`10,${y - 12} 24,${y + 2} 38,${y - 12}`}
        fill="none"
        stroke={ACCENT}
        strokeWidth={7}
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity={clamp01(p * 2 - 0.4)}
      />
    </svg>
  );
};

const Icon: React.FC<{ kind: "cross" | "check"; color: string }> = ({ kind, color }) => (
  <svg width={44} height={44} viewBox="0 0 44 44" style={{ display: "block", flex: "none" }}>
    <circle cx={22} cy={22} r={22} fill={color} />
    {kind === "check" ? (
      <polyline points="12,23 19,30 32,15" fill="none" stroke={INK} strokeWidth={5} strokeLinecap="round" strokeLinejoin="round" />
    ) : (
      <g stroke={INK} strokeWidth={5} strokeLinecap="round">
        <line x1={14} y1={14} x2={30} y2={30} />
        <line x1={30} y1={14} x2={14} y2={30} />
      </g>
    )}
  </svg>
);

// ---------------------------------------------------------------- flow
const FlowView: React.FC<{ visual: FlowVisual; frame: number; total: number; fps: number }> = ({
  visual,
  frame,
  total,
  fps,
}) => {
  const n = visual.steps.length;
  const chipH = n <= 3 ? 116 : n === 4 ? 104 : 92;
  const arrowH = n <= 3 ? 60 : n === 4 ? 48 : 42;
  const chipMax = n <= 3 ? 54 : n === 4 ? 50 : 46;
  const textW = INNER_W - 2 * 30 - 64 - 24 - 6; // chip padding, badge, gap, border

  const titleFit = useMemo(() => fitText(visual.title, 60, 38, INNER_W, 2), [visual.title]);
  // The chip has a 3 px border on each side, so the text box is chipH - 6 tall; line height is 1.1.
  const stepFits = useMemo(
    () => visual.steps.map((s) => fitText(s, chipMax, 30, textW, 2, chipH - 6, 1.1)),
    [visual.steps, chipMax, chipH, textW],
  );

  // Steps appear one by one, evenly spread over the first 70% of the panel.
  const first = 8;
  const spread = Math.max(1, total * 0.7 - first);
  const stepStart = (i: number) => first + Math.round((i * spread) / n);

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "stretch" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 20, alignItems: "flex-start", marginBottom: 32 }}>
        <FitText fit={titleFit} lineHeight={1.12} />
        <AccentBar progress={smooth(frame, 2, fps, 14)} />
      </div>
      {visual.steps.map((step, i) => {
        const p = enter(frame, stepStart(i), fps, 12);
        const last = i === n - 1;
        return (
          <React.Fragment key={i}>
            <div
              style={{
                height: chipH,
                boxSizing: "border-box",
                display: "flex",
                alignItems: "center",
                gap: 24,
                padding: "0 30px",
                borderRadius: 30,
                background: last ? "rgba(255,176,0,0.14)" : "rgba(255,255,255,0.08)",
                border: `3px solid ${last ? ACCENT : "rgba(255,255,255,0.16)"}`,
                opacity: clamp01(p * 1.4),
                transform: `translateY(${(1 - p) * 26}px) scale(${0.92 + 0.08 * p})`,
              }}
            >
              <div
                style={{
                  width: 64,
                  height: 64,
                  flex: "none",
                  borderRadius: 32,
                  background: ACCENT,
                  color: INK,
                  fontSize: 36,
                  fontWeight: 700,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  lineHeight: 1,
                }}
              >
                {i + 1}
              </div>
              <FitText fit={stepFits[i]} lineHeight={1.1} />
            </div>
            {i < n - 1 ? (
              <div style={{ height: arrowH, display: "flex", justifyContent: "center" }}>
                <Arrow height={arrowH} progress={smooth(frame, stepStart(i + 1) - 4, fps, 12)} />
              </div>
            ) : null}
          </React.Fragment>
        );
      })}
    </div>
  );
};

// ---------------------------------------------------------------- stat
const PLAIN_NUMBER = /^(-?)(\d+)(?:([.,])(\d+))?$/;

/** A leading hyphen before a digit becomes a real minus sign, which is wider and sits at digit height. */
const toDisplay = (value: string): string => value.replace(/^-(?=\d)/, "\u2212");

const countUpText = (value: string, progress: number, lang: "en" | "de"): string => {
  const m = PLAIN_NUMBER.exec(value.trim());
  if (!m || progress >= 1) return value;
  const [, sign, intPart, sep, frac] = m;
  // "1,000" (English) or "1.000" (German): exactly 3 digits after that language's thousands separator
  // is a thousands group, not decimals. Count the whole number up and put the separator back.
  const thousandsSep = lang === "de" ? "." : ",";
  if (sep === thousandsSep && frac && frac.length === 3 && /^[1-9]\d{0,2}$/.test(intPart)) {
    const n = Math.round(Number(`${intPart}${frac}`) * progress);
    const digits = String(n);
    const grouped = digits.length > 3 ? `${digits.slice(0, -3)}${sep}${digits.slice(-3)}` : digits;
    return `${sign && n !== 0 ? sign : ""}${grouped}`;
  }
  const decimals = frac ? frac.length : 0;
  const target = parseFloat(`${intPart}${frac ? `.${frac}` : ""}`);
  const current = target * progress;
  const body = current.toFixed(decimals).replace(".", sep ?? ".");
  const isZero = Number(current.toFixed(decimals)) === 0;
  return `${sign && !isZero ? sign : ""}${body}`;
};

const StatView: React.FC<{ visual: StatVisual; frame: number; total: number; fps: number; lang: "en" | "de" }> = ({
  visual,
  frame,
  total,
  fps,
  lang,
}) => {
  const finalText = toDisplay(visual.value);
  const valueFit = useMemo(() => fitText(finalText, 250, 80, INNER_W, 1), [finalText]);
  const labelFit = useMemo(() => fitText(visual.label, 58, 34, INNER_W, 3), [visual.label]);
  const isNumber = PLAIN_NUMBER.test(visual.value.trim());

  const countEnd = Math.min(42, Math.round(total * 0.6));
  const countProgress = interpolate(frame, [6, countEnd], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const valuePop = enter(frame, 3, fps, 16);
  const shownValue = toDisplay(isNumber ? countUpText(visual.value, countProgress, lang) : visual.value);
  const labelIn = smooth(frame, 14, fps, 14);
  const barIn = smooth(frame, 8, fps, 14);

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", padding: "36px 0 28px" }}>
      <div
        style={{
          transform: `scale(${isNumber ? 1 : 0.55 + 0.45 * valuePop})`,
          opacity: clamp01(valuePop * 1.5),
          // Fixed-width box so the count-up does not jitter sideways.
          minWidth: textWidth(finalText, valueFit.size),
          textAlign: "center",
        }}
      >
        <FitText fit={{ size: valueFit.size, lines: [shownValue] }} color={ACCENT} align="center" lineHeight={1.02} />
      </div>
      <div style={{ margin: "30px 0 34px" }}>
        <AccentBar progress={barIn} />
      </div>
      <div style={{ opacity: labelIn, transform: `translateY(${(1 - labelIn) * 20}px)` }}>
        <FitText fit={labelFit} align="center" lineHeight={1.18} />
      </div>
    </div>
  );
};

// ---------------------------------------------------------------- compare
const CompareCard: React.FC<{
  kind: "cross" | "check";
  progress: number;
  headingFit: Fit;
  textFit: Fit;
}> = ({ kind, progress, headingFit, textFit }) => {
  const isFact = kind === "check";
  const tone = isFact ? "#4ADE80" : "#FF8A8A";
  return (
    <div
      style={{
        flex: 1,
        boxSizing: "border-box",
        padding: "28px 24px 30px",
        borderRadius: 34,
        background: isFact ? "rgba(52,211,120,0.16)" : "rgba(229,72,77,0.15)",
        border: `3px solid ${isFact ? "rgba(74,222,128,0.65)" : "rgba(255,120,120,0.45)"}`,
        display: "flex",
        flexDirection: "column",
        gap: 20,
        opacity: clamp01(progress * 1.4),
        transform: `translateY(${(1 - progress) * 30}px) scale(${0.93 + 0.07 * progress})`,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <Icon kind={kind} color={tone} />
        <FitText fit={headingFit} color={tone} lineHeight={1.1} />
      </div>
      <FitText fit={textFit} color={isFact ? "#FFFFFF" : "rgba(255,255,255,0.86)"} lineHeight={1.2} />
    </div>
  );
};

const CompareView: React.FC<{ visual: CompareVisual; frame: number; total: number; fps: number }> = ({
  visual,
  frame,
  total,
  fps,
}) => {
  const gap = 24;
  const cardW = (INNER_W - gap) / 2; // 464
  const innerW = cardW - 2 * 24 - 6; // padding + border
  const headingW = innerW - 44 - 14; // icon + gap

  const titleFit = useMemo(() => fitText(visual.title, 60, 38, INNER_W, 2), [visual.title]);
  const fits = useMemo(() => {
    const lt = fitText(visual.left.text, 44, 28, innerW, 6);
    const rt = fitText(visual.right.text, 44, 28, innerW, 6);
    // Both cards share the smaller text size so the pair looks balanced.
    const size = Math.min(lt.size, rt.size);
    return {
      lh: fitText(visual.left.heading, 46, 28, headingW, 1),
      rh: fitText(visual.right.heading, 46, 28, headingW, 1),
      lt: fitText(visual.left.text, size, 28, innerW, 6),
      rt: fitText(visual.right.text, size, 28, innerW, 6),
    };
  }, [visual.left, visual.right, headingW, innerW]);

  const leftStart = 8;
  const rightStart = leftStart + Math.min(40, Math.max(14, Math.round(total * 0.25)));

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "stretch" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 20, alignItems: "flex-start", marginBottom: 34 }}>
        <FitText fit={titleFit} lineHeight={1.12} />
        <AccentBar progress={smooth(frame, 2, fps, 14)} />
      </div>
      <div style={{ display: "flex", gap, alignItems: "stretch" }}>
        <CompareCard kind="cross" progress={enter(frame, leftStart, fps)} headingFit={fits.lh} textFit={fits.lt} />
        <CompareCard kind="check" progress={enter(frame, rightStart, fps)} headingFit={fits.rh} textFit={fits.rt} />
      </div>
    </div>
  );
};

// ---------------------------------------------------------------- composition
export const ShortsPanel: React.FC<ShortsPanelProps> = ({ visual, lang }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const fontReady = useBeVietnamPro();

  const inP = spring({
    frame,
    fps,
    config: { damping: 15, stiffness: 170, mass: 0.7 },
    durationInFrames: ENTER_FRAMES + 2,
  });
  const fadeOut = interpolate(frame, [durationInFrames - EXIT_FRAMES, durationInFrames - 1], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const opacity = clamp01(interpolate(frame, [0, ENTER_FRAMES - 2], [0, 1], { extrapolateRight: "clamp" })) * fadeOut;
  const scale = (0.9 + 0.1 * inP) * (0.97 + 0.03 * fadeOut);
  const lift = (1 - inP) * 28 + (1 - fadeOut) * -10;

  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", fontFamily: FONT_FALLBACK }}>
      <style>{FONT_CSS}</style>
      {fontReady ? (
        <div
          lang={lang}
          style={{
            width: CARD_W,
            boxSizing: "border-box",
            padding: `${CARD_PAD_Y}px ${CARD_PAD_X}px`,
            borderRadius: CARD_RADIUS,
            background: CARD_BG,
            border: "2px solid rgba(255,255,255,0.10)",
            boxShadow: "0 20px 56px rgba(0,0,0,0.45)",
            opacity,
            transform: `translateY(${lift}px) scale(${scale})`,
            fontWeight: 700,
            fontKerning: "normal",
          }}
        >
          {visual.type === "flow" ? (
            <FlowView visual={visual} frame={frame} total={durationInFrames} fps={fps} />
          ) : visual.type === "stat" ? (
            <StatView visual={visual} frame={frame} total={durationInFrames} fps={fps} lang={lang} />
          ) : (
            <CompareView visual={visual} frame={frame} total={durationInFrames} fps={fps} />
          )}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
