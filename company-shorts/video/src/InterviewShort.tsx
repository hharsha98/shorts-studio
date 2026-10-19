import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import type { CalculateMetadataFunction } from "remotion";
import { C, FONT_STACK, FPS } from "./theme";
import { useFontsReady } from "./fonts";
import { Background, ProgressBar, TopBar } from "./components/Chrome";
import { Captions } from "./components/Captions";
import { HookScene } from "./scenes/Hook";
import { EvidenceScene } from "./scenes/Evidence";
import { PainScene } from "./scenes/Pain";
import { IdeaScene } from "./scenes/Idea";
import { ArchScene } from "./scenes/Arch";
import { ProofScene } from "./scenes/Proof";
import { MetricsScene } from "./scenes/Metrics";
import { PilotScene } from "./scenes/Pilot";
import { ClosingScene } from "./scenes/Closing";
import type { SceneCtx, SceneWindow, ShortProps } from "./types";

export const calculateShortMetadata: CalculateMetadataFunction<ShortProps> = ({ props }) => ({
  durationInFrames: Math.max(1, Math.round(props.durationSeconds * FPS)),
});

const Scene: React.FC<{ win: SceneWindow; props: ShortProps; frame: number; fps: number }> = ({ win, props, frame, fps }) => {
  const ctx: SceneCtx = {
    frame,
    fps,
    lang: props.lang,
    start: Math.round(win.start * fps),
    end: Math.round(win.end * fps),
    cue: (name, fallback) => (props.cues[name] !== undefined ? Math.round(props.cues[name] * fps) : fallback),
  };
  const L = props.labels;
  switch (win.key) {
    case "hook":
      return <HookScene ctx={ctx} hook={L.hook} credit={L.credit} status={L.hook.status ?? (L.pain.kind === "scattered" ? L.pain.center : "")} />;
    case "evidence":
      return <EvidenceScene ctx={ctx} ev={L.evidence} />;
    case "pain":
      return <PainScene ctx={ctx} pain={L.pain} credit={L.credit} />;
    case "idea":
      return <IdeaScene ctx={ctx} idea={L.idea} credit={L.credit} />;
    case "arch":
      return <ArchScene ctx={ctx} arch={L.arch} />;
    case "proof":
      return <ProofScene ctx={ctx} proof={L.proof} />;
    case "metrics":
      return <MetricsScene ctx={ctx} m={L.metrics} />;
    case "pilot":
      return <PilotScene ctx={ctx} pilot={L.pilot} />;
    case "closing":
      return <ClosingScene ctx={ctx} closing={L.closing} voice={props.voice} />;
    default:
      return null;
  }
};

/** One interview Short: scenes timed by the narration, captions on top, a thin progress bar at the bottom. */
export const InterviewShort: React.FC<ShortProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const ready = useFontsReady();
  return (
    <AbsoluteFill style={{ fontFamily: FONT_STACK, color: C.text }} lang={props.lang}>
      <Background />
      {ready ? (
        <>
          <TopBar top={props.labels.top} />
          {props.scenes.map((win) => (
            <Scene key={`${win.key}-${win.start}`} win={win} props={props} frame={frame} fps={fps} />
          ))}
          <Captions chunks={props.captions} />
          <ProgressBar />
        </>
      ) : null}
    </AbsoluteFill>
  );
};
