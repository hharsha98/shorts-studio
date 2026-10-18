import React, { useMemo } from "react";
import { C, CONTENT_W, MARGIN, tint } from "../theme";
import { fitText, textWidth } from "../text";
import { Lines, SceneShell } from "../components/Scene";
import type { Labels, SceneCtx } from "../types";

const HERO_CX = 540;
const HERO_CY = 1065;

const Glow: React.FC<{ r: number; color: string }> = ({ r, color }) => (
  <div
    style={{
      position: "absolute",
      left: HERO_CX - r,
      top: HERO_CY - r,
      width: r * 2,
      height: r * 2,
      borderRadius: r,
      background: `radial-gradient(circle, ${tint(color, 0.2)} 0%, ${tint(color, 0.06)} 45%, ${tint(color, 0)} 70%)`,
    }}
  />
);

/** Order sheet: checked lines, one flagged line, a magnifier over it. */
const OrderHero: React.FC<{ frame: number }> = ({ frame }) => {
  const f = Math.sin(frame / 18) * 6;
  const rows = [0, 1, 2, 3, 4, 5];
  const rowY = (i: number) => 900 + i * 52;
  return (
    <svg width={1080} height={1920} viewBox="0 0 1080 1920" style={{ position: "absolute", left: 0, top: 0 }}>
      <rect x={370} y={835} width={330} height={440} rx={26} fill="rgba(255,255,255,0.06)" stroke="rgba(255,255,255,0.28)" strokeWidth={3} />
      <rect x={402} y={866} width={170} height={16} rx={8} fill="rgba(255,255,255,0.38)" />
      {rows.map((i) => {
        const flagged = i === 3;
        const checked = i < 3;
        return (
          <g key={i}>
            {flagged ? <rect x={388} y={rowY(i) - 6} width={294} height={44} rx={12} fill={tint(C.coral, 0.2)} stroke={C.coral} strokeWidth={3} /> : null}
            {checked ? (
              <path d={`M404 ${rowY(i) + 16} L411 ${rowY(i) + 23} L424 ${rowY(i) + 9}`} fill="none" stroke={C.green} strokeWidth={4.5} strokeLinecap="round" strokeLinejoin="round" />
            ) : (
              <rect x={403} y={rowY(i) + 6} width={20} height={20} rx={5} fill="none" stroke={flagged ? C.coral : "rgba(255,255,255,0.35)"} strokeWidth={3} />
            )}
            <rect x={440} y={rowY(i) + 10} width={[180, 150, 200, 170, 120, 190][i]} height={13} rx={6.5} fill={flagged ? tint(C.coral, 0.75) : "rgba(255,255,255,0.22)"} />
          </g>
        );
      })}
      <g transform={`translate(${f * 0.6} ${f})`}>
        <circle cx={690} cy={1060} r={64} fill="rgba(10,17,28,0.35)" stroke={C.amber} strokeWidth={9} />
        <path d="M736 1106 L792 1162" stroke={C.amber} strokeWidth={16} strokeLinecap="round" />
        <circle cx={690} cy={1060} r={24} fill={C.coral} />
        <path d="M690 1047 V1063" stroke={C.ink} strokeWidth={5} strokeLinecap="round" />
        <circle cx={690} cy={1072} r={3} fill={C.ink} />
      </g>
    </svg>
  );
};

/** Two gears turning, with a warning badge. */
const MachineHero: React.FC<{ frame: number }> = ({ frame }) => {
  const teeth = (cx: number, cy: number, ro: number, ri: number, n: number) => {
    const pts: string[] = [];
    const step = (Math.PI * 2) / n;
    for (let i = 0; i < n; i++) {
      const a = i * step;
      for (const [ang, r] of [
        [a - step * 0.25, ri],
        [a - step * 0.15, ro],
        [a + step * 0.15, ro],
        [a + step * 0.25, ri],
      ]) {
        pts.push(`${(cx + r * Math.cos(ang)).toFixed(1)},${(cy + r * Math.sin(ang)).toFixed(1)}`);
      }
    }
    return `M${pts.join(" L")} Z`;
  };
  const a1 = frame * 0.5;
  const a2 = -frame * 0.5 * (12 / 8);
  return (
    <svg width={1080} height={1920} viewBox="0 0 1080 1920" style={{ position: "absolute", left: 0, top: 0 }}>
      <g transform={`rotate(${a1} 480 1080)`}>
        <path d={teeth(480, 1080, 165, 132, 12)} fill="rgba(255,255,255,0.05)" stroke="rgba(255,255,255,0.32)" strokeWidth={6} strokeLinejoin="round" />
        <circle cx={480} cy={1080} r={52} fill="none" stroke="rgba(255,255,255,0.32)" strokeWidth={6} />
      </g>
      <g transform={`rotate(${a2} 690 900)`}>
        <path d={teeth(690, 900, 102, 80, 8)} fill="rgba(255,255,255,0.05)" stroke={tint(C.blue, 0.6)} strokeWidth={6} strokeLinejoin="round" />
        <circle cx={690} cy={900} r={30} fill="none" stroke={tint(C.blue, 0.6)} strokeWidth={6} />
      </g>
      <g transform={`translate(0 ${Math.sin(frame / 14) * 5})`}>
        <path d="M690 1105 L770 1245 H610 Z" fill={C.coral} stroke={C.coral} strokeWidth={10} strokeLinejoin="round" />
        <path d="M690 1150 V1200" stroke={C.ink} strokeWidth={12} strokeLinecap="round" />
        <circle cx={690} cy={1224} r={7} fill={C.ink} />
      </g>
    </svg>
  );
};

/** Open book with a question bubble. */
const KnowledgeHero: React.FC<{ frame: number }> = ({ frame }) => {
  const f = Math.sin(frame / 16) * 6;
  return (
    <svg width={1080} height={1920} viewBox="0 0 1080 1920" style={{ position: "absolute", left: 0, top: 0 }}>
      <path d="M540 1010 C480 965 380 960 320 985 V1215 C380 1190 480 1195 540 1240 C600 1195 700 1190 760 1215 V985 C700 960 600 965 540 1010 Z" fill="rgba(255,255,255,0.06)" stroke="rgba(255,255,255,0.32)" strokeWidth={6} strokeLinejoin="round" />
      <path d="M540 1010 V1240" stroke="rgba(255,255,255,0.32)" strokeWidth={6} />
      {[0, 1, 2, 3].map((i) => (
        <g key={i}>
          <path d={`M360 ${1030 + i * 40} C420 ${1018 + i * 40} 470 ${1022 + i * 40} 510 ${1040 + i * 40}`} stroke="rgba(255,255,255,0.2)" strokeWidth={8} strokeLinecap="round" fill="none" />
          <path d={`M570 ${1040 + i * 40} C610 ${1022 + i * 40} 660 ${1018 + i * 40} 720 ${1030 + i * 40}`} stroke={i === 1 ? tint(C.amber, 0.8) : "rgba(255,255,255,0.2)"} strokeWidth={8} strokeLinecap="round" fill="none" />
        </g>
      ))}
      <g transform={`translate(0 ${f})`}>
        <path d="M600 800 H800 C815 800 826 811 826 826 V912 C826 927 815 938 800 938 H690 L650 975 V938 H600 C585 938 574 927 574 912 V826 C574 811 585 800 600 800 Z" fill={tint(C.amber, 0.16)} stroke={C.amber} strokeWidth={6} strokeLinejoin="round" />
        <text x={700} y={898} textAnchor="middle" fontSize={84} fontWeight={800} fill={C.amber} fontFamily="Be Vietnam Pro">?</text>
      </g>
    </svg>
  );
};

export const HookScene: React.FC<{ ctx: SceneCtx; hook: Labels["hook"] }> = ({ ctx, hook }) => {
  const full = useMemo(() => hook.lines.map((runs) => runs.map((r) => r.text).join("")), [hook.lines]);
  const size = useMemo(() => {
    let s = 108;
    while (s > 60 && Math.max(...full.map((l) => textWidth(l, s, 800))) > CONTENT_W) s -= 2;
    return s;
  }, [full]);
  const subFit = useMemo(() => fitText(hook.sub, { max: 40, min: 30, maxW: 880, maxLines: 2, weight: 500 }), [hook.sub]);
  const hero = hook.icon === "machine" ? <MachineHero frame={ctx.frame} /> : hook.icon === "knowledge" ? <KnowledgeHero frame={ctx.frame} /> : <OrderHero frame={ctx.frame} />;
  return (
    <SceneShell ctx={ctx} noEnter>
      <div style={{ position: "absolute", left: MARGIN, width: CONTENT_W, top: 318, textAlign: "center" }}>
        {hook.lines.map((runs, i) => (
          <div key={i} style={{ fontSize: size, fontWeight: 800, lineHeight: 1.1, whiteSpace: "pre", letterSpacing: -0.5 }}>
            {runs.map((r, k) => (
              <span key={k} style={{ color: r.accent ? C.amber : C.text }}>
                {r.text}
              </span>
            ))}
          </div>
        ))}
        <div style={{ marginTop: 34 }}>
          <Lines fit={subFit} weight={500} color={C.sub} align="center" lineHeight={1.28} />
        </div>
      </div>
      <div style={{ position: "absolute", inset: 0, transform: "scale(1.2)", transformOrigin: `${HERO_CX}px ${HERO_CY}px` }}>
        <Glow r={330} color={hook.icon === "machine" ? C.coral : C.amber} />
        {hero}
      </div>
    </SceneShell>
  );
};
