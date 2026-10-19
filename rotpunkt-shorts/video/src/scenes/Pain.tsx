import React, { useMemo } from "react";
import { C, CONTENT_W, MARGIN, W, tint } from "../theme";
import { fitText, textWidth } from "../text";
import { clamp01, ease, lerp, pop } from "../anim";
import { Icon } from "../icons";
import { Lines, SceneShell, SceneTitle, titleHeight, useTitleFit } from "../components/Scene";
import { Photo } from "../components/Photo";
import type { PainLabels, SceneCtx } from "../types";
import { Y } from "../theme";

const Chip: React.FC<{ text: string; p: number; color?: string }> = ({ text, p, color = C.blue }) => (
  <div
    style={{
      padding: "12px 26px",
      borderRadius: 32,
      background: tint(color, 0.14),
      border: `2px solid ${tint(color, 0.55)}`,
      color: C.text,
      fontSize: 34,
      fontWeight: 600,
      whiteSpace: "nowrap",
      opacity: clamp01(p * 1.5),
      transform: `scale(${0.8 + 0.2 * p})`,
    }}
  >
    {text}
  </div>
);

// ---------------------------------------------------------------- rule of ten (order errors)

/** Variants, dimensions and dependencies pinned onto the real kitchen photo (coordinates inside the 960x430 card). */
const Callouts: React.FC<{ frame: number; fps: number; at: number; chips: string[] }> = ({ frame, fps, at, chips }) => {
  const q = [0, 1, 2].map((i) => pop(frame, at + i * 6, fps, 170, 15));
  const line = ease(frame, at + 6, 12);
  const pill = (text: string, cx: number, cy: number, k: number): React.ReactNode => {
    const w = textWidth(text, 32, 700) + 44;
    return (
      <div
        style={{
          position: "absolute",
          left: cx - w / 2,
          top: cy - 26,
          width: w,
          height: 52,
          borderRadius: 26,
          background: "rgba(8,14,24,0.86)",
          border: `2.5px solid ${C.amber}`,
          color: C.text,
          fontSize: 32,
          fontWeight: 700,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          opacity: clamp01(q[k] * 1.5),
          transform: `scale(${0.75 + 0.25 * q[k]})`,
          boxShadow: "0 8px 24px rgba(0,0,0,0.45)",
        }}
      >
        {text}
      </div>
    );
  };
  return (
    <>
      <svg width={960} height={430} viewBox="0 0 960 430" style={{ position: "absolute", left: 0, top: 0 }}>
        <g opacity={clamp01(q[1] * 1.5)}>
          <line x1={82} y1={236} x2={82 + (870 - 82) * line} y2={236} stroke={C.amber} strokeWidth={4} />
          <line x1={82} y1={218} x2={82} y2={254} stroke={C.amber} strokeWidth={4} />
          {line > 0.98 ? <line x1={870} y1={218} x2={870} y2={254} stroke={C.amber} strokeWidth={4} /> : null}
        </g>
        <g opacity={clamp01(q[2] * 1.5)}>
          <circle cx={480} cy={157} r={9} fill={C.amber} />
          <polyline points="489,152 590,96 640,96" fill="none" stroke={C.amber} strokeWidth={4} strokeLinejoin="round" />
        </g>
        <g opacity={clamp01(q[0] * 1.5)}>
          {[210, 395, 575].map((x) => (
            <rect key={x} x={x - 60} y={300} width={120} height={110} rx={10} fill="none" stroke={tint(C.amber, 0.85)} strokeWidth={3} strokeDasharray="10 8" />
          ))}
        </g>
      </svg>
      {pill(chips[0], 395, 355, 0)}
      {pill(chips[1], 476, 236, 1)}
      {pill(chips[2], 760, 96, 2)}
    </>
  );
};
const RuleOfTen: React.FC<{ ctx: SceneCtx; p: Extract<PainLabels, { kind: "ruleOfTen" }>; credit: string }> = ({ ctx, p, credit }) => {
  const { frame, fps } = ctx;
  const titleFit = useTitleFit(p.title, 56);
  const top0 = Y.sceneTop + titleHeight(titleFit) + (p.photo ? 24 : 30);
  const photo = p.photo ? { x: MARGIN, y: top0, w: CONTENT_W, h: 430 } : null;
  const chipsAt = ctx.cue("pain.chips", ctx.start + 6);
  const barAt = [0, 1, 2].map((i) => ctx.cue(`pain.${i}`, ctx.start + 24 + i * 14));
  const heights = photo ? [50, 140, 250] : [80, 240, 470];
  const colors = [C.green, C.amber, C.coral];
  const centers = [210, 540, 870];
  const baseY = 1225;
  const colW = 230;
  const labelFits = useMemo(() => p.columns.map((c) => fitText(c, { max: 32, min: 24, maxW: 300, maxLines: 2, weight: 600 })), [p.columns]);
  const grown = barAt.map((at) => pop(frame, at, fps, 110, 16));
  let marker = 0;
  for (let i = 0; i < 3; i++) if (frame >= barAt[i]) marker = i;
  const mx = centers[marker];
  const my = baseY - heights[marker] * grown[marker] - 150;
  return (
    <SceneShell ctx={ctx}>
      <SceneTitle ctx={ctx} fit={titleFit} />
      {photo && p.photo ? (
        <Photo src={p.photo} credit={credit} x={photo.x} y={photo.y} w={photo.w} h={photo.h} focus="center 60%">
          <Callouts frame={frame} fps={fps} at={chipsAt} chips={p.chips} />
        </Photo>
      ) : (
        <div style={{ position: "absolute", left: MARGIN, top: top0, width: CONTENT_W, display: "flex", gap: 18, justifyContent: "center", flexWrap: "wrap" }}>
          {p.chips.map((c, i) => (
            <Chip key={i} text={c} p={pop(frame, chipsAt + i * 5, fps)} />
          ))}
        </div>
      )}
      {centers.map((cx, i) => {
        const h = heights[i] * grown[i];
        return (
          <React.Fragment key={i}>
            <div
              style={{
                position: "absolute",
                left: cx - colW / 2,
                width: colW,
                top: baseY - h,
                height: h,
                borderRadius: "20px 20px 6px 6px",
                background: `linear-gradient(180deg, ${tint(colors[i], 0.9)} 0%, ${tint(colors[i], 0.35)} 100%)`,
                boxShadow: `0 0 40px ${tint(colors[i], 0.25)}`,
              }}
            />
            <div
              style={{
                position: "absolute",
                left: cx - 150,
                width: 300,
                top: baseY - h - 82,
                textAlign: "center",
                fontSize: 64,
                fontWeight: 800,
                color: colors[i],
                opacity: clamp01(grown[i] * 2),
              }}
            >
              {p.multipliers[i]}
            </div>
            <div style={{ position: "absolute", left: cx - 150, width: 300, top: baseY + 20, opacity: 0.35 + 0.65 * clamp01(grown[i] * 2) }}>
              <Lines fit={labelFits[i]} weight={600} align="center" lineHeight={1.18} />
            </div>
          </React.Fragment>
        );
      })}
      <div style={{ position: "absolute", left: MARGIN, width: CONTENT_W, top: baseY, height: 4, borderRadius: 2, background: "rgba(255,255,255,0.25)" }} />
      <div
        style={{
          position: "absolute",
          left: mx - 34,
          top: my,
          width: 68,
          height: 68,
          borderRadius: 34,
          background: C.coral,
          color: C.ink,
          fontSize: 48,
          fontWeight: 800,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          opacity: clamp01(grown[0] * 2),
          boxShadow: `0 0 30px ${tint(C.coral, 0.6)}`,
        }}
      >
        !
      </div>
      <div style={{ position: "absolute", left: MARGIN, width: CONTENT_W, top: baseY + 104, textAlign: "center", color: C.faint, fontSize: 25, fontWeight: 500, opacity: ease(frame, barAt[2], 14) }}>
        {p.note}
      </div>
    </SceneShell>
  );
};

// ---------------------------------------------------------------- scattered knowledge (machine faults)
const TILE_W = 410;
const TILE_H = 160;
const TILE_ICONS = ["book", "quote", "inbox", "user"];

const Scattered: React.FC<{ ctx: SceneCtx; p: Extract<PainLabels, { kind: "scattered" }>; credit: string }> = ({ ctx, p, credit }) => {
  const { frame, fps } = ctx;
  const titleFit = useTitleFit(p.title, 58);
  const top0 = Y.sceneTop + titleHeight(titleFit) + 40;
  const bottom = 1330;
  const cy = (top0 + bottom) / 2;
  const tiles = [
    { x: MARGIN, y: top0 },
    { x: W - MARGIN - TILE_W, y: top0 },
    { x: MARGIN, y: bottom - TILE_H },
    { x: W - MARGIN - TILE_W, y: bottom - TILE_H },
  ];
  const at = [0, 1, 2, 3].map((i) => ctx.cue(`pain.${i}`, ctx.start + 10 + i * 12));
  const labelFits = useMemo(() => p.tiles.map((t) => fitText(t, { max: 34, min: 25, maxW: TILE_W - 120, maxLines: 2, weight: 600 })), [p.tiles]);
  const centerP = pop(frame, ctx.start + 2, fps);
  const pulse = 1 + 0.06 * Math.sin(frame / 5);
  const hop = 22;
  const order = [0, 1, 3, 2];
  const searchStart = at[3] + 8;
  const k = Math.max(0, frame - searchStart) / hop;
  const from = order[Math.floor(k) % 4];
  const to = order[(Math.floor(k) + 1) % 4];
  const local = k - Math.floor(k);
  const tc = (i: number) => ({ x: tiles[i].x + TILE_W / 2, y: tiles[i].y + TILE_H / 2 });
  // travel between the tiles but stop short of them, so the magnifier never covers a label
  const inner = (i: number) => {
    const c = tc(i);
    return { x: lerp(540, c.x, 0.42), y: lerp(cy, c.y, 0.42) };
  };
  const gx = lerp(inner(from).x, inner(to).x, ease(local * hop, 0, hop * 0.7));
  const gy = lerp(inner(from).y, inner(to).y, ease(local * hop, 0, hop * 0.7));
  const glassOn = frame >= searchStart ? ease(frame, searchStart, 8) : 0;
  return (
    <SceneShell ctx={ctx}>
      <SceneTitle ctx={ctx} fit={titleFit} />
      <svg width={1080} height={1920} viewBox="0 0 1080 1920" style={{ position: "absolute", left: 0, top: 0 }}>
        {tiles.map((t, i) => {
          const d = ease(frame, at[i], 10);
          const c = tc(i);
          return (
            <line
              key={i}
              x1={540}
              y1={cy}
              x2={lerp(540, c.x, d)}
              y2={lerp(cy, c.y, d)}
              stroke="rgba(255,255,255,0.28)"
              strokeWidth={4}
              strokeDasharray="12 12"
              strokeDashoffset={-frame * 1.5}
            />
          );
        })}
      </svg>
      {tiles.map((t, i) => {
        const q = pop(frame, at[i], fps);
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: t.x,
              top: t.y,
              width: TILE_W,
              height: TILE_H,
              boxSizing: "border-box",
              borderRadius: 26,
              background: "#172334",
              border: `2px solid ${C.line}`,
              boxShadow: "0 16px 40px rgba(0,0,0,0.35)",
              display: "flex",
              alignItems: "center",
              gap: 20,
              padding: "0 26px",
              opacity: clamp01(q * 1.5),
              transform: `scale(${0.85 + 0.15 * q})`,
            }}
          >
            <div style={{ width: 72, height: 72, borderRadius: 36, background: tint(C.blue, 0.16), display: "flex", alignItems: "center", justifyContent: "center", flex: "none" }}>
              <Icon name={TILE_ICONS[i]} size={42} color={C.blue} />
            </div>
            <Lines fit={labelFits[i]} weight={600} lineHeight={1.15} />
          </div>
        );
      })}
      {p.photo ? (
        <>
          <div style={{ position: "absolute", left: 540 - 180, top: cy - 125, width: 360, height: 250, borderRadius: 30, boxShadow: `0 0 ${50 * pulse}px ${tint(C.coral, 0.5)}`, transform: `scale(${0.7 + 0.3 * centerP})` }} />
          <Photo src={p.photo} credit={credit} x={540 - 180} y={cy - 125} w={360} h={250} radius={30} border={`4px solid ${C.coral}`} creditSize={17} scale={0.7 + 0.3 * centerP} progress={clamp01((frame - ctx.start) / 150)}>
            <div style={{ position: "absolute", inset: 0, background: "rgba(40,8,0,0.28)" }} />
          </Photo>
          <div
            style={{
              position: "absolute",
              left: 540 + 180 - 46,
              top: cy - 125 - 30,
              width: 76,
              height: 76,
              borderRadius: 38,
              background: C.coral,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              transform: `scale(${(0.7 + 0.3 * centerP) * pulse})`,
              boxShadow: `0 0 30px ${tint(C.coral, 0.6)}`,
            }}
          >
            <Icon name="alert" size={46} color={C.ink} stroke={4} />
          </div>
        </>
      ) : (
        <div
          style={{
            position: "absolute",
            left: 540 - 112,
            top: cy - 112,
            width: 224,
            height: 224,
            borderRadius: 112,
            background: tint(C.coral, 0.16),
            border: `4px solid ${C.coral}`,
            boxShadow: `0 0 ${50 * pulse}px ${tint(C.coral, 0.45)}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            transform: `scale(${(0.7 + 0.3 * centerP) * pulse})`,
          }}
        >
          <Icon name="alert" size={110} color={C.coral} stroke={3.4} />
        </div>
      )}
      <div style={{ position: "absolute", left: 0, width: W, top: cy + (p.photo ? 142 : 130), textAlign: "center", fontSize: 40, fontWeight: 800, color: C.text }}>{p.center}</div>
      <div
        style={{
          position: "absolute",
          left: 0,
          width: W,
          top: cy + (p.photo ? 198 : 186),
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          gap: 12,
          color: C.sub,
          fontSize: 30,
          fontWeight: 600,
          opacity: glassOn,
        }}
      >
        <div style={{ transform: `rotate(${frame * 6}deg)` }}>
          <Icon name="clock" size={36} color={C.sub} />
        </div>
        {p.searching}
      </div>
      {p.photo ? null : (
        <div style={{ position: "absolute", left: gx - 20, top: gy - 70, opacity: glassOn }}>
          <Icon name="search" size={76} color={C.amber} stroke={4.5} />
        </div>
      )}
    </SceneShell>
  );
};

// ---------------------------------------------------------------- know-how bottleneck (skills gap)
const Avatar: React.FC<{ x: number; y: number; r: number; color: string; p: number }> = ({ x, y, r, color, p }) => (
  <div
    style={{
      position: "absolute",
      left: x - r,
      top: y - r,
      width: r * 2,
      height: r * 2,
      borderRadius: r,
      background: tint(color, 0.14),
      border: `4px solid ${color}`,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      opacity: clamp01(p * 1.5),
      transform: `scale(${0.7 + 0.3 * p})`,
    }}
  >
    <Icon name="user" size={r * 1.15} color={color} stroke={3.2} />
  </div>
);

const Bottleneck: React.FC<{ ctx: SceneCtx; p: Extract<PainLabels, { kind: "bottleneck" }> }> = ({ ctx, p }) => {
  const { frame, fps } = ctx;
  const titleFit = useTitleFit(p.title, 58);
  const top0 = Y.sceneTop + titleHeight(titleFit) + 30;
  const chipAt = [0, 1, 2].map((i) => ctx.cue(`pain.${i}`, ctx.start + 8 + i * 14));
  const chipsH = useMemo(() => {
    const total = p.chips.reduce((s, c) => s + textWidth(c, 34, 600) + 56 + 18, 0);
    return total > CONTENT_W ? 2 * 70 + 16 : 70;
  }, [p.chips]);
  const expertsY = top0 + chipsH + 190;
  const newY = 1190;
  const expertR = 84;
  const newR = 62;
  const experts = [420, 660];
  const newcomers = [150, 345, 540, 735, 930];
  const appear = pop(frame, ctx.start + 4, fps);
  const bubbles = Array.from({ length: 10 }, (_, k) => k);
  const period = 54;
  return (
    <SceneShell ctx={ctx}>
      <SceneTitle ctx={ctx} fit={titleFit} />
      <div style={{ position: "absolute", left: MARGIN, top: top0, width: CONTENT_W, display: "flex", gap: 18, justifyContent: "center", flexWrap: "wrap", rowGap: 16 }}>
        {p.chips.map((c, i) => (
          <Chip key={i} text={c} p={pop(frame, chipAt[i], fps)} color={i === 2 ? C.amber : C.blue} />
        ))}
      </div>
      {bubbles.map((k) => {
        const spawn = ctx.start + 14 + k * 9;
        if (frame < spawn) return null;
        const local = ((frame - spawn) % period) / period;
        const fromX = newcomers[k % 5];
        const toX = experts[k % 2];
        const x = lerp(fromX, toX, local);
        const y = lerp(newY - newR - 36, expertsY + expertR + 34, local) - Math.sin(local * Math.PI) * 40;
        const o = Math.sin(local * Math.PI);
        return (
          <div
            key={k}
            style={{
              position: "absolute",
              left: x - 26,
              top: y - 26,
              width: 52,
              height: 52,
              borderRadius: 16,
              background: tint(C.amber, 0.2),
              border: `3px solid ${C.amber}`,
              color: C.amber,
              fontSize: 34,
              fontWeight: 800,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              opacity: o,
            }}
          >
            ?
          </div>
        );
      })}
      {experts.map((x, i) => (
        <Avatar key={i} x={x} y={expertsY} r={expertR} color={C.amber} p={appear} />
      ))}
      <div style={{ position: "absolute", left: 0, width: W, top: expertsY - expertR - 62, textAlign: "center", fontSize: 38, fontWeight: 800, color: C.amber, opacity: appear }}>{p.experts}</div>
      <div style={{ position: "absolute", left: 0, width: W, top: (expertsY + newY) / 2 - 30, display: "flex", justifyContent: "center", opacity: ease(frame, ctx.start + 20, 12) }}>
        <div style={{ padding: "10px 26px", borderRadius: 30, background: "#121C2A", border: `2px solid ${C.line}`, fontSize: 32, fontWeight: 600, color: C.sub, whiteSpace: "nowrap" }}>{p.flow}</div>
      </div>
      {newcomers.map((x, i) => (
        <Avatar key={i} x={x} y={newY} r={newR} color={C.slate} p={pop(frame, ctx.start + 6 + i * 3, fps)} />
      ))}
      <div style={{ position: "absolute", left: 0, width: W, top: newY + newR + 18, textAlign: "center", fontSize: 36, fontWeight: 700, color: C.sub, opacity: appear }}>{p.newcomers}</div>
    </SceneShell>
  );
};

export const PainScene: React.FC<{ ctx: SceneCtx; pain: PainLabels; credit: string }> = ({ ctx, pain, credit }) => {
  if (pain.kind === "ruleOfTen") return <RuleOfTen ctx={ctx} p={pain} credit={credit} />;
  if (pain.kind === "scattered") return <Scattered ctx={ctx} p={pain} credit={credit} />;
  return <Bottleneck ctx={ctx} p={pain} />;
};
