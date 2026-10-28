import React, { useMemo } from "react";
import { Img, staticFile } from "remotion";
import { C, CONTENT_W, MARGIN, Y, tint } from "../theme";
import { fitText } from "../text";
import { clamp01, ease, pop } from "../anim";
import { Icon } from "../icons";
import { Lines, SceneShell } from "../components/Scene";
import type { Labels, SceneCtx } from "../types";

const PAD = 40;
const INNER = CONTENT_W - PAD * 2;

export const ClosingScene: React.FC<{ ctx: SceneCtx; closing: Labels["closing"]; voice: boolean }> = ({ ctx, closing, voice }) => {
  const { frame, fps, start } = ctx;
  const note = voice ? `${closing.note} · ${closing.voiceNote}` : closing.note;
  const links = closing.links && closing.links.length ? closing.links : [closing.link];
  const f = useMemo(() => {
    const oneLine = fitText(closing.name, { max: 56, min: 36, maxW: INNER, maxLines: 1, weight: 800 });
    return {
      series: fitText(closing.series, { max: 24, min: 18, maxW: INNER, maxLines: 1, weight: 600 }),
      forLine: fitText(closing.forLine ?? "", { max: 42, min: 28, maxW: INNER, maxLines: 2, weight: 800 }),
      name: oneLine.lines.length === 1 ? oneLine : fitText(closing.name, { max: 56, min: 34, maxW: INNER, maxLines: 2, weight: 800 }),
      role: fitText(closing.role, { max: 30, min: 22, maxW: INNER, maxLines: 1, weight: 600 }),
      links: links.map((href) => fitText(href, { max: 28, min: 20, maxW: INNER - 52, maxLines: 1, weight: 600 })),
      note: fitText(note, { max: 22, min: 17, maxW: INNER, maxLines: 3, weight: 500 }),
    };
  }, [closing, note, links]);
  const plate = closing.logoPlate === "light";
  const logoH = closing.logo ? (plate ? 110 : 120) : 0;
  const linksH = f.links.reduce((s, item) => s + item.size * 1.25 + 10, 0);
  const cardH =
    PAD * 2 +
    f.series.size * 1.15 +
    16 +
    logoH +
    (closing.forLine ? 12 + f.forLine.lines.length * f.forLine.size * 1.12 : 0) +
    12 +
    f.role.size * 1.15 +
    6 +
    f.name.lines.length * f.name.size * 1.08 +
    20 + 3 + 16 +
    linksH +
    18 +
    f.note.lines.length * f.note.size * 1.3;
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
          borderRadius: 36,
          background: "rgba(16,26,42,0.94)",
          border: `2.5px solid ${tint(C.amber, 0.55)}`,
          boxShadow: `0 0 ${50 + 30 * glow}px ${tint(C.amber, 0.16)}, 0 30px 70px rgba(0,0,0,0.45)`,
          opacity: clamp01(cardP * 1.5),
          transform: `scale(${0.92 + 0.08 * cardP})`,
          textAlign: "center",
        }}
      >
        <Lines fit={f.series} weight={600} color={C.sub} align="center" style={{ letterSpacing: 1 }} />
        <div style={{ height: 16 }} />
        {closing.logo ? (
          <div style={{ display: "flex", justifyContent: "center", opacity: clamp01(cardP * 1.4) }}>
            <div
              style={{
                background: plate ? "#FFFFFF" : "transparent",
                borderRadius: plate ? 16 : 0,
                padding: plate ? "10px 16px" : 0,
                maxWidth: "100%",
                boxSizing: "border-box",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Img
                src={staticFile(closing.logo)}
                style={{ height: plate ? 80 : logoH, width: "auto", maxWidth: INNER - (plate ? 32 : 0), objectFit: "contain" }}
              />
            </div>
          </div>
        ) : null}
        {closing.forLine ? (
          <div style={{ marginTop: 12, opacity: roleP }}>
            <Lines fit={f.forLine} weight={800} color={C.amber} align="center" lineHeight={1.12} />
          </div>
        ) : null}
        <div style={{ marginTop: 12, opacity: roleP }}>
          <Lines fit={f.role} weight={600} color={C.sub} align="center" />
        </div>
        <div style={{ height: 8 }} />
        <div style={{ opacity: clamp01(nameP * 1.5), transform: `translateY(${(1 - nameP) * 18}px)` }}>
          <Lines fit={f.name} weight={800} align="center" lineHeight={1.08} />
        </div>
        <div style={{ height: 18 }} />
        <div style={{ height: 3, borderRadius: 2, background: C.line, width: INNER * linkP }} />
        <div style={{ height: 16 }} />
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8, opacity: linkP }}>
          {f.links.map((item, i) => (
            <div key={links[i]} style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 12 }}>
              <Icon name="link" size={28} color={C.blue} stroke={3.2} />
              <Lines fit={item} weight={600} color={C.text} />
            </div>
          ))}
        </div>
        <div style={{ height: 18 }} />
        <div style={{ opacity: noteP }}>
          <Lines fit={f.note} weight={500} color={C.faint} align="center" lineHeight={1.3} />
        </div>
      </div>
    </SceneShell>
  );
};
