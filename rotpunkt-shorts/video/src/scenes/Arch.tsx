import React, { useMemo } from "react";
import { C, CONTENT_W, MARGIN, tint } from "../theme";
import { fitText, textWidth } from "../text";
import { clamp01, ease, pop } from "../anim";
import { Icon } from "../icons";
import { Lines, SceneShell, SceneTitle, titleHeight, useTitleFit } from "../components/Scene";
import type { Labels, SceneCtx } from "../types";
import { Y } from "../theme";

const NODE_H = 124;
const GAP = 58;
const ICON_D = 80;
const ICON_X = MARGIN + 22;
const LINE_X = ICON_X + ICON_D / 2;
const TEXT_X = 22 + ICON_D + 24;
const TEXT_W = CONTENT_W - TEXT_X - 70;
const BADGE_H = 64;

const Connector: React.FC<{ y1: number; y2: number; drawn: number; both: boolean; frame: number; flowing: boolean }> = ({ y1, y2, drawn, both, frame, flowing }) => {
  if (drawn <= 0.01) return null;
  const len = y2 - y1;
  const yEnd = y1 + len * drawn;
  const head = (y: number, dir: 1 | -1) => `${LINE_X - 13},${y - 14 * dir} ${LINE_X},${y} ${LINE_X + 13},${y - 14 * dir}`;
  const dots = flowing ? [0, 1, 2] : [];
  return (
    <svg width={1080} height={1920} viewBox="0 0 1080 1920" style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
      <line x1={LINE_X} y1={y1 + 4} x2={LINE_X} y2={yEnd - 4} stroke={tint(C.amber, 0.75)} strokeWidth={6} strokeLinecap="round" />
      {drawn > 0.95 ? <polyline points={head(y2 - 4, 1)} fill="none" stroke={C.amber} strokeWidth={6} strokeLinecap="round" strokeLinejoin="round" /> : null}
      {both && drawn > 0.95 ? <polyline points={head(y1 + 4, -1)} fill="none" stroke={C.amber} strokeWidth={6} strokeLinecap="round" strokeLinejoin="round" /> : null}
      {dots.map((d) => {
        const phase = ((frame / 26 + d / 3) % 1 + 1) % 1;
        const dir = both && d === 1 ? -1 : 1;
        const p = dir === 1 ? phase : 1 - phase;
        return <circle key={d} cx={LINE_X} cy={y1 + 8 + (len - 16) * p} r={6} fill="#FFFFFF" opacity={0.9 * Math.sin(phase * Math.PI)} />;
      })}
    </svg>
  );
};

export const ArchScene: React.FC<{ ctx: SceneCtx; arch: Labels["arch"] }> = ({ ctx, arch }) => {
  const { frame, fps } = ctx;
  const titleFit = useTitleFit(arch.title);
  const fits = useMemo(
    () =>
      arch.nodes.map((nd) => ({
        title: fitText(nd.title, { max: 40, min: 28, maxW: TEXT_W, maxLines: 1, weight: 700 }),
        sub: fitText(nd.sub, { max: 29, min: 21, maxW: TEXT_W, maxLines: 1, weight: 500 }),
      })),
    [arch.nodes],
  );
  const badgeSize = useMemo(() => {
    let s = 30;
    const cellW = (CONTENT_W - 18) / 2 - 2 * 22 - 38 - 12;
    while (s > 22 && Math.max(...arch.badges.map((b) => textWidth(b.text, s, 600))) > cellW) s -= 1;
    return s;
  }, [arch.badges]);
  const n = arch.nodes.length;
  const areaTop = Y.sceneTop + titleHeight(titleFit) + 34;
  const blockH = n * NODE_H + (n - 1) * GAP + 40 + 2 * BADGE_H + 18;
  const blockTop = Math.round(areaTop + Math.max(0, (Y.sceneBottom - 40 - areaTop - blockH) / 2));
  const nodeTop = (i: number) => blockTop + i * (NODE_H + GAP);
  const appear = arch.nodes.map((nd, i) => ctx.cue(`arch.${nd.id}`, ctx.start + 6 + i * 24));
  let active = -1;
  for (let i = 0; i < n; i++) if (frame >= appear[i]) active = i;
  const badgesAt = ctx.cue("arch.badges", appear[n - 1] + 30);
  const badgesTop = nodeTop(n - 1) + NODE_H + 40;

  return (
    <SceneShell ctx={ctx}>
      <SceneTitle ctx={ctx} fit={titleFit} />
      {arch.nodes.slice(0, -1).map((nd, i) => (
        <Connector
          key={nd.id}
          y1={nodeTop(i) + NODE_H}
          y2={nodeTop(i + 1)}
          drawn={ease(frame, appear[i + 1] - 4, 10)}
          both={nd.link === "both"}
          frame={frame}
          flowing={frame >= appear[i + 1] + 6}
        />
      ))}
      {arch.nodes.map((nd, i) => {
        const p = pop(frame, appear[i], fps, 165, 16);
        const isActive = i === active && frame < badgesAt;
        const passed = i < active || frame >= badgesAt;
        const glow = isActive ? 0.5 + 0.5 * Math.sin(frame / 6) : 0;
        return (
          <div
            key={nd.id}
            style={{
              position: "absolute",
              left: MARGIN,
              top: nodeTop(i),
              width: CONTENT_W,
              height: NODE_H,
              boxSizing: "border-box",
              borderRadius: 28,
              background: isActive ? tint(C.amber, 0.12) : C.cardStrong,
              border: `3px solid ${isActive ? C.amber : C.line}`,
              boxShadow: isActive ? `0 0 ${24 + 16 * glow}px ${tint(C.amber, 0.28)}` : "0 14px 34px rgba(0,0,0,0.25)",
              opacity: clamp01(p * 1.6),
              transform: `translateY(${(1 - p) * 34}px) scale(${0.94 + 0.06 * p})`,
            }}
          >
            <div
              style={{
                position: "absolute",
                left: 22,
                top: (NODE_H - 6 - ICON_D) / 2,
                width: ICON_D,
                height: ICON_D,
                borderRadius: ICON_D / 2,
                background: tint(isActive ? C.amber : C.blue, 0.16),
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Icon name={nd.icon} size={46} color={isActive ? C.amber : C.blue} />
            </div>
            <div style={{ position: "absolute", left: TEXT_X, top: 0, height: NODE_H - 6, display: "flex", flexDirection: "column", justifyContent: "center", gap: 4 }}>
              <Lines fit={fits[i].title} weight={700} lineHeight={1.12} />
              <Lines fit={fits[i].sub} weight={500} color={C.sub} lineHeight={1.15} />
            </div>
            {passed ? (
              <div
                style={{
                  position: "absolute",
                  right: 24,
                  top: (NODE_H - 6 - 44) / 2,
                  width: 44,
                  height: 44,
                  borderRadius: 22,
                  background: tint(C.green, 0.18),
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  opacity: ease(frame, i < n - 1 ? appear[i + 1] : badgesAt, 8),
                }}
              >
                <Icon name="check" size={30} color={C.green} stroke={5} />
              </div>
            ) : null}
          </div>
        );
      })}
      <div style={{ position: "absolute", left: MARGIN, top: badgesTop, width: CONTENT_W, display: "flex", flexWrap: "wrap", gap: 18 }}>
        {arch.badges.map((b, i) => {
          const q = pop(frame, badgesAt + i * 4, fps, 170, 15);
          return (
            <div
              key={i}
              style={{
                width: (CONTENT_W - 18) / 2,
                height: BADGE_H,
                boxSizing: "border-box",
                borderRadius: 32,
                background: tint(C.green, 0.12),
                border: `2px solid ${tint(C.green, 0.55)}`,
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "0 22px",
                opacity: clamp01(q * 1.5),
                transform: `scale(${0.8 + 0.2 * q})`,
              }}
            >
              <Icon name={b.icon} size={38} color={C.green} />
              <span style={{ fontSize: badgeSize, fontWeight: 600, color: C.text, whiteSpace: "nowrap" }}>{b.text}</span>
            </div>
          );
        })}
      </div>
    </SceneShell>
  );
};
