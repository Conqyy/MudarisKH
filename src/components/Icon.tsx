import type { CSSProperties } from "react";

const paths = {
  home: "m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z",
  grid: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
  folder: "M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z",
  history: "M3 11a9 9 0 1 1 2.5 7M3 4v7h7M12 7v5l3 2",
  bookmark: "M6 3h12v18l-6-4-6 4Z",
  calendar: "M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2ZM7 3v4M17 3v4M3 11h18",
  settings: "m9 3-.6 2.4-2 1.2L4 6l-2 3 1.8 1.7v2.6L2 15l2 3 2.4-.6 2 1.2L9 21h6l.6-2.4 2-1.2L20 18l2-3-1.8-1.7v-2.6L22 9l-2-3-2.4.6-2-1.2L15 3ZM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
  logout: "M9 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4M15 8l4 4-4 4M9 12h11",
  menu: "M4 6h16M4 12h16M4 18h16", close: "m6 6 12 12M6 18 18 6",
  plus: "M12 5v14M5 12h14", minus: "M5 12h14",
  upload: "M12 16V3m-5 5 5-5 5 5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5",
  file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8ZM14 2v6h6M8 13h8M8 17h5",
  exam: "M9 4H5v17h14V4h-4M9 2h6v5H9ZM8 12l1 1 2-2M13 12h3M8 17l1 1 2-2M13 17h3",
  cards: "M6 7h14v14H6ZM3 17V3h14",
  summary: "M4 3h16v18H4ZM8 7h8M8 11h8M8 15h5",
  chat: "M21 11.5a8.5 8.5 0 0 1-9 8.5 10 10 0 0 1-4-.8L3 21l1.8-5A8.5 8.5 0 1 1 21 11.5ZM8 11h.01M12 11h.01M16 11h.01",
  layers: "m12 3 10 5-10 5L2 8Zm-9 10 9 5 9-5M3 18l9 5 9-5",
  "arrow-left": "M19 12H5m6-6-6 6 6 6", "arrow-right": "M5 12h14m-6-6 6 6-6 6",
  "chevron-down": "m6 9 6 6 6-6", "chevron-left": "m15 6-6 6 6 6", "chevron-right": "m9 6 6 6-6 6",
  check: "m5 12 4 4L19 6", "check-circle": "M22 11v1a10 10 0 1 1-5.9-9.1M22 4 12 14l-3-3",
  alert: "M10.3 3.9 1.8 18.7A1.5 1.5 0 0 0 3.1 21h17.8a1.5 1.5 0 0 0 1.3-2.3L13.7 3.9a2 2 0 0 0-3.4 0ZM12 9v4M12 17h.01",
  lock: "M5 10h14v11H5ZM8 10V6a4 4 0 0 1 8 0v4M12 14v3",
  moon: "M21 13A9 9 0 0 1 11 3a9 9 0 1 0 10 10Z",
  sun: "M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5",
  globe: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM3 12h18M12 3c4 4 4 14 0 18-4-4-4-14 0-18Z",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  edit: "m15 5 4 4M4 20l4-1L21 6a2.8 2.8 0 0 0-4-4L4 15ZM3 21h6",
  trash: "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7",
  download: "M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4",
  external: "M14 3h7v7M10 14 21 3M10 3H4v17h17v-6",
  clock: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM12 7v5l3 2",
  refresh: "M20 7a9 9 0 0 0-15-2L2 8m0-6v6h6M4 17a9 9 0 0 0 15 2l3-3m0 6v-6h-6",
  loader: "M12 3a9 9 0 0 1 9 9M12 21a9 9 0 0 1-9-9",
  user: "M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM4 21v-2a8 8 0 0 1 16 0v2",
  sparkles: "m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5ZM20 2v4M18 4h4",
  search: "M16 10a6 6 0 1 1-12 0 6 6 0 0 1 12 0Zm-2 4 7 7",
  book: "M12 5c-3-2-6-2-10-1v15c4-1 7-1 10 1 3-2 6-2 10-1V4c-4-1-7-1-10 1Zm0 0v15",
  audio: "M9 18V5l12-2v13M9 18a3 3 0 1 1-3-3c1.7 0 3 1.3 3 3Zm12-2a3 3 0 1 1-3-3c1.7 0 3 1.3 3 3Z",
  play: "m8 4 12 8-12 8Z", archive: "M3 3h18v5H3ZM5 8v13h14V8M9 12h6",
  link: "m10 13 4-4M8 16l-2 2a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0M16 8l2-2a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0",
  grip: "M8 5h.01M16 5h.01M8 12h.01M16 12h.01M8 19h.01M16 19h.01",
  "arrow-up": "M12 19V5m-6 6 6-6 6 6", "arrow-down": "M12 5v14m-6-6 6 6 6-6",
  fullscreen: "M8 3H3v5M16 3h5v5M3 16v5h5M21 16v5h-5",
  minimize: "M3 8h5V3M16 3v5h5M3 16h5v5M16 21v-5h5",
  send: "m22 2-7 20-4-9-9-4Zm0 0L11 13",
  info: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM12 11v6M12 7h.01",
} as const;

export type IconName = keyof typeof paths;
export default function Icon({ name, size = 20, className = "", style }: { name: IconName; size?: number; className?: string; style?: CSSProperties }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" className={`ui-icon ${className}`} style={style}><path d={paths[name]} /></svg>;
}

export function BrandMark({ className = "" }: { className?: string }) {
  return <span className={`brand-mark ${className}`} aria-hidden="true"><Icon name="layers" size={21} /></span>;
}
