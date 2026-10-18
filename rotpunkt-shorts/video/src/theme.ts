export const W = 1080;
export const H = 1920;
export const FPS = 30;

export const FONT = "Be Vietnam Pro";
export const FONT_STACK = `"${FONT}", "Helvetica Neue", Arial, sans-serif`;

export const C = {
  bgTop: "#0A111C",
  bgBottom: "#101C2D",
  grid: "rgba(255,255,255,0.045)",
  text: "#F4F6FA",
  sub: "#AAB6C6",
  faint: "#738299",
  amber: "#FFB000",
  green: "#4ADE80",
  coral: "#FF7A59",
  blue: "#7CC4FF",
  slate: "#52627A",
  card: "rgba(255,255,255,0.055)",
  cardStrong: "rgba(255,255,255,0.09)",
  line: "rgba(255,255,255,0.13)",
  ink: "#0B1018",
};

/** "#RRGGBB" with an alpha, as an rgba() string. */
export const tint = (hex: string, alpha: number): string => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
};

export const MARGIN = 60;
export const CONTENT_W = W - 2 * MARGIN;

/** Vertical layout of the 1080x1920 frame (pixels). Scenes stay above the caption panel. */
export const Y = {
  topBar: 78,
  sceneTop: 196,
  sceneBottom: 1395,
  captionTop: 1440,
  footnote: 1690,
  progress: 1898,
};
