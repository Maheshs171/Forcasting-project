"""
utils/chart.py
───────────────
Generates a self-contained interactive HTML chart. No server needed.
"""

import os
import json


def _fmt(v: float, is_money: bool) -> str:
    return f"${v:,.0f}" if is_money else f"{v:,.0f}"


def save_chart(result, path: str, title: str, is_money: bool = False, pacing: dict = None) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    hist = result.historical
    fut = result.future
    hist_labels = [d.strftime("%b %Y") for d in hist["ds"]]
    hist_vals = [float(v) for v in hist["y"]]
    fut_labels = [d.strftime("%b %Y") for d in fut["ds"]]
    fut_yhat = [float(v) for v in fut["yhat"]]
    fut_low = [float(v) for v in fut["yhat_lower"]]
    fut_high = [float(v) for v in fut["yhat_upper"]]

    total_pred = sum(fut_yhat)
    total_low = sum(fut_low)
    total_high = sum(fut_high)
    n_periods = len(fut_yhat)
    avg_monthly = total_pred / max(n_periods, 1)

    warn_html = ""
    if result.warnings:
        warn_html = (
            "<div style='background:#fffbeb;border:1px solid #f59e0b;border-radius:8px;"
            "padding:10px 14px;font-size:12px;color:#92400e;margin-bottom:16px'>"
            + "<br>".join(f"! {w}" for w in result.warnings) + "</div>"
        )

    pacing_html = ""
    if pacing:
        pacing_html = f"""
        <div class="card">
          <div class="ct">Current month pacing (day {pacing['as_of_day']} of month)</div>
          <div class="stats">
            <div class="stat"><div class="sl">Month-to-date actual</div>
              <div class="sv">{_fmt(pacing['mtd_actual'], is_money)}</div></div>
            <div class="stat"><div class="sl">Projected month total</div>
              <div class="sv">{_fmt(pacing['projected'], is_money)}</div></div>
            <div class="stat"><div class="sl">Range</div>
              <div class="sv" style="font-size:16px">{_fmt(pacing['low'], is_money)} - {_fmt(pacing['high'], is_money)}</div></div>
            <div class="stat"><div class="sl">Based on</div>
              <div class="sv" style="font-size:16px">{pacing['history_months_used']} months history</div></div>
          </div>
        </div>"""

    table_rows = "".join(
        f"<tr><td style='padding:7px 12px'>{fut_labels[i]}</td>"
        f"<td style='padding:7px 12px;font-weight:500'>{_fmt(fut_yhat[i], is_money)}</td>"
        f"<td style='padding:7px 12px;color:#666'>{_fmt(fut_low[i], is_money)}</td>"
        f"<td style='padding:7px 12px;color:#666'>{_fmt(fut_high[i], is_money)}</td></tr>"
        for i in range(len(fut_labels))
    )

    all_labels = hist_labels + fut_labels
    hc = len(hist_labels)
    hist_data = [hist_vals[i] if i < hc else None for i in range(len(all_labels))]
    fore_data = [hist_vals[-1] if i == hc - 1 else (fut_yhat[i - hc] if i >= hc else None) for i in range(len(all_labels))]
    band_hi = [hist_vals[-1] if i == hc - 1 else (fut_high[i - hc] if i >= hc else None) for i in range(len(all_labels))]
    band_lo = [hist_vals[-1] if i == hc - 1 else (fut_low[i - hc] if i >= hc else None) for i in range(len(all_labels))]

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f8f9fa;color:#1a1a1a;padding:24px}}
.wrap{{max-width:1000px;margin:0 auto}}
h1{{font-size:22px;font-weight:500;margin-bottom:4px}}
.sub{{font-size:13px;color:#666;margin-bottom:20px}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}}
.stat{{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px}}
.sl{{font-size:12px;color:#666;margin-bottom:4px}}
.sv{{font-size:22px;font-weight:500}}
.card{{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:20px;margin-bottom:16px}}
.ct{{font-size:14px;font-weight:500;margin-bottom:14px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;padding:8px 12px;color:#666;font-weight:500;border-bottom:1px solid #e5e7eb}}
td{{border-bottom:1px solid #f3f4f6}}
@media(max-width:600px){{.stats{{grid-template-columns:1fr 1fr}}}}
</style></head><body>
<div class="wrap">
  <h1>{title}</h1>
  <p class="sub">Model: {result.model_name} &middot; {len(hist)} months of history &middot; {n_periods} months forecast &middot; 95% confidence interval</p>
  {warn_html}
  <div class="stats">
    <div class="stat"><div class="sl">Total predicted</div><div class="sv">{_fmt(total_pred, is_money)}</div></div>
    <div class="stat"><div class="sl">Monthly average</div><div class="sv">{_fmt(avg_monthly, is_money)}</div></div>
    <div class="stat"><div class="sl">95% range (total)</div><div class="sv" style="font-size:16px">{_fmt(total_low, is_money)} - {_fmt(total_high, is_money)}</div></div>
    <div class="stat"><div class="sl">Periods</div><div class="sv">{n_periods}</div></div>
  </div>
  {pacing_html}
  <div class="card">
    <div class="ct">Historical + forecast</div>
    <div style="position:relative;height:320px"><canvas id="chart"></canvas></div>
  </div>
  <div class="card">
    <div class="ct">Monthly forecast detail</div>
    <table><thead><tr><th>Month</th><th>Predicted</th><th>Low (95%)</th><th>High (95%)</th></tr></thead>
    <tbody>{table_rows}</tbody></table>
  </div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
new Chart(document.getElementById('chart'), {{
  type:'line',
  data:{{labels:{json.dumps(all_labels)},datasets:[
    {{label:'Band high',data:{json.dumps(band_hi)},borderColor:'transparent',backgroundColor:'rgba(226,75,74,.10)',fill:'+1',tension:.4,pointRadius:0,borderWidth:0}},
    {{label:'Band low',data:{json.dumps(band_lo)},borderColor:'transparent',backgroundColor:'rgba(226,75,74,.10)',fill:false,tension:.4,pointRadius:0,borderWidth:0}},
    {{label:'Forecast',data:{json.dumps(fore_data)},borderColor:'#e24b4a',backgroundColor:'transparent',borderWidth:2,borderDash:[5,4],tension:.4,pointRadius:3}},
    {{label:'Historical',data:{json.dumps(hist_data)},borderColor:'#378add',backgroundColor:'transparent',borderWidth:2.5,tension:.4,pointRadius:3}}
  ]}},
  options:{{responsive:true,maintainAspectRatio:false,interaction:{{mode:'index',intersect:false}},
    plugins:{{legend:{{position:'top'}}}},
    scales:{{x:{{ticks:{{maxTicksLimit:12,maxRotation:45}}}},y:{{ticks:{{callback:v=>v.toLocaleString()}}}}}}
  }}
}});
</script></body></html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path
