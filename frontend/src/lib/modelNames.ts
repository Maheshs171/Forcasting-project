// Shared model display-name/color lookup, used by every chart/table/badge
// that shows a model key. Local pipeline models have a fixed, curated set
// of ~11 keys (naive, prophet, xgboost, ...) — those get hand-picked labels
// and colors below. Azure AutoML trials don't: azure_automl.py slugifies
// whatever algorithm name Azure reports (e.g. "ExtremeRandomTrees" ->
// "extreme_random_trees", with "_2"/"_3" suffixes for repeated algorithms
// across trials), so there's no fixed list to hand-curate — prettifyModelKey
// and modelColor below generate a readable label and a stable, distinct
// color for ANY key, known or not.

const KNOWN_LABELS: Record<string, string> = {
  sarima: "SARIMA",
  ets: "ETS (Holt-Winters)",
  prophet: "Prophet",
  naive: "Seasonal Naive",
  xgboost: "XGBoost (multi-feature)",
  sarimax: "SARIMAX (multi-feature)",
  ensemble: "Ensemble",
  random_forest: "Random Forest (multi-feature)",
  extra_trees: "Extra Trees (multi-feature)",
  mlforecast: "mlforecast (LightGBM)",
  autots: "AutoTS",
};

const KNOWN_COLORS: Record<string, string> = {
  sarima: "#7c3aed",
  ets: "#0891b2",
  prophet: "#db2777",
  naive: "#64748b",
  xgboost: "#d97706",
  sarimax: "#059669",
  ensemble: "#4f46e5",
  random_forest: "#84cc16",
  extra_trees: "#14b8a6",
  mlforecast: "#ea580c",
  autots: "#c026d3",
};

// Words that should render as an acronym rather than Title Case.
const ACRONYMS = new Set(["xg", "gbm", "arima", "lgbm", "svr", "knn", "rf"]);

/** "extreme_random_trees_2" -> "Extreme Random Trees 2"; "xg_boost_regressor" -> "XG Boost Regressor" */
export function prettifyModelKey(key: string): string {
  if (KNOWN_LABELS[key]) return KNOWN_LABELS[key];
  return key
    .split("_")
    .map((word) => {
      if (/^\d+$/.test(word)) return word;
      if (ACRONYMS.has(word)) return word.toUpperCase();
      return word.charAt(0).toUpperCase() + word.slice(1);
    })
    .join(" ");
}

/** Deterministic hash -> HSL hue, so any unknown key gets a stable, visually
 * distinct color across renders instead of every unmapped model collapsing
 * onto the same fallback gray (which made a 25-model donut legend unreadable
 * — every unrecognized slice looked identical). */
export function modelColor(key: string): string {
  if (KNOWN_COLORS[key]) return KNOWN_COLORS[key];
  let hash = 0;
  for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  const hue = hash % 360;
  return `hsl(${hue}, 60%, 55%)`;
}
