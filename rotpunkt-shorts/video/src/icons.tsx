import React from "react";

type IconProps = { name: string; size?: number; color?: string; stroke?: number };

const gearPath = (cx: number, cy: number, rOuter: number, rInner: number, teeth: number): string => {
  const pts: string[] = [];
  const step = (Math.PI * 2) / teeth;
  for (let i = 0; i < teeth; i++) {
    const a = i * step;
    const corners = [
      [a - step * 0.25, rInner],
      [a - step * 0.16, rOuter],
      [a + step * 0.16, rOuter],
      [a + step * 0.25, rInner],
    ];
    for (const [ang, r] of corners) pts.push(`${(cx + r * Math.cos(ang)).toFixed(2)},${(cy + r * Math.sin(ang)).toFixed(2)}`);
  }
  return `M${pts.join(" L")} Z`;
};

/** Simple line icons on a 48x48 grid (own drawings, no icon set or trademark). */
export const Icon: React.FC<IconProps> = ({ name, size = 48, color = "#FFFFFF", stroke = 3 }) => {
  const common = { fill: "none", stroke: color, strokeWidth: stroke, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  let body: React.ReactNode;
  switch (name) {
    case "inbox":
      body = (
        <>
          <path d="M6 27 L12 10 H36 L42 27 V38 H6 Z" {...common} />
          <path d="M6 27 H16 L19 32 H29 L32 27 H42" {...common} />
        </>
      );
      break;
    case "agent":
      body = (
        <>
          <rect x={12} y={12} width={24} height={24} rx={6} {...common} />
          <path d="M19 6 V12 M29 6 V12 M19 36 V42 M29 36 V42 M6 19 H12 M6 29 H12 M36 19 H42 M36 29 H42" {...common} />
          <path d="M24 17 L26.2 21.8 L31 24 L26.2 26.2 L24 31 L21.8 26.2 L17 24 L21.8 21.8 Z" fill={color} stroke="none" />
        </>
      );
      break;
    case "db":
      body = (
        <>
          <ellipse cx={24} cy={12} rx={14} ry={5} {...common} />
          <path d="M10 12 V36 C10 39 16 41 24 41 C32 41 38 39 38 36 V12" {...common} />
          <path d="M10 24 C10 27 16 29 24 29 C32 29 38 27 38 24" {...common} />
        </>
      );
      break;
    case "shield":
      body = (
        <>
          <path d="M24 5 L39 11 V23 C39 33 32 40 24 43 C16 40 9 33 9 23 V11 Z" {...common} />
          <path d="M17 24 L22 29 L31 19" {...common} />
        </>
      );
      break;
    case "factory":
      body = (
        <>
          <path d="M6 41 V23 L16 29 V23 L26 29 V23 L35 29 V9 H42 V41 Z" {...common} />
          <path d="M13 35 H17 M22 35 H26 M31 35 H35" {...common} />
        </>
      );
      break;
    case "alert":
      body = (
        <>
          <path d="M24 6 L43 40 H5 Z" {...common} />
          <path d="M24 18 V28" {...common} />
          <circle cx={24} cy={34} r={1.9} fill={color} stroke="none" />
        </>
      );
      break;
    case "book":
      body = (
        <>
          <path d="M24 13 C19 9 11 9 6 11 V38 C11 36 19 36 24 40 C29 36 37 36 42 38 V11 C37 9 29 9 24 13 Z" {...common} />
          <path d="M24 13 V40" {...common} />
        </>
      );
      break;
    case "user":
      body = (
        <>
          <circle cx={24} cy={16} r={8} {...common} />
          <path d="M9 42 C9 32 16 28 24 28 C32 28 39 32 39 42" {...common} />
        </>
      );
      break;
    case "usercheck":
      body = (
        <>
          <circle cx={19} cy={16} r={7} {...common} />
          <path d="M6 41 C6 31 12 27 19 27 C23 27 26 28 28 30" {...common} />
          <path d="M29 35 L34 40 L43 30" {...common} />
        </>
      );
      break;
    case "loop":
      body = (
        <>
          <path d="M38 19 A15 15 0 0 0 11 17" {...common} />
          <path d="M10 9 V17 H18" {...common} />
          <path d="M10 29 A15 15 0 0 0 37 31" {...common} />
          <path d="M38 39 V31 H30" {...common} />
        </>
      );
      break;
    case "chat":
      body = (
        <>
          <path d="M7 10 H41 V32 H23 L13 40 V32 H7 Z" {...common} />
          <path d="M14 18 H34 M14 24 H27" {...common} />
        </>
      );
      break;
    case "quote":
      body = (
        <>
          <path d="M12 5 H30 L38 13 V43 H12 Z" {...common} />
          <path d="M30 5 V13 H38" {...common} />
          <path d="M18 23 H32 M18 29 H32 M18 35 H26" {...common} />
        </>
      );
      break;
    case "server":
      body = (
        <>
          <rect x={8} y={8} width={32} height={13} rx={3} {...common} />
          <rect x={8} y={27} width={32} height={13} rx={3} {...common} />
          <circle cx={15} cy={14.5} r={1.8} fill={color} stroke="none" />
          <circle cx={15} cy={33.5} r={1.8} fill={color} stroke="none" />
        </>
      );
      break;
    case "lock":
      body = (
        <>
          <rect x={10} y={21} width={28} height={21} rx={4} {...common} />
          <path d="M16 21 V15 C16 10 20 7 24 7 C28 7 32 10 32 15 V21" {...common} />
          <path d="M24 29 V34" {...common} />
        </>
      );
      break;
    case "eye":
      body = (
        <>
          <path d="M4 24 C10 14 17 10 24 10 C31 10 38 14 44 24 C38 34 31 38 24 38 C17 38 10 34 4 24 Z" {...common} />
          <circle cx={24} cy={24} r={6} {...common} />
        </>
      );
      break;
    case "search":
      body = (
        <>
          <circle cx={21} cy={21} r={12} {...common} />
          <path d="M30 30 L41 41" {...common} />
        </>
      );
      break;
    case "gear":
      body = (
        <>
          <path d={gearPath(24, 24, 19, 14.5, 9)} {...common} />
          <circle cx={24} cy={24} r={6} {...common} />
        </>
      );
      break;
    case "clock":
      body = (
        <>
          <circle cx={24} cy={24} r={17} {...common} />
          <path d="M24 14 V24 L31 28" {...common} />
        </>
      );
      break;
    case "link":
      body = (
        <>
          <path d="M20 28 L28 20" {...common} />
          <path d="M23 15 L27 11 C30 8 35 8 38 11 C41 14 41 19 38 22 L34 26" {...common} />
          <path d="M25 33 L21 37 C18 40 13 40 10 37 C7 34 7 29 10 26 L14 22" {...common} />
        </>
      );
      break;
    case "doc":
      body = (
        <>
          <path d="M12 5 H30 L38 13 V43 H12 Z" {...common} />
          <path d="M30 5 V13 H38" {...common} />
        </>
      );
      break;
    case "check":
      body = <path d="M12 25 L20 33 L36 16" {...common} />;
      break;
    case "info":
      body = (
        <>
          <circle cx={24} cy={24} r={18} {...common} />
          <path d="M24 22 V33" {...common} />
          <circle cx={24} cy={15.5} r={1.9} fill={color} stroke="none" />
        </>
      );
      break;
    default:
      body = <circle cx={24} cy={24} r={16} {...common} />;
  }
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" style={{ display: "block", flex: "none", overflow: "visible" }}>
      {body}
    </svg>
  );
};
