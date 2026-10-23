import { useEffect, useState } from "react";

import { useApi } from "../api";
import { FEATURE_LABELS } from "../format";
import type { TraceStep } from "../types";
import { Notice, Skeleton } from "./Bits";

const KIND_CLASS: Record<string, string> = {
  tool_call: "tool", llm_call: "llm", plan: "plan", context: "context", verify: "verify", adapt: "adapt", final: "final",
};

function seconds(ms: number | null | undefined) {
  return ms == null ? "" : ms < 1000 ? `${ms} мс` : `${(ms / 1000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} с`;
}

/** Ход генерации: шаги агента, уже записанные в трассу, и таймер. */
export function AgentRun({ steps, startedAt }: { steps: TraceStep[]; startedAt: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const elapsed = Math.max(0, Math.round((now - startedAt) / 1000));
  return (
    <section className="agent-run" aria-live="polite" aria-labelledby="run-title">
      <div className="agent-run-head">
        <h2 id="run-title">Агент готовит разбор</h2>
        <span className="timer">{elapsed} с</span>
      </div>
      <p className="muted">
        Обычно 1-1,5 минуты: план, сбор данных о компании и аналитики банка, черновик, проверка другой моделью и правка.
        Шаги появляются по мере выполнения.
      </p>
      <ol className="steps">
        {steps.map((s) => <StepRow key={s.step} s={s} />)}
        <li className="step step-pending"><span className="step-dot" /><span className="step-title">Следующий шаг…</span></li>
      </ol>
    </section>
  );
}

function StepRow({ s, raw = false }: { s: TraceStep; raw?: boolean }) {
  return (
    <li className={`step step-${KIND_CLASS[s.kind] ?? "other"}`}>
      <span className="step-dot" />
      <span className="step-main">
        <span className="step-title">{s.title}</span>
        {s.detail && <span className="step-detail">{s.detail}</span>}
        {raw && (s.input || s.output) && (
          <details className="step-raw">
            <summary>Данные шага</summary>
            <pre>{JSON.stringify({ input: s.input, output: s.output }, null, 2)}</pre>
          </details>
        )}
      </span>
      <span className="step-meta">{[s.model, seconds(s.latency_ms)].filter(Boolean).join(", ")}</span>
    </li>
  );
}

/** Трасса готового инсайта: признаки клиента, повлиявшие на вывод, и все шаги с сырыми данными. */
export function TraceView({ insightId }: { insightId: string }) {
  const trace = useApi<TraceStep[]>(`/insights/${insightId}/trace`);
  if (trace.loading) return <Skeleton lines={8} />;
  if (trace.error || !trace.data) return <Notice tone="error">{trace.error?.message ?? "Трасса недоступна"}</Notice>;
  const steps = trace.data;
  const ctx = steps.find((s) => s.kind === "context")?.output as
    | { reasons?: string[]; exposures?: Record<string, { weight: number; features: string[] }>; bank_items?: string[] } | undefined;
  const llm = steps.filter((s) => s.kind === "llm_call");
  const cost = llm.reduce((sum, s) => sum + (Number((s.output as { cost_rub?: number } | null)?.cost_rub) || 0), 0);
  const time = steps.reduce((sum, s) => sum + (s.latency_ms ?? 0), 0);
  const features = new Map<string, number>();
  for (const e of Object.values(ctx?.exposures ?? {})) for (const f of e.features) features.set(f, Math.max(features.get(f) ?? 0, e.weight));

  return (
    <div className="trace">
      <div className="trace-summary">
        <div><strong>{steps.length}</strong><span>шагов</span></div>
        <div><strong>{steps.filter((s) => s.kind === "tool_call").length}</strong><span>вызовов инструментов</span></div>
        <div><strong>{llm.length}</strong><span>вызовов моделей</span></div>
        <div><strong>{(time / 1000).toLocaleString("ru-RU", { maximumFractionDigits: 0 })} с</strong><span>в сумме</span></div>
        <div><strong>{cost.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽</strong><span>стоимость</span></div>
      </div>
      {features.size > 0 && (
        <section>
          <h3>Признаки компании, на которых построен вывод</h3>
          <p className="muted">Чувствительность компании к факторам события по детерминированным правилам (вес 0-1).</p>
          <ul className="feature-weights">
            {[...features.entries()].sort((a, b) => b[1] - a[1]).map(([f, w]) => (
              <li key={f}><span>{FEATURE_LABELS[f] ?? f}</span><span className="weight-bar"><span style={{ width: `${Math.round(w * 100)}%` }} /></span></li>
            ))}
          </ul>
        </section>
      )}
      <section>
        <h3>Шаги агента</h3>
        <ol className="steps steps-full">{steps.map((s) => <StepRow key={s.step} s={s} raw />)}</ol>
      </section>
    </div>
  );
}
