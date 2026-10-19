import { Easing, interpolate, spring } from "remotion";

export const clamp01 = (n: number): number => Math.min(1, Math.max(0, n));

/** Springy 0 -> 1 starting at `start` (frames); 0 before it. */
export const pop = (frame: number, start: number, fps: number, stiffness = 170, damping = 15): number =>
  frame < start ? 0 : spring({ frame: frame - start, fps, config: { damping, stiffness, mass: 0.75 } });

/** Calm 0 -> 1 over `duration` frames starting at `start`. */
export const ease = (frame: number, start: number, duration: number): number =>
  interpolate(frame, [start, start + duration], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

export const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;
