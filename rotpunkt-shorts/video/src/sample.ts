import script from "../../scripts/short1.json";
import type { Labels, ShortProps } from "./types";

/** Studio preview only: short1 English labels on a fixed 40 s timeline (real renders get props from tools/build.py). */
export const sampleProps: ShortProps = {
  lang: "en",
  voice: true,
  durationSeconds: 40,
  labels: script.en.labels as unknown as Labels,
  scenes: [
    { key: "hook", start: 0, end: 3.5 },
    { key: "evidence", start: 3.5, end: 9 },
    { key: "pain", start: 9, end: 13 },
    { key: "idea", start: 13, end: 15.5 },
    { key: "arch", start: 15.5, end: 26 },
    { key: "metrics", start: 26, end: 31 },
    { key: "proof", start: 31, end: 34.5 },
    { key: "pilot", start: 34.5, end: 37 },
    { key: "closing", start: 37, end: 40 },
  ],
  cues: {},
  captions: [],
};
