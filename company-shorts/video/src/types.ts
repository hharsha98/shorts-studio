export type Lang = "en" | "de";

export type SceneKey = "hook" | "evidence" | "pain" | "idea" | "arch" | "proof" | "metrics" | "pilot" | "closing";

export type Run = { text: string; accent?: boolean };
export type Word = { text: string; start: number; end: number };
export type CaptionChunk = { start: number; end: number; words: Word[] };
export type SceneWindow = { key: SceneKey; start: number; end: number };

export type PainLabels =
  | { kind: "ruleOfTen"; title: string; chips: string[]; columns: string[]; multipliers: string[]; note: string; photo?: string }
  | { kind: "scattered"; title: string; center: string; tiles: string[]; searching: string; photo?: string }
  | { kind: "bottleneck"; title: string; chips: string[]; experts: string; newcomers: string; flow: string };

export type ArchNode = { id: string; icon: string; title: string; sub: string; link?: "arrow" | "both" };

export type Labels = {
  /** Source credit shown small on every product photo. */
  credit: string;
  top: { badge: string; topic: string; right: string };
  hook: { icon: string; lines: Run[][]; sub: string; photo?: string; status?: string };
  evidence: { title: string; cards: { role: string; quote: string; gist?: string }[]; note: string };
  pain: PainLabels;
  idea: { icon: string; kicker: string; title: string; sub: string; photo?: string };
  arch: { title: string; nodes: ArchNode[]; badges: { icon: string; text: string }[] };
  proof: {
    kicker: string;
    badge: string;
    title: string;
    sub: string;
    facts: { value: string; label: string; wide?: boolean }[];
    source: string;
  };
  metrics: {
    title: string;
    stamp: string;
    legend: string[];
    items: { label: string; before: number; after: number; unit: string }[];
    footnote: string;
  };
  pilot: { title: string; sub: string; items: string[] };
  closing: {
    name: string;
    role: string;
    link: string;
    series: string;
    note: string;
    voiceNote: string;
    forLine?: string;
    logo?: string;
    /** "light" puts the logo on a white chip so a dark wordmark stays readable on the dark card. */
    logoPlate?: string;
  };
};

export type ShortProps = {
  lang: Lang;
  voice: boolean;
  durationSeconds: number;
  labels: Labels;
  scenes: SceneWindow[];
  cues: Record<string, number>;
  captions: CaptionChunk[];
};

/** What every scene component receives: the global frame, its own window in frames, and cue lookup in frames. */
export type SceneCtx = {
  frame: number;
  fps: number;
  start: number;
  end: number;
  lang: Lang;
  cue: (name: string, fallback: number) => number;
};
