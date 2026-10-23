import { useApi } from "../api";
import { Notice, Skeleton } from "../components/Bits";
import { companyTitle, money, pct, PRODUCT_NAMES } from "../format";
import { useSession } from "../session";
import type { ClientProfile, Counterparty, IndustryShare } from "../types";

const CLIENT_TYPE: Record<string, string> = { existing: "действующий клиент", potential: "потенциальный клиент", closed: "обслуживание закрыто" };

/** Бизнес-контекст компании (критерий 01): признаки, по которым отбираются и интерпретируются события. */
export function Company() {
  const { company, meta } = useSession();
  const profile = useApi<ClientProfile>(company ? `/clients/${company.client_id}/profile` : null);
  const okved = meta?.okved2 ?? {};
  if (!company) return null;
  const p = profile.data;

  return (
    <div className="company-page">
      <header className="page-head">
        <h1>Профиль компании</h1>
        <p className="lead">
          Так сервис видит компанию «{companyTitle(company)}» ({company.client_id}). Эти признаки определяют порядок ленты и то,
          почему событие важно именно для вас. Данные обезличены; платежи через банк - только часть оборота компании.
        </p>
      </header>
      {profile.loading && <Skeleton lines={8} />}
      {profile.error && <Notice tone="error">{profile.error.message}</Notice>}
      {p && (
        <div className="company-grid">
          <section className="panel">
            <h2>Компания</h2>
            <dl className="facts">
              <div><dt>Основной вид деятельности</dt><dd>{p.okved_code} {p.okved_name}</dd></div>
              <div><dt>Выручка</dt><dd>{money(p.revenue)}{p.large_business ? ", крупный бизнес (свыше 15 млрд ₽)" : ""}</dd></div>
              <div><dt>Регион</dt><dd>{[p.city, p.region].filter(Boolean).join(", ") || "нет данных"}</dd></div>
              <div><dt>Численность по ФНС</dt><dd>{p.workers_fns ?? "нет данных"}</dd></div>
              <div><dt>Возраст и стадия</dt><dd>{p.age_gradation ? `${p.age_gradation} лет` : "нет данных"}{p.stage ? `, ${p.stage.toLowerCase()}` : ""}</dd></div>
              <div><dt>Статус в Альфа-Банке</dt><dd>{p.client_type ? CLIENT_TYPE[p.client_type] : "нет данных"}</dd></div>
              <div><dt>Внешняя торговля</dt><dd>{p.foreign_trade.fts_flag ? `да${p.foreign_trade.countries.length ? `: ${p.foreign_trade.countries.join(", ")}` : ""}` : "нет данных ФТС"}</dd></div>
            </dl>
            <h3>Продукты в Альфа-Банке</h3>
            <ul className="products">
              {Object.entries(p.products).map(([k, v]) => (
                <li key={k} className={v ? "has" : "hasnt"}>{PRODUCT_NAMES[k] ?? k}<span className="visually-hidden">{v ? ": есть" : ": нет"}</span></li>
              ))}
            </ul>
          </section>

          <section className="panel">
            <h2>Положение в отрасли и группа</h2>
            {p.industry_position ? (
              <p className="big-line">
                <strong>{p.industry_position.revenue_rank ?? "—"}-е место</strong> по выручке среди {p.industry_position.peers.toLocaleString("ru-RU")} компаний
                класса {p.industry_position.okved2} «{okved[p.industry_position.okved2] ?? ""}» в данных банка
                {p.industry_position.revenue_share != null ? `, ${pct(p.industry_position.revenue_share, 1)} выручки класса` : ""}.
              </p>
            ) : <p className="muted">Нет данных об отрасли.</p>}
            <p className="muted">Это доля внутри выборки банка, а не доля всего рынка.</p>
            {p.group ? (
              <>
                <h3>Группа компаний</h3>
                <p>{p.group.size} юрлиц, суммарная выручка {money(p.group.total_revenue)}.</p>
                <Shares items={p.group.top_industries} okved={okved} caption="Выручка группы по отраслям" />
              </>
            ) : <p>Компания не входит в группу.</p>}
          </section>

          <section className="panel panel-wide">
            <h2>Контрагенты по платежам</h2>
            <div className="two-col">
              <Side title="Поставщики (кому компания платит)" count={p.graph.suppliers_count} turnover={p.graph.supplier_turnover}
                    top={p.graph.top_suppliers} industries={p.graph.supplier_industries} unknown={p.graph.supplier_unknown_share}
                    intragroup={p.graph.supplier_intragroup_share} hhi={p.graph.supplier_concentration} okved={okved} />
              <Side title="Покупатели (кто платит компании)" count={p.graph.buyers_count} turnover={p.graph.buyer_turnover}
                    top={p.graph.top_buyers} industries={p.graph.buyer_industries} unknown={p.graph.buyer_unknown_share}
                    intragroup={p.graph.buyer_intragroup_share} hhi={p.graph.buyer_concentration} okved={okved} />
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function Shares({ items, okved, caption }: { items: IndustryShare[]; okved: Record<string, string>; caption: string }) {
  if (!items.length) return null;
  return (
    <figure className="shares">
      <figcaption>{caption}</figcaption>
      <ul>
        {items.map((i) => (
          <li key={i.okved2}>
            <span className="share-name">{i.okved2} {okved[i.okved2] ?? ""}</span>
            <span className="share-bar"><span style={{ width: `${Math.max(1, Math.round(i.share * 100))}%` }} /></span>
            <span className="share-value">{pct(i.share, 1)}</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}

function Side(props: {
  title: string; count: number; turnover: number; top: Counterparty[]; industries: IndustryShare[];
  unknown: number | null; intragroup: number | null; hhi: number | null; okved: Record<string, string>;
}) {
  if (!props.count) return <div><h3>{props.title}</h3><p className="muted">Платежей в данных нет.</p></div>;
  const concentration = props.hhi == null ? "" : props.hhi > 0.25 ? "высокая" : props.hhi > 0.15 ? "умеренная" : "низкая";
  return (
    <div>
      <h3>{props.title}</h3>
      <p>
        {props.count} внешних контрагентов, оборот {money(props.turnover)}; концентрация {concentration} (HHI {props.hhi ?? "—"}).
        {props.unknown ? ` Отрасль неизвестна для ${pct(props.unknown)} оборота: контрагентов нет в выборке.` : ""}
        {props.intragroup ? ` Внутри группы - ${pct(props.intragroup)} платежей.` : ""}
      </p>
      <Shares items={props.industries} okved={props.okved} caption="Доля оборота по отраслям контрагентов" />
      <table className="cp-table">
        <thead><tr><th>Контрагент</th><th>Отрасль</th><th className="num">Доля</th></tr></thead>
        <tbody>
          {props.top.map((c) => (
            <tr key={c.client_id}>
              <td>{c.client_id}</td>
              <td>{c.okved_name ?? <span className="muted">нет в выборке</span>}</td>
              <td className="num">{pct(c.share, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
