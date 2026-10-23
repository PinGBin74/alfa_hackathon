import { useApi } from "../api";
import { Notice, Skeleton } from "../components/Bits";
import { pct } from "../format";
import { useSession } from "../session";

interface Metrics {
  insights_total: number;
  insights_evaluated: number;
  verified_rate: number | null;
  verified_first_iteration_rate: number | null;
  bank_view_rate: number | null;
  statements_with_sources_rate: number | null;
  why_with_client_features_rate: number | null;
  sanitizer_removals_per_insight: number | null;
  avg_llm_cost_rub: number | null;
  avg_llm_latency_ms: number | null;
  negative_feedback_rate: number | null;
  feedback_avg: number | null;
  feedback_count: number;
  insights_by_role: Record<string, number>;
  llm_spent_today_rub: number;
  llm_daily_budget_rub: number;
}

const GROUPS: { title: string; note: string; rows: { key: keyof Metrics; label: string; fmt: (v: number) => string }[] }[] = [
  {
    title: "Достоверность", note: "Самопроверка агента: правила по источникам и фактчекинг другой моделью.",
    rows: [
      { key: "verified_rate", label: "Разборы, прошедшие проверку", fmt: (v) => pct(v) },
      { key: "verified_first_iteration_rate", label: "Прошли с первой попытки", fmt: (v) => pct(v) },
      { key: "sanitizer_removals_per_insight", label: "Непроверенных пунктов скрыто на разбор", fmt: (v) => v.toLocaleString("ru-RU") },
    ],
  },
  {
    title: "Связь с источниками и компанией", note: "Каждый вывод должен опираться на источник, каждый пункт «почему важно» - на признаки компании.",
    rows: [
      { key: "statements_with_sources_rate", label: "Выводы со ссылкой на источник", fmt: (v) => pct(v) },
      { key: "why_with_client_features_rate", label: "Пункты «почему важно» с признаками компании", fmt: (v) => pct(v) },
      { key: "bank_view_rate", label: "Разборы с позицией Альфа-Банка", fmt: (v) => pct(v) },
    ],
  },
  {
    title: "Пользователи", note: "Оценки под разборами; негативные с комментарием разбираются при правке промптов и таксономии.",
    rows: [
      { key: "feedback_count", label: "Оценок", fmt: (v) => v.toLocaleString("ru-RU") },
      { key: "feedback_avg", label: "Средняя оценка (-1…1)", fmt: (v) => v.toLocaleString("ru-RU", { maximumFractionDigits: 2 }) },
      { key: "negative_feedback_rate", label: "Разборы с негативной оценкой", fmt: (v) => pct(v) },
    ],
  },
  {
    title: "Стоимость и скорость", note: "Только модели из списка кейса; дневной бюджет контролируется сервисом.",
    rows: [
      { key: "avg_llm_cost_rub", label: "Стоимость разбора", fmt: (v) => `${v.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽` },
      { key: "avg_llm_latency_ms", label: "Время моделей на разбор", fmt: (v) => `${Math.round(v / 1000)} с` },
      { key: "llm_spent_today_rub", label: "Потрачено сегодня", fmt: (v) => `${v.toLocaleString("ru-RU")} ₽` },
    ],
  },
];

/** Мониторинг качества AI-компонента (критерий 12): GET /api/feedback/metrics, без LLM. */
export function Quality() {
  const { meta } = useSession();
  const m = useApi<Metrics>("/feedback/metrics");
  return (
    <div className="quality-page">
      <header className="page-head">
        <h1>Качество AI</h1>
        <p className="lead">
          Метрики по последним разборам и обратной связи. Считаются по сохранённым разборам и трассам агента; офлайн-оценка
          на эталонных наборах - в eval/ (docs/ml.md, раздел 6).
        </p>
      </header>
      {m.loading && <Skeleton lines={8} />}
      {m.error && <Notice tone="error">{m.error.message}</Notice>}
      {m.data && (
        <>
          <p className="big-line">
            Разборов: <strong>{m.data.insights_total}</strong>, оценено по последним {m.data.insights_evaluated}. Бюджет моделей:
            потрачено {m.data.llm_spent_today_rub.toLocaleString("ru-RU")} из {m.data.llm_daily_budget_rub.toLocaleString("ru-RU")} ₽ сегодня.
          </p>
          <div className="metric-groups">
            {GROUPS.map((g) => (
              <section key={g.title} className="panel">
                <h2>{g.title}</h2>
                <p className="muted">{g.note}</p>
                <dl className="metrics">
                  {g.rows.map((r) => {
                    const v = m.data![r.key];
                    return (
                      <div key={r.key}>
                        <dt>{r.label}</dt>
                        <dd>{typeof v === "number" ? r.fmt(v) : "нет данных"}</dd>
                      </div>
                    );
                  })}
                </dl>
              </section>
            ))}
          </div>
          {Object.keys(m.data.insights_by_role).length > 0 && (
            <section className="panel">
              <h2>Разборы по ролям</h2>
              <ul className="role-list">
                {Object.entries(m.data.insights_by_role).map(([role, n]) => (
                  <li key={role}><span>{meta?.roles[role] ?? role}</span><strong>{n}</strong></li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}
