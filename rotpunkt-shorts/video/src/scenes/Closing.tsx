import React, { useMemo } from "react";
import { C, CONTENT_W, MARGIN, Y, tint } from "../theme";
import { fitText } from "../text";
import { clamp01, ease, pop } from "../anim";
import { Icon } from "../icons";
import { Lines, SceneShell } from "../components/Scene";
import type { Labels, SceneCtx } from "../types";

const PAD = 52;
const INNER = CONTENT_W - PAD * 2;

export const ClosingScene: React.FC<{ ctx: SceneCtx; closing: Labels["closing"]; voice: boolean }> = ({ ctx, closing, voice }) => {
  const { frame, fps, start } = ctx;
  const note = voice ? `${closing.note} · ${closing.voiceNote}` : closing.note;
  const f = useMemo(() => {
    const oneLine = fitText(closing.name, { max: 76, min: 52, maxW: INNER, maxLines: 1, weight: 800 });
    return {
      series: fitText(closing.series, { max: 28, min: 22, maxW: INNER, maxLines: 1, weight: 600 }),
      name: oneLine.lines.length === 1 ? oneLine : fitText(closing.name, { max: 76, min: 48, maxW: INNER, maxLines: 2, weight: 800 }),
      role: fitText(closing.role, { max: 46, min: 32, maxW: INNER, maxLines: 2, weight: 700 }),
      link: fitText(closing.link, { max: 42, min: 30, maxW: INNER - 70, maxLines: 1, weight: 600 }),
      note: fitText(note, { max: 27, min: 21, maxW: INNER, maxLines: 3, weight: 500 }),
    };
  }, [closing, note]);
  const cardH =
    PAD * 2 +
    f.series.size * 1.15 +
    30 +
    f.name.lines.length * f.name.size * 1.08 +
    18 +
    f.role.lines.length * f.role.size * 1.15 +
    36 + 3 + 36 +
    f.link.size * 1.15 +
    34 +
    f.note.lines.length * f.note.size * 1.35;
  const top = Math.round((Y.sceneTop + Y.sceneBottom) / 2 - cardH / 2);
  const cardP = pop(frame, start, fps, 130, 18);
  const nameP = pop(frame, start + 6, fps, 150, 16);
  const roleP = ease(frame, start + 12, 12);
  const linkP = ease(frame, start + 18, 12);
  const noteP = ease(frame, start + 24, 14);
  const glow = 0.5 + 0.5 * Math.sin(frame / 12);
  return (
    <SceneShell ctx={ctx}>
      <div
        style={{
          position: "absolute",
          left: MARGIN,
          top,
          width: CONTENT_W,
          boxSizing: "border-box",
          padding: PAD,
          borderRadius: 40,
          background: "rgba(16,26,42,0.94)",
          border: `2.5px solid ${tint(C.amber, 0.55)}`,
          boxShadow: `0 0 ${50 + 30 * glow}px ${tint(C.amber, 0.16)}, 0 30px 70px rgba(0,0,0,0.45)`,
          opacity: clamp01(cardP * 1.5),
          transform: `scale(${0.92 + 0.08 * cardP})`,
          textAlign: "center",
        }}
      >
        <Lines fit={f.series} weight={600} color={C.sub} align="center" style={{ letterSpacing: 1 }} />
        <div style={{ height: 30 }} />
        <div style={{ opacity: clamp01(nameP * 1.5), transform: `translateY(${(1 - nameP) * 18}px)` }}>
          <Lines fit={f.name} weight={800} align="center" lineHeight={1.08} />
        </div>
        <div style={{ height: 18 }} />
        <div style={{ opacity: roleP }}>
          <Lines fit={f.role} weight={700} color={C.amber} align="center" lineHeight={1.15} />
        </div>
        <div style={{ height: 36 }} />
        <div style={{ height: 3, borderRadius: 2, background: C.line, width: INNER * linkP }} />
        <div style={{ height: 36 }} />
        <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 18, opacity: linkP }}>
          <Icon name="link" size={46} color={C.blue} stroke={3.6} />
          <Lines fit={f.link} weight={600} color={C.text} />
        </div>
        <div style={{ height: 34 }} />
        <div style={{ opacity: noteP }}>
          <Lines fit={f.note} weight={500} color={C.faint} align="center" lineHeight={1.35} />
        </div>
      </div>
    </SceneShell>
  );
};
