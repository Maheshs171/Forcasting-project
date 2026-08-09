import axios from "axios";

const client = axios.create({ baseURL: "/api" });

export type MetricKey = "patients" | "encounters" | "collections" | "contact_lenses";

export interface MetricMeta {
  key: MetricKey;
  label: string;
  is_money: boolean;
}

export interface ModelMeta {
  key: string;
  name: string;
  min_months: number;
}

export interface EnvInfo {
  server: string;
  database: string;
  is_qa: boolean;
}

export interface ForecastPoint {
  month: string;
  label: string;
  predicted: number;
  low: number;
  high: number;
}

export interface HistoryPoint {
  month: string;
  label: string;
  value: number;
}

export interface YoyHistoryPoint {
  year: number;
  month: number; // 1-12
  value: number;
}

export interface BacktestCandidate {
  n_folds?: number;
  per_step_mape?: Record<string, number | null>;
  near_term_mape?: number | null;
  long_term_mape?: number | null;
  overall_mape?: number | null;
  accuracy_pct?: number;
  weighted_score?: number;
  flatness_ratio?: number;
  flat_forecast_penalty_applied?: boolean;
  skipped?: string;
}

export interface NextMonth { month: string; projected_total: number }
export interface ByEndOfYear {
  year: number;
  actual_so_far: number;
  current_month_estimate: number;
  remaining_months_forecast: number;
  total_estimate: number;
  low: number;
  high: number;
}
export interface Next12Months {
  months_covered: number;
  total_estimate: number;
  low: number;
  high: number;
}
export interface GrowthStats {
  last_month_actual: number | null;
  mtd_growth_pct: number | null;
  same_period_last_year_total: number | null;
  ytd_growth_pct: number | null;
  last_year_total: number | null;
  full_year_growth_pct: number | null;
}

export interface ModelForecast {
  model_key: string;
  model_name: string;
  is_flat: boolean;
  is_recommended: boolean;
  accuracy_pct: number | null;
  near_term_mape: number | null;
  long_term_mape: number | null;
  next_month: NextMonth | null;
  by_end_of_year: ByEndOfYear;
  next_12_months: Next12Months;
  growth: GrowthStats;
  full_forecast: ForecastPoint[];
}

export interface MetricForecast {
  metric: MetricKey;
  label: string;
  frequency?: DataFrequency;
  model_used: string;
  best_model: string;
  history_months: number;
  horizon_months: number;
  data_quality_notes: string[];
  history_full?: HistoryPoint[];
  yoy_history?: YoyHistoryPoint[];
  this_month: {
    month: string;
    month_to_date_actual: number;
    projected_total: number;
    low: number;
    high: number;
    as_of_day: number;
    history_months_used: number;
  };
  models: Record<string, ModelForecast>;
  // Mirrors of the recommended model, kept at top level for convenience
  next_month: NextMonth | null;
  by_end_of_year: ByEndOfYear;
  next_12_months?: Next12Months;
  full_forecast: ForecastPoint[];
  growth?: GrowthStats;
  backtest?: Record<string, BacktestCandidate>;
  _source_file?: string;
  _generated_at?: string;
  _chart_url?: string | null;
}

export interface BacktestReport {
  metric: string;
  candidates: Record<string, BacktestCandidate>;
  best_model: string;
}

export interface JobProgress {
  current: number;
  total: number;
  label: string | null;
}

export interface JobSummary {
  id: string;
  kind: "predict" | "validate";
  params: Record<string, unknown>;
  status: "queued" | "running" | "completed" | "failed";
  progress: JobProgress;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  log_count?: number;
  logs?: string[];
}

export interface OutputFile {
  name: string;
  metric: string | null;
  timestamp: string | null;
  ext: string;
  size: number;
  modified: string;
  url: string | null;
}

export interface DataQualityPoint { month: string; label: string; value: number }
export interface DataQualityReport {
  metric: string;
  label: string;
  raw_monthly: DataQualityPoint[];
  cleaned: DataQualityPoint[];
  excluded: DataQualityPoint[];
  notes: string[];
  raw_count: number;
  cleaned_count: number;
  excluded_count: number;
}

export interface SummaryStats {
  n: number;
  mean: number | null;
  median: number | null;
  std: number | null;
  min: number | null;
  max: number | null;
  coefficient_of_variation: number | null;
}
export interface OutlierPoint {
  month: string;
  value: number | null;
  robust_z_score: number | null;
  excluded: boolean;
  flagged_severe: boolean;
}
export interface HistogramBin { range_low: number | null; range_high: number | null; count: number }
export interface SeasonalityPoint { month: string; index: number | null }
export interface YoyRow {
  year: number;
  total: number | null;
  avg_per_month: number | null;
  months_present: number;
  growth_pct_vs_prior_year: number | null;
}
export interface AutocorrPoint { lag: number; correlation: number | null }
export interface Decomposition {
  labels: string[];
  observed: (number | null)[];
  trend: (number | null)[];
  seasonal: (number | null)[];
  residual: (number | null)[];
}
export interface VolatilityPoint { month: string; coefficient_of_variation: number | null }
export interface TransactionInsights {
  total_count: number;
  excluded_count: number;
  excluded_total_amount: number;
  amount_histogram: HistogramBin[];
  top_excluded: { date: string; amount: number | null }[];
  outlier_threshold: number;
}
export type DataFrequency = "month" | "week" | "day";

export interface DataInsightsReport {
  metric: string;
  frequency?: DataFrequency;
  has_data: boolean;
  notes: string[];
  date_range?: { start: string; end: string };
  summary_raw?: SummaryStats;
  summary_cleaned?: SummaryStats;
  gaps: string[];
  outliers: OutlierPoint[];
  outlier_threshold?: number;
  histogram: HistogramBin[];
  seasonality_index: SeasonalityPoint[];
  yoy: YoyRow[];
  autocorrelation: AutocorrPoint[];
  decomposition: Decomposition | null;
  volatility: VolatilityPoint[];
  transactions?: TransactionInsights;
}

export interface ConnectionInfo {
  name: string;
  server: string;
  database: string;
  username: string;
  port: number;
  is_active: boolean;
}

export const api = {
  health: () => client.get("/health").then((r) => r.data),
  env: () => client.get<EnvInfo>("/env").then((r) => r.data),
  metrics: () => client.get<MetricMeta[]>("/metrics").then((r) => r.data),
  models: () => client.get<ModelMeta[]>("/models").then((r) => r.data),
  configDefaults: () =>
    client.get<{ start_year: number; months: number; country: string }>("/config/defaults").then((r) => r.data),

  forecast: (metric: MetricKey, frequency: DataFrequency = "month") =>
    client.get<MetricForecast>(`/forecast/${metric}`, { params: { frequency } }).then((r) => r.data),
  allForecasts: (frequency: DataFrequency = "month") =>
    client.get<Record<MetricKey, MetricForecast | null>>("/forecast", { params: { frequency } }).then((r) => r.data),
  summaryLatest: () =>
    client.get<{ data: Record<string, MetricForecast>; generated_at: string }>("/summary/latest").then((r) => r.data),
  backtest: (frequency: DataFrequency = "month") =>
    client.get<{ data: Record<string, BacktestReport>; generated_at: string }>("/backtest", { params: { frequency } }).then((r) => r.data),
  outputs: () => client.get<OutputFile[]>("/outputs").then((r) => r.data),

  runPredict: (params: {
    metric?: string | null;
    model?: string | null;
    freq?: DataFrequency;
    months?: number;
    end_date?: string | null;
    history_end_date?: string | null;
    start_year?: number;
    country?: string;
  }) => client.post<JobSummary>("/jobs/predict", params).then((r) => r.data),

  runValidate: (params: { metric?: string | null; freq?: DataFrequency; start_year?: number; country?: string }) =>
    client.post<JobSummary>("/jobs/validate", params).then((r) => r.data),

  jobs: () => client.get<JobSummary[]>("/jobs").then((r) => r.data),
  job: (id: string) => client.get<JobSummary>(`/jobs/${id}`).then((r) => r.data),
  jobLogs: (id: string, since: number) =>
    client
      .get<{ status: string; progress: JobProgress; logs: string[]; next: number; error: string | null }>(
        `/jobs/${id}/logs`,
        { params: { since } }
      )
      .then((r) => r.data),

  dataQuality: (metric: string, startYear?: number) =>
    client.get<DataQualityReport>(`/data-quality/${metric}`, { params: startYear ? { start_year: startYear } : {} }).then((r) => r.data),

  dataInsights: (metric: string, startYear?: number, frequency: DataFrequency = "month") =>
    client
      .get<DataInsightsReport>(`/data-insights/${metric}`, {
        params: { ...(startYear ? { start_year: startYear } : {}), frequency },
      })
      .then((r) => r.data),

  connections: () => client.get<ConnectionInfo[]>("/connections").then((r) => r.data),
  addConnection: (body: { name: string; server: string; database: string; username: string; password: string; port: number; make_active: boolean }) =>
    client.post<{ saved: boolean; test_ok: boolean; test_message: string }>("/connections", body).then((r) => r.data),
  testConnection: (body: { server: string; database: string; username: string; password: string; port: number }) =>
    client.post<{ ok: boolean; message: string }>("/connections/test", body).then((r) => r.data),
  activateConnection: (name: string) => client.post(`/connections/${encodeURIComponent(name)}/activate`).then((r) => r.data),
  deleteConnection: (name: string) => client.delete(`/connections/${encodeURIComponent(name)}`).then((r) => r.data),
};

export function chartUrl(path?: string | null) {
  if (!path) return null;
  return path;
}
