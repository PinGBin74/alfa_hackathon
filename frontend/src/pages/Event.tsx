import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, ApiError, post, useApi } from "../api";
import { AgentRun, TraceView } from "../components/Agent";
import { FactorChips, Notice, Skeleton } from "../components/Bits";
import { Chat } from "../components/Chat";
import { Icon } from "../components/Icon";
import { InsightView } from "../components/InsightView";
import { SourcesProvider } from "../components/Sources";
import { companyTitle, dateShort } from "../format";
import { useSession } from "../session";
import type { Insight, NewsDetail, Progress, SourceRef, TraceStep } from "../types";

type Tab = "insight" | "trace" | "news";
const POLL_MS = 1500;

export function Event() {
  const { newsId = "" } = useParams();
  const { company } = useSession();
  const news = useApi<NewsDetail>(`/news/${newsId}`);
  const [insight, setInsight] = useState<Insight | null>(null);
  const [steps, setSteps] = useState<TraceStep[]>([]);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [tab, setTab] = useState<Tab>("insight");
  const [extraRefs, setExtraRefs] = useState<SourceRef[]>([]);
  const run = useRef(0);

  const clientId = company?.client_id;
  const generate = useCallback(async (id: number) => {
    if (!clientId) return;
    setStartedAt(Date.now());
    setSteps([]);
    const poll = setInterval(() => {
      api<Progress>(`/insights/${clientId}/${newsId}/progress`)
        .then((p) => id === run.current && p.status === "running" && setSteps(p.steps))
        .catch(() => undefined);
    }, POLL_MS);
    try {
      const result = await post<Insight>(`/insights/${clientId}/${newsId}`);
      if (id === run.current) setInsight(result);
    } catch (e) {
      if (id === run.current) setError(e as ApiError);
    } finally {
      clearInterval(poll);
      if (id === run.current) setStartedAt(null);
    }
  }, [clientId, newsId]);

  useEffect(() => {
    if (!clientId) return;
    const id = ++run.current;
    setInsight(null);
    setError(null);
    setTab("insight");
    setExtraRefs([]);
    // готовый разбор - сразу; идёт генерация (вкладка открыта повторно) или не было - запускаем/присоединяемся
    api<Progress>(`/insights/${clientId}/${newsId}/progress`)
      .then(async (p) => {
        if (id !== run.current) return;
        if (p.status === "ready" && p.insight_id) {
          const ready = await api<Insight>(`/insights/${p.insight_id}`);
          if (id === run.current) setInsight(ready);
        }
        else void generate(id);
      })
      .catch((e: ApiError) => id === run.current && setError(e));
    return () => {
      run.current++;
    };
  }, [clientId, newsId, generate]);

  const retry = () => {
    const id = ++run.current;
    setError(null);
    void generate(id);
  };

  const n = news.data;
  return (
    <div className="event-page">
      <nav className="crumbs" aria-label="Навигация">
        <Link to="/news">Новостная аналитика</Link>
        <Icon name="chevron" size={14} />
        <span>Разбор события</span>
      </nav>

      {news.loading && <Skeleton lines={3} />}
      {news.error && <Notice tone="error">{news.error.message}</Notice>}
      {n && (
        <header className="event-head">
          <p className="event-source">{n.source}, {dateShort(n.published_at)}{n.importance ? `, важность события ${n.importance} из 5` : ""}</p>
          <h1>{n.title}</h1>
          <div className="event-tags">
            <FactorChips factors={n.factors} limit={4} />
            {n.regions.length > 0 && <span className="tag">{n.regions.join(", ")}</span>}
            {n.countries.length > 0 && <span className="tag">{n.countries.slice(0, 4).join(", ")}</span>}
          </div>
          <p className="event-for">Для компании «{companyTitle(company)}»</p>
        </header>
      )}

      <div className="event-layout">
        <div className="event-main">
          <div role="tablist">
            {([["insight", "Разбор"], ["trace", "Как получен разбор"], ["news", "Текст новости"]] as [Tab, string][]).map(([t, label]) => (
              <button key={t} role="tab" aria-selected={tab === t} className={`tab${tab === t ? " active" : ""}`}
                      onClick={() => setTab(t)} disabled={t === "trace" && !insight}>{label}</button>
            ))}
          </div>

          {tab === "news" && n && (
            <div className="news-text">
              {(n.body ?? n.summary ?? "").split(/\n+/).filter(Boolean).map((p, i) => <p key={i}>{p}</p>)}
              {/^https?:/.test(n.url) && <a className="text-link" href={n.url} target="_blank" rel="noopener noreferrer">Статья на сайте источника</a>}
            </div>
          )}

          {tab !== "news" && error && (
            <Notice tone="error">
              {error.message}{" "}
              {error.status !== 403 && error.status !== 404 && <button className="button secondary small" onClick={retry}>Повторить</button>}
            </Notice>
          )}
          {tab === "insight" && !insight && !error && (startedAt ? <AgentRun steps={steps} startedAt={startedAt} /> : <Skeleton lines={6} />)}
          {insight && (
            <SourcesProvider refs={[...insight.sources, ...extraRefs]} primary={`news:${insight.news_id}`}>
              <div className="event-grid">
                <div className="event-col">
                  {tab === "insight" && (
                    <>
                      <InsightView insight={insight} />
                      <FeedbackBar insightId={insight.insight_id} />
                    </>
                  )}
                  {tab === "trace" && <TraceView insightId={insight.insight_id} />}
                </div>
                <aside className="chat-slot">
                  <Chat insightId={insight.insight_id} onSources={(refs) => setExtraRefs((r) => [...r, ...refs])} />
                </aside>
              </div>
            </SourcesProvider>
          )}
        </div>
      </div>
    </div>
  );
}

function FeedbackBar({ insightId }: { insightId: string }) {
  const [sent, setSent] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async (rating: number) => {
    setError(null);
    try {
      await post("/feedback", { insight_id: insightId, rating, comment: comment.trim() || null });
      setSent(rating);
      setOpen(false);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (sent !== null) return <p className="feedback-done"><Icon name="check" size={16} />Спасибо, оценка учтена в мониторинге качества.</p>;
  return (
    <div className="feedback">
      <span>Разбор был полезен?</span>
      <button className="button ghost small" onClick={() => void send(1)}><Icon name="thumbUp" size={16} />Да</button>
      <button className="button ghost small" onClick={() => setOpen(true)}><Icon name="thumbDown" size={16} />Нет</button>
      {open && (
        <form className="feedback-form" onSubmit={(e) => { e.preventDefault(); void send(-1); }}>
          <label htmlFor="fb">Что не так? Комментарий увидят аналитики.</label>
          <textarea id="fb" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} maxLength={1000} />
          <button className="button secondary small">Отправить</button>
        </form>
      )}
      {error && <p className="error-text">{error}</p>}
    </div>
  );
}
