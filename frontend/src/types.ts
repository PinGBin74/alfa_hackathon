// Контракты backend (backend/app/schemas, contracts/*.schema.json)

export interface User {
  user_id: string;
  login: string;
  role: string;
  role_name: string;
  company_ids: string[];
}

export interface DemoAccount extends User {
  companies: { client_id: string; okved_name: string | null; region: string | null }[];
}

export interface ClientSummary {
  client_id: string;
  okved_code: string | null;
  okved_name: string | null;
  city: string | null;
  region: string | null;
  revenue: number | null;
  large_business: boolean;
  client_type: "existing" | "potential" | "closed" | null;
  group_id: string | null;
}

export interface Counterparty {
  client_id: string;
  amount: number;
  share: number;
  payments: number | null;
  okved_code: string | null;
  okved_name: string | null;
  region: string | null;
}

export interface IndustryShare {
  okved2: string;
  share: number;
  examples: string[];
}

export interface ClientProfile {
  client_id: string;
  group_id: string | null;
  okved_code: string | null;
  okved_name: string | null;
  ownership: string | null;
  age_gradation: string | null;
  stage: string | null;
  workers_fns: string | null;
  revenue: number | null;
  large_business: boolean;
  city: string | null;
  region: string | null;
  client_type: "existing" | "potential" | "closed" | null;
  products: Record<string, boolean>;
  foreign_trade: { fts_flag: boolean; countries: string[] };
  group: { group_id: string; size: number; total_revenue: number | null; large_business: boolean; top_industries: IndustryShare[] } | null;
  industry_position: { okved2: string; peers: number; revenue_rank: number | null; revenue_share: number | null } | null;
  graph: {
    top_suppliers: Counterparty[];
    top_buyers: Counterparty[];
    supplier_concentration: number | null;
    buyer_concentration: number | null;
    supplier_turnover: number;
    buyer_turnover: number;
    suppliers_count: number;
    buyers_count: number;
    supplier_industries: IndustryShare[];
    buyer_industries: IndustryShare[];
    supplier_unknown_share: number | null;
    buyer_unknown_share: number | null;
    supplier_intragroup_share: number | null;
    buyer_intragroup_share: number | null;
  };
}

export interface FactorTag {
  factor: string;
  label: string;
  direction: "up" | "down" | "unchanged" | "mixed" | "unknown" | string;
}

export interface NewsItem {
  news_id: string;
  title: string;
  url: string;
  source: string;
  published_at: string;
  summary: string | null;
  key_facts: string[];
  industries: string[];
  regions: string[];
  event_type: string | null;
  factors: FactorTag[];
  countries: string[];
  companies: string[];
  importance: number | null;
}

export interface NewsDetail extends NewsItem {
  body: string | null;
}

export interface FeedEntry {
  news: NewsItem;
  relevance_score: number;
  relevance_reasons: string[];
  relevance_parts: Record<string, number>;
  insight_id: string | null;
}

export interface Statement {
  text: string;
  basis: string[];
}

export interface SourceRef {
  source_id: string;
  type: "news" | "bank_analytics" | "client_data";
  title: string | null;
  url: string | null;
  published_at: string | null;
}

export interface Insight {
  insight_id: string;
  client_id: string;
  user_role: string | null;
  news_id: string;
  relevance_score: number | null;
  what_happened: { summary: string; confirmed_facts: { text: string; source_id: string }[]; assumptions: string[] };
  why_it_matters: { text: string; client_features: string[] }[];
  consequences: { risks: Statement[]; opportunities: Statement[]; factors_to_watch: string[] };
  suggested_actions: { text: string; kind: "action" | "question" | "scenario" | "product"; product_code: string | null }[];
  bank_position: { text: string; analytics_doc_id: string; quote_ref: string | null }[];
  ai_inference: Statement[];
  sources: SourceRef[];
  confidence: "low" | "medium" | "high" | null;
  verification: { passed: boolean; issues: string[]; iterations: number } | null;
  trace_id: string | null;
  generated_at: string;
}

export interface TraceStep {
  step: number;
  kind: string;
  name: string | null;
  title: string;
  detail: string | null;
  model: string | null;
  latency_ms: number | null;
  tokens_in?: number | null;
  tokens_out?: number | null;
  input?: Record<string, unknown> | null;
  output?: Record<string, unknown> | null;
}

export interface Progress {
  status: "idle" | "running" | "ready";
  insight_id: string | null;
  trace_id: string | null;
  steps: TraceStep[];
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
  sources?: SourceRef[];
}

export interface ChatAnswer {
  answer: string;
  source_ids: string[];
  sources: SourceRef[];
  trace_id: string | null;
}

export interface BankPosition {
  position_id: string;
  thesis: string;
  quote: string;
  factors: string[];
  forecast: { metric: string; value: string; horizon: string | null; label?: string } | null;
  horizon_passed: boolean;
  superseded_by: { position_id: string; doc_id: string; page: number; thesis: string; date: string | null } | null;
}

export interface BankPage {
  source_id: string;
  page: number;
  document: { doc_id: string; title: string; date: string | null; stale: boolean; has_file: boolean };
  positions: BankPosition[];
  text: string;
}

export interface Meta {
  factors: Record<string, string>;
  okved2: Record<string, string>;
  roles: Record<string, string>;
  products: Record<string, { feature: string; label: string }>;
}
