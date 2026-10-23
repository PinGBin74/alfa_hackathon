import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useApi } from "../api";
import { cap, companyTitle } from "../format";
import { useSession } from "../session";
import type { FeedEntry } from "../types";
import { Icon } from "./Icon";

const INERT = [
  { icon: "wallet", label: "Счета" },
  { icon: "payment", label: "Платежи" },
  { icon: "doc", label: "Документы" },
];
export const NEW_EVENT_SCORE = 0.45; // «важное для компании» в счётчике меню и на главной

export function Shell() {
  const { user, companies, company, selectCompany, signOut } = useSession();
  const navigate = useNavigate();
  const feed = useApi<FeedEntry[]>(company ? `/feed/${company.client_id}?limit=20` : null);
  const important = (feed.data ?? []).filter((e) => e.relevance_score >= NEW_EVENT_SCORE).length;

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">А</span>
          <span className="brand-text">
            <span className="brand-name">Альфа-Бизнес</span>
            <span className="brand-tag" title="Имитация интернет-банка для демонстрации сервиса">прототип</span>
          </span>
        </div>
        <nav className="nav" aria-label="Разделы интернет-банка">
          <NavLink to="/" end className="nav-item"><Icon name="home" />Главная</NavLink>
          <NavLink to="/news" className="nav-item nav-insights">
            <Icon name="insight" />
            <span className="nav-insights-text">Новостная аналитика<small>важное для компании</small></span>
            {important > 0 && <span className="nav-count" aria-label={`${important} событий могут повлиять на компанию`}>{important}</span>}
          </NavLink>
          <NavLink to="/company" className="nav-item"><Icon name="building" />Профиль компании</NavLink>
          {INERT.map((i) => (
            <span key={i.label} className="nav-item nav-inert" title="В прототипе раздел не реализован">
              <Icon name={i.icon} />{i.label}
            </span>
          ))}
          <NavLink to="/quality" className="nav-item"><Icon name="gauge" />Качество AI</NavLink>
        </nav>
        <p className="sidebar-note">Данные компаний обезличены. Банковские разделы - имитация.</p>
      </aside>

      <div className="main">
        <header className="topbar">
          <label className="company-switch">
            <span className="visually-hidden">Компания</span>
            <select value={company?.client_id ?? ""} onChange={(e) => selectCompany(e.target.value)}>
              {companies.map((c) => (
                <option key={c.client_id} value={c.client_id}>{companyTitle(c)} ({c.client_id})</option>
              ))}
            </select>
          </label>
          <div className="topbar-user">
            <div className="user-text">
              <strong>{cap(user?.role_name)}</strong>
              <span>{user?.login}</span>
            </div>
            <button className="icon-button" onClick={() => { signOut(); navigate("/login"); }} title="Выйти">
              <Icon name="logout" />
              <span className="visually-hidden">Выйти</span>
            </button>
          </div>
        </header>
        <main className="content" id="content">
          {company ? <Outlet /> : <div className="empty">У этой учётной записи нет доступных компаний.</div>}
        </main>
      </div>
    </div>
  );
}
