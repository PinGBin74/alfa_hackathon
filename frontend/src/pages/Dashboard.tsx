import { Link } from "react-router-dom";

import { useApi } from "../api";
import { FactorChips, Relevance, Skeleton } from "../components/Bits";
import { Icon } from "../components/Icon";
import { NEW_EVENT_SCORE } from "../components/Shell";
import { companyTitle, money, parseReason, when } from "../format";
import { useSession } from "../session";
import type { FeedEntry } from "../types";

// Демо-остатки для имитации главного экрана: детерминированы по id компании, не данные банка
function demoAccounts(clientId: string) {
  let h = 0;
  for (const ch of clientId) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const base = 40_000_000 + (h % 900) * 1_000_000;
  return [
    { name: "Расчётный счёт", number: `40702 810 ${String(h % 10000).padStart(4, "0")} •• 1042`, amount: base },
    { name: "Валютный счёт", number: `40702 156 ${String((h >>> 3) % 10000).padStart(4, "0")} •• 3307`, amount: (base / 11.3) * 0.18, currency: "¥" },
    { name: "Депозит до 30 декабря", number: `42106 810 ${String((h >>> 5) % 10000).padStart(4, "0")} •• 0219`, amount: base * 1.6 },
  ];
}

function greeting(now = new Date()) {
  const h = now.getHours();
  return h < 5 ? "Доброй ночи" : h < 12 ? "Доброе утро" : h < 18 ? "Добрый день" : "Добрый вечер";
}

export function Dashboard() {
  const { company, user } = useSession();
  const feed = useApi<FeedEntry[]>(company ? `/feed/${company.client_id}?limit=20` : null);
  if (!company) return null;
  const entries = feed.data ?? [];
  const top = entries.slice(0, 3);
  const important = entries.filter((e) => e.relevance_score >= NEW_EVENT_SCORE).length;

  return (
    <div className="dashboard">
      <section className="greeting">
        <h1>{greeting()}</h1>
        <p>{companyTitle(company)}, {company.region ?? "регион не указан"}. Вы вошли как {user?.role_name}.</p>
      </section>

      <section className="insights-entry" aria-labelledby="entry-title">
        <div className="insights-entry-head">
          <div>
            <h2 id="entry-title">Новостная аналитика</h2>
            <p>
              {feed.loading ? "Подбираем события для компании…"
                : important > 0 ? `${important} ${plural(important, "событие", "события", "событий")} за две недели могут повлиять на компанию`
                : "Важных для компании событий пока нет - лента обновляется каждые 30 минут"}
            </p>
          </div>
          <Link to="/news" className="button primary">Открыть ленту</Link>
        </div>
        {feed.loading && <Skeleton lines={3} />}
        {feed.error && <p className="error-text">{feed.error.message}</p>}
        <ol className="entry-list">
          {top.map((e) => {
            const reason = e.relevance_reasons[0] ? parseReason(e.relevance_reasons[0]).text : null;
            return (
              <li key={e.news.news_id}>
                <Link to={`/news/${e.news.news_id}`} className="entry-item">
                  <Relevance value={e.relevance_score} compact />
                  <span className="entry-body">
                    <span className="entry-title">{e.news.title}</span>
                    {reason && <span className="entry-reason">Почему для вас: {reason}</span>}
                  </span>
                  <span className="entry-meta">
                    <FactorChips factors={e.news.factors} limit={1} />
                    <span>{when(e.news.published_at)}</span>
                    {e.insight_id && <span className="ready-mark"><Icon name="check" size={14} />разбор готов</span>}
                  </span>
                </Link>
              </li>
            );
          })}
        </ol>
      </section>

      <section className="accounts" aria-labelledby="accounts-title">
        <div className="section-head">
          <h2 id="accounts-title">Счета</h2>
          <span className="demo-tag" title="Остатки сгенерированы для имитации главного экрана">демо-данные</span>
        </div>
        <ul className="account-rows">
          {demoAccounts(company.client_id).map((a) => (
            <li key={a.number}>
              <span className="acc-name">{a.name}<small>{a.number}</small></span>
              <span className="acc-amount">{a.currency ? `${Math.round(a.amount).toLocaleString("ru-RU")} ${a.currency}` : money(a.amount)}</span>
            </li>
          ))}
        </ul>
        <div className="quick-actions">
          {["Создать платёж", "Выписка", "Зарплатный проект", "Валютный контроль"].map((t) => (
            <button key={t} className="button ghost" disabled title="В прототипе не реализовано">{t}</button>
          ))}
        </div>
      </section>
    </div>
  );
}

function plural(n: number, one: string, few: string, many: string) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}
