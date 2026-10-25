import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";

import { ApiError, useApi } from "../api";
import { cap, companyTitle } from "../format";
import { useSession } from "../session";
import type { DemoAccount } from "../types";

export function Login() {
  const { user, signIn } = useSession();
  const navigate = useNavigate();
  const accounts = useApi<DemoAccount[]>("/auth/demo-accounts");
  const [login, setLogin] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (user) return <Navigate to="/" replace />;

  // Пустой список - в БД не загружены данные (свежий запуск без seed): вход невозможен ни под каким логином
  const noAccounts = accounts.data !== null && accounts.data.length === 0;

  const enter = async (value: string) => {
    setBusy(value);
    setError(null);
    try {
      await signIn(value);
      navigate("/");
    } catch (e) {
      const unknown = e instanceof ApiError && e.status === 401;
      setError(unknown && noAccounts ? "Учётные записи ещё не загружены: см. подсказку ниже."
        : unknown ? "Такой учётной записи нет. Выберите тестовую ниже." : (e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="login">
      <section className="login-panel">
        <div className="brand brand-large">
          <span className="brand-mark" aria-hidden="true">А</span>
          <span className="brand-text">
            <span className="brand-name">Альфа-Бизнес</span>
            <span className="brand-tag">прототип</span>
          </span>
        </div>
        <h1>Вход для руководителей компаний</h1>
        <p className="lead">
          Сервис отбирает новости, важные для вашей компании, и объясняет их влияние с учётом аналитики Альфа-Банка.
          В прототипе вход - по тестовой учётной записи.
        </p>
        <form className="login-form" onSubmit={(e) => { e.preventDefault(); if (login.trim()) void enter(login.trim()); }}>
          <label htmlFor="login">Логин</label>
          <div className="input-row">
            <input id="login" value={login} onChange={(e) => setLogin(e.target.value)} placeholder="например, cfo_demo" autoComplete="username" />
            <button className="button primary" disabled={!login.trim() || busy !== null}>Войти</button>
          </div>
        </form>
        {error && <p className="error-text" role="alert">{error}</p>}
      </section>

      <section className="login-accounts" aria-labelledby="accounts-title">
        <h2 id="accounts-title">Тестовые учётные записи</h2>
        <p className="muted">У одной компании несколько пользователей с разными ролями: роль меняет порядок ленты и акценты разбора.</p>
        {accounts.loading && <p className="muted">Загружаем…</p>}
        {accounts.error && <p className="error-text">{accounts.error.message} Учётные записи загружаются командой make seed.</p>}
        {noAccounts && (
          <div className="error-text" role="status">
            <p>В базе нет учётных записей: данные ещё не загружены. Выполните в корне проекта</p>
            <p><code>make seed-demo</code> (синтетические данные) или <code>make seed</code> (исходные CSV кейса из data/raw)</p>
            <p>и обновите страницу.</p>
          </div>
        )}
        <ul className="account-list">
          {accounts.data?.map((a) => (
            <li key={a.login}>
              <button className="account" onClick={() => void enter(a.login)} disabled={busy !== null}>
                <span className="account-role">{cap(a.role_name)}</span>
                <span className="account-login">{a.login}</span>
                <span className="account-companies">
                  {a.companies.map((c) => (
                    <span key={c.client_id}>{companyTitle(c)}{c.region ? `, ${c.region}` : ""}</span>
                  ))}
                </span>
                {busy === a.login && <span className="account-busy">Входим…</span>}
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
