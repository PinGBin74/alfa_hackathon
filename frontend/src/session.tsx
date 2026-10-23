import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, getToken, post, setToken } from "./api";
import type { ClientSummary, Meta, User } from "./types";

interface Session {
  user: User | null;
  companies: ClientSummary[];
  company: ClientSummary | null;
  meta: Meta | null;
  ready: boolean;
  selectCompany: (clientId: string) => void;
  signIn: (login: string) => Promise<void>;
  signOut: () => void;
}

const Ctx = createContext<Session | null>(null);
const companyKey = (login: string) => `ani.company.${login}`;

function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [companies, setCompanies] = useState<ClientSummary[]>([]);
  const [companyId, setCompanyId] = useState<string | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [ready, setReady] = useState(false);

  const loadUser = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setReady(true);
      return;
    }
    try {
      const [me, list, m] = await Promise.all([api<User>("/auth/me"), api<ClientSummary[]>("/clients"), api<Meta>("/meta")]);
      setUser(me);
      setCompanies(list);
      setMeta(m);
      const stored = readStored(companyKey(me.login));
      setCompanyId(list.some((c) => c.client_id === stored) ? stored : (list[0]?.client_id ?? null));
    } catch {
      setToken(null);
      setUser(null);
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    void loadUser();
  }, [loadUser]);

  const value = useMemo<Session>(() => ({
    user,
    companies,
    meta,
    ready,
    company: companies.find((c) => c.client_id === companyId) ?? null,
    selectCompany: (id) => {
      setCompanyId(id);
      if (user) {
        try {
          localStorage.setItem(companyKey(user.login), id);
        } catch {
          /* не критично */
        }
      }
    },
    signIn: async (login) => {
      const r = await post<{ access_token: string }>("/auth/login", { login });
      setToken(r.access_token);
      setReady(false);
      await loadUser();
    },
    signOut: () => {
      setToken(null);
      setUser(null);
      setCompanies([]);
      setCompanyId(null);
    },
  }), [user, companies, companyId, meta, ready, loadUser]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): Session {
  const s = useContext(Ctx);
  if (!s) throw new Error("useSession outside SessionProvider");
  return s;
}
