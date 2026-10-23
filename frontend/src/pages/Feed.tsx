import { type FormEvent, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError, post, useApi } from "../api";
import { FactorChips, FeatureChip, Notice, Relevance, Skeleton } from "../components/Bits";
import { Icon } from "../components/Icon";
import { companyTitle, money, parseReason, PRODUCT_NAMES, when } from "../format";
import { useSession } from "../session";
import type { ClientProfile, FeedEntry, NewsItem } from "../types";

const PAGE = 20;

export function Feed() {
  const { company, user, meta } = useSession();
  const [limit, setLimit] = useState(PAGE);
  const feed = useApi<FeedEntry[]>(company ? `/feed/${company.client_id}?limit=${limit}` : null);
  const profile = useApi<ClientProfile>(company ? `/clients/${company.client_id}/profile` : null);
  const [factor, setFactor] = useState<string | null>(null);

  const factors = useMemo(() => {
    const counts = new Map<string, number>();
    for (const e of feed.data ?? []) for (const f of e.news.factors.slice(0, 1)) counts.set(f.factor, (counts.get(f.factor) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
  }, [feed.data]);
  const shown = (feed.data ?? []).filter((e) => !factor || e.news.factors.some((f) => f.factor === factor));

  if (!company) return null;
  return (
    <div className="feed-page">
      <header className="page-head">
        <h1>Новостная аналитика</h1>
        <p className="lead">
          Лента подобрана для компании «{companyTitle(company)}» и роли «{user?.role_name}»: выше - события, которые сильнее всего
          затрагивают её отрасль, продукты, контрагентов и страны ВЭД. Откройте событие, чтобы получить разбор с позицией Альфа-Банка.
        </p>
      </header>

      <div className="feed-layout">
        <div className="feed-main">
          <AddByUrl />
          {factors.length > 1 && (
            <div className="filter-row" role="group" aria-label="Фильтр по главному фактору события">
              <button className={`chip-button${factor === null ? " active" : ""}`} onClick={() => setFactor(null)}>Все</button>
              {factors.map(([code, n]) => (
                <button key={code} className={`chip-button${factor === code ? " active" : ""}`} onClick={() => setFactor(factor === code ? null : code)}>
                  {meta?.factors[code] ?? code} <span className="count">{n}</span>
                </button>
              ))}
            </div>
          )}
          {feed.loading && <Skeleton lines={6} />}
          {feed.error && <Notice tone="error">{feed.error.message}</Notice>}
          {feed.data && !feed.data.length && (
            <Notice>Свежих новостей в базе нет. Запустите сбор (make ingest) или добавьте новость по ссылке выше.</Notice>
          )}
          <ol className="feed-list">
            {shown.map((e, i) => <FeedRow key={e.news.news_id} entry={e} rank={i + 1} />)}
          </ol>
          {feed.data && feed.data.length >= limit && limit < 100 && (
            <button className="button secondary" onClick={() => setLimit((l) => Math.min(100, l + PAGE))}>Показать ещё</button>
          )}
        </div>

        <aside className="feed-aside" aria-labelledby="context-title">
          <h2 id="context-title">По каким признакам подобрана лента</h2>
          {profile.loading && <Skeleton lines={5} />}
          {profile.data && <ContextSummary p={profile.data} okved={meta?.okved2 ?? {}} />}
          <Link to="/company" className="text-link">Весь профиль компании</Link>
        </aside>
      </div>
    </div>
  );
}

function FeedRow({ entry, rank }: { entry: FeedEntry; rank: number }) {
  const n: NewsItem = entry.news;
  const reasons = entry.relevance_reasons.slice(0, 2).map(parseReason);
  return (
    <li className="feed-row">
      <Link to={`/news/${n.news_id}`} className="feed-link">
        <span className="feed-rank" aria-label={`Место в ленте: ${rank}`}>{rank}</span>
        <span className="feed-body">
          <span className="feed-top">
            <span className="feed-source">{n.source}, {when(n.published_at)}</span>
            {entry.insight_id ? <span className="ready-mark"><Icon name="check" size={14} />разбор готов</span>
              : <span className="todo-mark">разбор по запросу</span>}
          </span>
          <span className="feed-title">{n.title}</span>
          {n.summary && <span className="feed-summary">{n.summary}</span>}
          {reasons.length > 0 && (
            <span className="feed-reasons">
              {reasons.map((r) => (
                <span key={r.text} className="feed-reason">
                  {r.feature && r.feature !== "base" && <FeatureChip code={r.feature} />}
                  <span>{r.text}</span>
                </span>
              ))}
            </span>
          )}
          <span className="feed-bottom">
            <Relevance value={entry.relevance_score} />
            <FactorChips factors={n.factors} />
          </span>
        </span>
      </Link>
    </li>
  );
}

function AddByUrl() {
  const navigate = useNavigate();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const item = await post<NewsItem>("/news", { url: url.trim() });
      navigate(`/news/${item.news_id}`);
    } catch (e) {
      const err = e as ApiError;
      setError(err.status === 422 ? `Ссылку не удалось обработать: ${err.message}` : err.message);
      setBusy(false);
    }
  };

  return (
    <form className="add-url" onSubmit={submit}>
      <label htmlFor="news-url">Разобрать любую новость по ссылке</label>
      <div className="input-row">
        <input id="news-url" type="url" required placeholder="https://www.interfax.ru/business/..." value={url}
               onChange={(e) => setUrl(e.target.value)} disabled={busy} />
        <button className="button secondary" disabled={busy || !url.trim()}>
          <Icon name="link" size={18} />{busy ? "Загружаем и размечаем…" : "Разобрать"}
        </button>
      </div>
      <p className="hint">Статья пройдёт тот же конвейер, что и лента: проверка ссылки, текст, дедупликация, разметка моделью.</p>
      {error && <p className="error-text" role="alert">{error}</p>}
    </form>
  );
}

function ContextSummary({ p, okved }: { p: ClientProfile; okved: Record<string, string> }) {
  const has = Object.entries(p.products).filter(([, v]) => v).map(([k]) => PRODUCT_NAMES[k] ?? k);
  const sup = p.graph.supplier_industries.slice(0, 3);
  const buy = p.graph.buyer_industries.slice(0, 3);
  return (
    <dl className="context-list">
      <div><dt>Вид деятельности</dt><dd>{p.okved_code} {p.okved_name}</dd></div>
      <div><dt>Масштаб</dt><dd>выручка {money(p.revenue)}{p.group ? `, группа из ${p.group.size} компаний` : ""}</dd></div>
      <div><dt>Регион</dt><dd>{p.region ?? "нет данных"}</dd></div>
      <div><dt>Продукты в Альфа-Банке</dt><dd>{has.join(", ") || "нет"}</dd></div>
      <div><dt>Внешняя торговля</dt><dd>{p.foreign_trade.fts_flag ? (p.foreign_trade.countries.join(", ") || "есть") : "нет"}</dd></div>
      {sup.length > 0 && <div><dt>Закупки у отраслей</dt><dd>{sup.map((i) => `${okved[i.okved2] ?? i.okved2} ${Math.round(i.share * 100)}%`).join(", ")}</dd></div>}
      {buy.length > 0 && <div><dt>Продажи отраслям</dt><dd>{buy.map((i) => `${okved[i.okved2] ?? i.okved2} ${Math.round(i.share * 100)}%`).join(", ")}</dd></div>}
    </dl>
  );
}
