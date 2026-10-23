import { createContext, type ReactNode, useContext, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, useApi } from "../api";
import { dateShort } from "../format";
import type { BankPage, NewsDetail, SourceRef } from "../types";
import { Notice, Skeleton } from "./Bits";
import { Icon } from "./Icon";

type Kind = "news" | "bank" | "client" | "other";

export function sourceKind(id: string): Kind {
  if (id.startsWith("news:")) return "news";
  if (id.startsWith("bank:")) return "bank";
  if (id.startsWith("client:")) return "client";
  return "other";
}

const KIND_LABEL: Record<Kind, string> = { news: "Новость", bank: "Альфа-Банк", client: "Данные компании", other: "Источник" };

interface Drawer {
  open: (id: string) => void;
  refs: Record<string, SourceRef>;
  primary?: string;
}

const DrawerCtx = createContext<Drawer>({ open: () => undefined, refs: {} });

/** Источники инсайта/ответа + боковая панель первоисточника. */
export function SourcesProvider({ refs, primary, children }: { refs: SourceRef[]; primary?: string; children: ReactNode }) {
  const [current, setCurrent] = useState<string | null>(null);
  const map = Object.fromEntries(refs.map((r) => [r.source_id, r]));
  return (
    <DrawerCtx.Provider value={{ open: setCurrent, refs: map, primary }}>
      {children}
      {current && <SourceDrawer id={current} ref_={map[current]} onClose={() => setCurrent(null)} />}
    </DrawerCtx.Provider>
  );
}

export function useSources() {
  return useContext(DrawerCtx);
}

export function shortTitle(id: string, ref?: SourceRef): string {
  const kind = sourceKind(id);
  if (kind === "client") return "данные компании";
  if (kind === "bank") {
    const page = id.split(":")[2];
    const title = ref?.title?.replace(/, стр\. \d+$/, "") ?? "материал банка";
    return `${title.length > 42 ? `${title.slice(0, 40)}…` : title}, стр. ${page}`;
  }
  const t = ref?.title ?? id;
  return t.length > 48 ? `${t.slice(0, 46)}…` : t;
}

export function SourceChip({ id }: { id: string }) {
  const { open, refs, primary } = useSources();
  const kind = sourceKind(id);
  return (
    <button type="button" className={`source-chip source-${kind}`} onClick={() => open(id)} title={`${KIND_LABEL[kind]}: открыть первоисточник`}>
      <span className="source-kind">{KIND_LABEL[kind]}</span>
      <span className="source-title">{id === primary ? "эта новость" : shortTitle(id, refs[id])}</span>
    </button>
  );
}

export function Basis({ ids }: { ids: string[] }) {
  if (!ids.length) return null;
  return <span className="basis">{ids.map((id) => <SourceChip key={id} id={id} />)}</span>;
}

function SourceDrawer({ id, ref_, onClose }: { id: string; ref_?: SourceRef; onClose: () => void }) {
  const kind = sourceKind(id);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="Первоисточник" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <span className={`source-kind source-kind-${kind}`}>{KIND_LABEL[kind]}</span>
          <button className="icon-button" onClick={onClose} autoFocus><Icon name="close" /><span className="visually-hidden">Закрыть</span></button>
        </div>
        {kind === "bank" && <BankSource id={id} />}
        {kind === "news" && <NewsSource id={id.slice(5)} fallback={ref_} />}
        {kind === "client" && (
          <div className="drawer-body">
            <h3>Данные о компании из выгрузки банка</h3>
            <p>Признаки компании (отрасль, продукты, ВЭД, группа, контрагенты по платежам), на которые опирается вывод. Данные обезличены.</p>
            <Link to="/company" className="button secondary" onClick={onClose}>Открыть профиль компании</Link>
          </div>
        )}
      </aside>
    </div>
  );
}

function BankSource({ id }: { id: string }) {
  const [, doc, page] = id.split(":");
  const data = useApi<BankPage>(`/analytics/${doc}/pages/${page}`);
  const [pdfError, setPdfError] = useState<string | null>(null);

  const openPdf = async () => {
    setPdfError(null);
    try {
      const blob = await api<Blob>(`/analytics/${doc}/file`);
      const url = URL.createObjectURL(blob);
      window.open(`${url}#page=${page}`, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      setPdfError((e as Error).message);
    }
  };

  if (data.loading) return <div className="drawer-body"><Skeleton lines={6} /></div>;
  if (data.error || !data.data) return <div className="drawer-body"><Notice tone="error">{data.error?.message ?? "Не найдено"}</Notice></div>;
  const p = data.data;
  return (
    <div className="drawer-body">
      <h3>{p.document.title}</h3>
      <p className="muted">Центр макроэкономического анализа Альфа-Банка, {dateShort(p.document.date)}, страница {p.page}</p>
      {p.document.stale && <Notice tone="warn">Материал устарел: выводы на его основе - только как исторический контекст.</Notice>}
      {p.positions.length > 0 && <h4>Позиции банка на этой странице</h4>}
      {p.positions.map((pos) => (
        <figure key={pos.position_id} className="bank-quote">
          <p className="bank-thesis">{pos.thesis}</p>
          <blockquote>«{pos.quote}»</blockquote>
          {pos.superseded_by && (
            <figcaption className="superseded">
              Прогноз обновлён в материале от {dateShort(pos.superseded_by.date)}: {pos.superseded_by.thesis}
            </figcaption>
          )}
          {pos.horizon_passed && <figcaption className="superseded">Срок этого прогноза уже наступил.</figcaption>}
        </figure>
      ))}
      {p.text && (
        <details className="page-text" open={!p.positions.length}>
          <summary>Текст страницы</summary>
          <p>{p.text}</p>
        </details>
      )}
      {p.document.has_file && (
        <button className="button secondary" onClick={() => void openPdf()}><Icon name="external" size={18} />Открыть PDF на странице {p.page}</button>
      )}
      {pdfError && <p className="error-text">{pdfError}</p>}
    </div>
  );
}

function NewsSource({ id, fallback }: { id: string; fallback?: SourceRef }) {
  const data = useApi<NewsDetail>(`/news/${id}`);
  const n = data.data;
  const external = n?.url && /^https?:/.test(n.url) ? n.url : fallback?.url && /^https?:/.test(fallback.url) ? fallback.url : null;
  return (
    <div className="drawer-body">
      {data.loading && <Skeleton lines={6} />}
      {data.error && <Notice tone="error">{data.error.message}</Notice>}
      {n && (
        <>
          <h3>{n.title}</h3>
          <p className="muted">{n.source}, {dateShort(n.published_at)}</p>
          {n.body ? <div className="news-text">{n.body.split(/\n+/).map((para, i) => <p key={i}>{para}</p>)}</div> : <p>{n.summary}</p>}
        </>
      )}
      {external && (
        <a className="button secondary" href={external} target="_blank" rel="noopener noreferrer">
          <Icon name="external" size={18} />Открыть статью на сайте источника
        </a>
      )}
    </div>
  );
}
