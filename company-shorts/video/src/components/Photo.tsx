import React from "react";
import { Img, staticFile } from "remotion";
import { C } from "../theme";

/**
 * A product photo from the company's public website in a rounded card, with a slow zoom and the small source credit in its
 * corner ("Images: <domain>"). Only photos: never the company logo, so nothing looks like an official company video.
 */
export const Photo: React.FC<{
  src: string;
  credit: string;
  x: number;
  y: number;
  w: number;
  h: number;
  /** 0..1 through the scene: drives the slow zoom. */
  progress?: number;
  radius?: number;
  border?: string;
  focus?: string;
  opacity?: number;
  scale?: number;
  creditSize?: number;
  children?: React.ReactNode;
}> = ({ src, credit, x, y, w, h, progress = 0, radius = 34, border, focus = "center", opacity = 1, scale = 1, creditSize = 20, children }) => (
  <div
    style={{
      position: "absolute",
      left: x,
      top: y,
      width: w,
      height: h,
      borderRadius: radius,
      overflow: "hidden",
      border: border ?? `2px solid ${C.line}`,
      boxShadow: "0 28px 70px rgba(0,0,0,0.5)",
      opacity,
      transform: `scale(${scale})`,
      background: "#0E1622",
    }}
  >
    <Img
      src={staticFile(src)}
      style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: focus, transform: `scale(${1.03 + 0.05 * progress})` }}
    />
    <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: Math.min(140, h * 0.35), background: "linear-gradient(180deg, rgba(5,9,16,0) 0%, rgba(5,9,16,0.55) 100%)" }} />
    {children}
    <div
      style={{
        position: "absolute",
        right: 16,
        bottom: 12,
        fontSize: creditSize,
        fontWeight: 600,
        color: "rgba(255,255,255,0.86)",
        textShadow: "0 1px 4px rgba(0,0,0,0.85)",
        letterSpacing: 0.3,
      }}
    >
      {credit}
    </div>
  </div>
);
