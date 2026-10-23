// Небольшой набор линейных иконок (24x24, stroke=currentColor)
const PATHS: Record<string, string> = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  insight: "M4 19h16M6 15l3.5-4 3 2.5L18 7M18 7v3.5M18 7h-3.5",
  wallet: "M3 7.5A2.5 2.5 0 0 1 5.5 5H19v4M3 7.5V18a2 2 0 0 0 2 2h15V9H5.5A2.5 2.5 0 0 1 3 7.5zM16.5 14.5h.01",
  payment: "M4 7h16M4 7l3-3M4 7l3 3M20 17H4m16 0-3-3m3 3-3 3",
  doc: "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6",
  building: "M4 21V5l8-2v18M12 8h8v13M8 8h.01M8 12h.01M8 16h.01M16 12h.01M16 16h.01M2 21h20",
  gauge: "M12 14l4-4M4.9 19a9 9 0 1 1 14.2 0",
  logout: "M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10",
  link: "M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1",
  send: "M4 12 20 4l-6 16-3-7z",
  check: "M5 12.5 10 17l9-10",
  alert: "M12 8v5M12 16.5h.01M10.3 3.9 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  external: "M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
  close: "M6 6l12 12M18 6 6 18",
  up: "M7 10l5-5 5 5M12 5v14",
  thumbUp: "M7 21H4V10h3zM7 10l4-7a2 2 0 0 1 2 2v4h5.5a2 2 0 0 1 2 2.4l-1.3 7A2 2 0 0 1 17.2 21H7",
  thumbDown: "M17 3h3v11h-3zM17 14l-4 7a2 2 0 0 1-2-2v-4H5.5a2 2 0 0 1-2-2.4l1.3-7A2 2 0 0 1 6.8 3H17",
  chevron: "M9 6l6 6-6 6",
  spark: "M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18",
  layers: "M12 3 3 8l9 5 9-5zM3 13l9 5 9-5",
};

export function Icon({ name, size = 20, className }: { name: keyof typeof PATHS | string; size?: number; className?: string }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={PATHS[name] ?? ""} />
    </svg>
  );
}
