// Форматирование и человеческие названия кодов признаков клиента

export const FEATURE_LABELS: Record<string, string> = {
  MAINOKVED_CODE: "Основной вид деятельности",
  REVENUE_COMPANY: "Выручка",
  REGION: "Регион",
  GROUP_ID: "Группа компаний",
  FTS_FLAG: "Внешняя торговля",
  FTS_COUNTRY_NAME: "Страны ВЭД",
  OKFS_NAME: "Форма собственности",
  AMOUNT_WORKERS_FNS_GRADATION: "Численность",
  ECO_MARK_LABEL: "Стадия бизнеса",
  CL_TYPE: "Статус в банке",
  COMPANY_AGE_YEARS_GRADATION: "Возраст компании",
  industry_position: "Место в отрасли",
  "group.top_industries": "Отрасли группы",
  "group.total_revenue": "Выручка группы",
  user_role: "Ваша роль",
  CL_PRODUCT_RKO_MARK: "РКО в Альфа-Банке",
  CL_PRODUCT_GAR_MARK: "Гарантии",
  CL_PRODUCT_LOA_MARK: "Кредиты",
  CL_PRODUCT_LEA_MARK: "Лизинг",
  CL_PRODUCT_DEP_MARK: "Депозиты",
  CL_PRODUCT_ZPP_MARK: "Зарплатный проект",
  FACTORING_MARK: "Факторинг",
  "graph.top_suppliers": "Ключевые поставщики",
  "graph.top_buyers": "Ключевые покупатели",
  "graph.supplier_industries": "Отрасли поставщиков",
  "graph.buyer_industries": "Отрасли покупателей",
  "graph.supplier_concentration": "Концентрация поставщиков",
  "graph.buyer_concentration": "Концентрация покупателей",
  "graph.supplier_unknown_share": "Поставщики вне данных банка",
  "graph.buyer_unknown_share": "Покупатели вне данных банка",
  "graph.supplier_intragroup_share": "Закупки внутри группы",
  "graph.buyer_intragroup_share": "Продажи внутри группы",
  base: "Общая значимость",
};

export const PRODUCT_NAMES: Record<string, string> = {
  rko: "РКО", guarantees: "Гарантии", loans: "Кредиты", leasing: "Лизинг", deposits: "Депозиты",
  payroll: "Зарплатный проект", factoring: "Факторинг",
};

export const featureLabel = (code: string) => FEATURE_LABELS[code] ?? code;

/** «текст причины [FEATURE]» из ранжирования -> {text, feature} */
export function parseReason(reason: string): { text: string; feature: string | null } {
  const m = reason.match(/^(.*)\s\[([^\]]+)\]$/);
  return m ? { text: m[1], feature: m[2] } : { text: reason, feature: null };
}

export function money(value: number | null | undefined): string {
  if (value == null) return "нет данных";
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${(value / 1e12).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} трлн ₽`;
  if (abs >= 1e9) return `${(value / 1e9).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} млрд ₽`;
  if (abs >= 1e6) return `${(value / 1e6).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} млн ₽`;
  return `${Math.round(value).toLocaleString("ru-RU")} ₽`;
}

export const pct = (v: number | null | undefined, digits = 0) =>
  v == null ? "—" : `${(v * 100).toLocaleString("ru-RU", { maximumFractionDigits: digits })}%`;

const MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];

export function when(iso: string | null | undefined, now = new Date()): string {
  if (!iso) return "";
  const d = new Date(iso);
  const minutes = Math.round((now.getTime() - d.getTime()) / 60000);
  const time = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  if (minutes < 1) return "только что";
  if (minutes < 60) return `${minutes} мин назад`;
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) return `сегодня, ${time}`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return `вчера, ${time}`;
  return `${d.getDate()} ${MONTHS[d.getMonth()]}${d.getFullYear() !== now.getFullYear() ? ` ${d.getFullYear()}` : ""}`;
}

export function dateShort(iso: string | null | undefined): string {
  if (!iso) return "дата неизвестна";
  const d = new Date(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

export const DIRECTION: Record<string, string> = {
  up: "рост", down: "снижение", unchanged: "без изменений", mixed: "разнонаправленно", unknown: "",
};

export const CONFIDENCE: Record<string, string> = { high: "Высокая уверенность", medium: "Средняя уверенность", low: "Низкая уверенность" };

export const ACTION_KIND: Record<string, string> = {
  action: "Действие", question: "Вопрос для анализа", scenario: "Сценарий", product: "Продукт банка",
};

export const cap = (s: string | null | undefined) => (s ? s[0].toUpperCase() + s.slice(1) : "");

export function companyTitle(c: { client_id: string; okved_name: string | null } | null | undefined): string {
  if (!c) return "";
  const name = c.okved_name ? c.okved_name.replace(/,.*$/, "") : "Компания";
  return name.length > 60 ? `${name.slice(0, 58)}…` : name;
}
