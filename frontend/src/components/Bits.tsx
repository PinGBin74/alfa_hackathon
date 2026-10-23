import type { ReactNode } from "react";

import { DIRECTION, featureLabel } from "../format";
import type { FactorTag } from "../types";

/** Релевантность 0..1 полосой: длина - значение, подпись - для экранных дикторов и при наведении. */
export function Relevance({ value, compact = false }: { value: number; compact?: boolean }) {
  const level = value >= 0.55 ? "high" : value >= 0.35 ? "mid" : "low";
  const label = level === "high" ? "Высокая значимость" : level === "mid" ? "Средняя значимость" : "Низкая значимость";
  return (
    <span className={`relevance relevance-${level}${compact ? " relevance-compact" : ""}`} title={`${label}: ${value.toFixed(2)}`}>
      <span className="relevance-track"><span className="relevance-fill" style={{ width: `${Math.round(value * 100)}%` }} /></span>
      {!compact && <span className="relevance-label">{label}</span>}
    </span>
  );
}

export function FactorChips({ factors, limit = 3 }: { factors: FactorTag[]; limit?: number }) {
  if (!factors.length) return null;
  return (
    <span className="factor-chips">
      {factors.slice(0, limit).map((f) => (
        <span key={f.factor} className="factor-chip" title={DIRECTION[f.direction] ? `${f.label}: ${DIRECTION[f.direction]}` : f.label}>
          {f.label}
          {f.direction === "up" && <span className="dir" aria-label="рост">▲</span>}
          {f.direction === "down" && <span className="dir" aria-label="снижение">▼</span>}
        </span>
      ))}
    </span>
  );
}

export function FeatureChip({ code }: { code: string }) {
  return <span className="feature-chip" title={code}>{featureLabel(code)}</span>;
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "error"; children: ReactNode }) {
  return <div className={`notice notice-${tone}`} role={tone === "error" ? "alert" : "status"}>{children}</div>;
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="skeleton" aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => <span key={i} style={{ width: `${90 - i * 12}%` }} />)}
    </div>
  );
}
