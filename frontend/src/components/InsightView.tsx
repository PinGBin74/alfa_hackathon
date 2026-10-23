import type { ReactNode } from "react";

import { ACTION_KIND, CONFIDENCE, when } from "../format";
import type { Insight } from "../types";
import { FeatureChip } from "./Bits";
import { Icon } from "./Icon";
import { Basis, SourceChip } from "./Sources";

/** Разбор события по шести вопросам кейса; у каждого утверждения - чей это голос и на что он опирается. */
export function InsightView({ insight }: { insight: Insight }) {
  const { what_happened: wh, consequences: cons } = insight;
  const removed = (insight.verification?.issues ?? []).filter((i) => i.startsWith("removed:")).length;
  return (
    <article className="insight">
      <div className="insight-status">
        {insight.verification?.passed ? (
          <span className="status status-ok"><Icon name="check" size={16} />Прошёл самопроверку</span>
        ) : (
          <span className="status status-warn"><Icon name="alert" size={16} />Часть пунктов не подтвердилась и скрыта</span>
        )}
        {insight.confidence && <span className={`status status-${insight.confidence}`}>{CONFIDENCE[insight.confidence]}</span>}
        <span className="status-meta">
          итераций: {insight.verification?.iterations ?? 1}{removed ? `, скрыто непроверенных пунктов: ${removed}` : ""}, подготовлен {when(insight.generated_at)}
        </span>
      </div>

      <div className="legend" aria-label="Обозначения">
        <span className="voice voice-news">По данным новости</span>
        <span className="voice voice-bank">Позиция Альфа-Банка</span>
        <span className="voice voice-ai">Вывод AI</span>
        <span className="voice voice-client">Признак компании</span>
      </div>

      <Section title="Что произошло">
        <p className="summary">{wh.summary}</p>
        {wh.confirmed_facts.length > 0 && (
          <ul className="statements">
            {wh.confirmed_facts.map((f, i) => (
              <li key={i} className="statement voice-news"><span>{f.text}</span><Basis ids={[f.source_id]} /></li>
            ))}
          </ul>
        )}
        {wh.assumptions.length > 0 && (
          <div className="assumptions">
            <h4>Не подтверждено: прогнозы и мнения из новости</h4>
            <ul>{wh.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>
          </div>
        )}
      </Section>

      <Section title="Почему это важно для вашей компании">
        <ul className="statements">
          {insight.why_it_matters.map((w, i) => (
            <li key={i} className="statement voice-client">
              <span>{w.text}</span>
              <span className="basis">{w.client_features.map((f) => <FeatureChip key={f} code={f} />)}</span>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Какие последствия возможны">
        <div className="two-col">
          <div>
            <h4 className="risk-title">Риски</h4>
            {cons.risks.length ? (
              <ul className="statements">{cons.risks.map((s, i) => <li key={i} className="statement voice-ai risk"><span>{s.text}</span><Basis ids={s.basis} /></li>)}</ul>
            ) : <p className="muted">Существенных рисков не выявлено.</p>}
          </div>
          <div>
            <h4 className="opp-title">Возможности</h4>
            {cons.opportunities.length ? (
              <ul className="statements">{cons.opportunities.map((s, i) => <li key={i} className="statement voice-ai opp"><span>{s.text}</span><Basis ids={s.basis} /></li>)}</ul>
            ) : <p className="muted">Явных возможностей не выявлено.</p>}
          </div>
        </div>
        {cons.factors_to_watch.length > 0 && (
          <div className="watch">
            <h4>Что может изменить ситуацию</h4>
            <ul>{cons.factors_to_watch.map((f, i) => <li key={i}>{f}</li>)}</ul>
          </div>
        )}
      </Section>

      <Section title="Что можно сделать">
        {insight.suggested_actions.length ? (
          <ul className="actions">
            {insight.suggested_actions.map((a, i) => (
              <li key={i} className={`action action-${a.kind}`}>
                <span className="action-kind">{ACTION_KIND[a.kind] ?? a.kind}</span>
                <span>{a.text}</span>
              </li>
            ))}
          </ul>
        ) : <p className="muted">Конкретных действий данные не подсказывают.</p>}
      </Section>

      <Section title="Как это оценивает Альфа-Банк" tone="bank">
        {insight.bank_position.length ? (
          <ul className="statements">
            {insight.bank_position.map((b, i) => (
              <li key={i} className="statement voice-bank">
                <span>{b.text}</span>
                <span className="basis">{b.quote_ref && <SourceChip id={b.quote_ref} />}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">В аналитике банка нет материала, который прямо касается этого события. Выводы ниже сделаны моделью.</p>
        )}
      </Section>

      {insight.ai_inference.length > 0 && (
        <Section title="Выводы AI" tone="ai" note="Сформированы моделью на основе данных компании и источников. Это не позиция банка.">
          <ul className="statements">
            {insight.ai_inference.map((s, i) => <li key={i} className="statement voice-ai"><span>{s.text}</span><Basis ids={s.basis} /></li>)}
          </ul>
        </Section>
      )}
    </article>
  );
}

function Section({ title, children, tone, note }: { title: string; children: ReactNode; tone?: "bank" | "ai"; note?: string }) {
  return (
    <section className={`insight-section${tone ? ` insight-section-${tone}` : ""}`}>
      <h3>{title}</h3>
      {note && <p className="section-note">{note}</p>}
      {children}
    </section>
  );
}
