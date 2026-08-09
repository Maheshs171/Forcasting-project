"""
utils/chart.py
───────────────
Generates a self-contained interactive HTML chart. No server needed.

Styled to match the in-app dark theme exactly (same colors as
frontend/src/index.css's html.dark chart variables and .glass cards) so the
standalone chart someone opens from a shared link looks like the same
product as the dashboard, not a different tool.
"""

import os
import json

# Mirrors frontend/src/index.css's html.dark custom properties — kept in
# sync by hand since this is the one place in the app that renders a chart
# outside the React tree and can't just read the CSS variables directly.
DARK = {
    "bg": "#0b0f1a",
    "card_bg": "#131a29",
    "card_border": "#232c3f",
    "text": "#e2e8f0",
    "text_dim": "#94a3b8",
    "text_dimmer": "#64748b",
    "grid": "rgba(226, 232, 240, 0.08)",
    "tick": "rgba(226, 232, 240, 0.55)",
    "axis_line": "rgba(226, 232, 240, 0.15)",
    "tooltip_bg": "#1a2233",
    "tooltip_border": "#2d3548",
    "label_fg": "#cbd5e1",  # historical line color, matches --chart-label-fg
    "amber_bg": "rgba(217, 119, 6, 0.1)",
    "amber_border": "rgba(245, 158, 11, 0.3)",
    "amber_fg": "#fbbf24",
}

FREQ_ADVERB = {"month": "monthly", "week": "weekly", "day": "daily"}


def _fmt(v: float, is_money: bool) -> str:
    return f"${v:,.0f}" if is_money else f"{v:,.0f}"


def save_chart(
    result, path: str, title: str, is_money: bool = False, pacing: dict = None,
    freq: str = "month", color: str = "#4f46e5",
) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    period_word = freq  # "month" / "week" / "day"
    period_adverb = FREQ_ADVERB.get(freq, freq)
    label_fmt = "%b %d, %Y" if freq in ("week", "day") else "%b %Y"

    hist = result.historical
    fut = result.future
    hist_labels = [d.strftime(label_fmt) for d in hist["ds"]]
    hist_vals = [float(v) for v in hist["y"]]
    fut_labels = [d.strftime(label_fmt) for d in fut["ds"]]
    fut_yhat = [float(v) for v in fut["yhat"]]
    fut_low = [float(v) for v in fut["yhat_lower"]]
    fut_high = [float(v) for v in fut["yhat_upper"]]

    total_pred = sum(fut_yhat)
    total_low = sum(fut_low)
    total_high = sum(fut_high)
    n_periods = len(fut_yhat)
    avg_period = total_pred / max(n_periods, 1)

    warn_html = ""
    if result.warnings:
        items = "".join(f"<div>! {w}</div>" for w in result.warnings)
        warn_html = f"<div class='warn'>{items}</div>"

    pacing_html = ""
    if pacing:
        pacing_html = f"""
        <div class="card">
          <div class="ct">Current {period_word} pacing (day {pacing['as_of_day']} of {period_word})</div>
          <div class="stats">
            <div class="stat"><div class="sl">{period_word.capitalize()}-to-date actual</div>
              <div class="sv">{_fmt(pacing['mtd_actual'], is_money)}</div></div>
            <div class="stat"><div class="sl">Projected {period_word} total</div>
              <div class="sv">{_fmt(pacing['projected'], is_money)}</div></div>
            <div class="stat"><div class="sl">Range</div>
              <div class="sv sv-sm">{_fmt(pacing['low'], is_money)} - {_fmt(pacing['high'], is_money)}</div></div>
            <div class="stat"><div class="sl">Based on</div>
              <div class="sv sv-sm">{pacing['history_months_used']} {period_word}s history</div></div>
          </div>
        </div>"""

    table_rows = "".join(
        f"<tr><td>{fut_labels[i]}</td>"
        f"<td class='num'>{_fmt(fut_yhat[i], is_money)}</td>"
        f"<td class='num dim'>{_fmt(fut_low[i], is_money)}</td>"
        f"<td class='num dim'>{_fmt(fut_high[i], is_money)}</td></tr>"
        for i in range(len(fut_labels))
    )

    all_labels = hist_labels + fut_labels
    hc = len(hist_labels)
    hist_data = [hist_vals[i] if i < hc else None for i in range(len(all_labels))]
    # The forecast series starts one point early (at the last historical
    # point) so the two lines visually connect instead of leaving a gap —
    # same technique TrendChart.tsx uses.
    fore_data = [hist_vals[-1] if i == hc - 1 else (fut_yhat[i - hc] if i >= hc else None) for i in range(len(all_labels))]
    band_hi = [hist_vals[-1] if i == hc - 1 else (fut_high[i - hc] if i >= hc else None) for i in range(len(all_labels))]
    band_lo = [hist_vals[-1] if i == hc - 1 else (fut_low[i - hc] if i >= hc else None) for i in range(len(all_labels))]

    d = DARK
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:{d['bg']};color:{d['text']};padding:24px;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:1000px;margin:0 auto}}
h1{{font-size:22px;font-weight:600;letter-spacing:-0.01em;margin-bottom:4px}}
.sub{{font-size:13px;color:{d['text_dim']};margin-bottom:20px}}
.warn{{background:{d['amber_bg']};border:1px solid {d['amber_border']};border-radius:10px;padding:10px 14px;font-size:12px;color:{d['amber_fg']};margin-bottom:16px;line-height:1.6}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}}
.stat{{background:{d['card_bg']};border:1px solid {d['card_border']};border-radius:10px;padding:14px 16px}}
.sl{{font-size:11px;color:{d['text_dim']};margin-bottom:5px;text-transform:uppercase;letter-spacing:0.03em}}
.sv{{font-size:21px;font-weight:600;font-variant-numeric:tabular-nums}}
.sv-sm{{font-size:15px}}
.card{{background:{d['card_bg']};border:1px solid {d['card_border']};border-radius:14px;padding:20px;margin-bottom:16px;box-shadow:0 8px 24px -12px rgba(0,0,0,0.5)}}
.ct{{font-size:11px;font-weight:600;margin-bottom:14px;color:{d['text_dim']};text-transform:uppercase;letter-spacing:0.04em}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;padding:8px 12px;color:{d['text_dim']};font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:0.03em;border-bottom:1px solid {d['card_border']}}}
td{{padding:9px 12px;border-bottom:1px solid rgba(226,232,240,0.05)}}
td.num{{font-variant-numeric:tabular-nums;text-align:right;font-weight:500}}
td.dim{{color:{d['text_dim']};font-weight:400}}
th:nth-child(n+2), td.num{{text-align:right}}
@media(max-width:600px){{.stats{{grid-template-columns:1fr 1fr}}}}
</style></head><body>
<div class="wrap">
  <h1>{title}</h1>
  <p class="sub">Model: {result.model_name} &middot; {len(hist)} {period_word}s of history &middot; {n_periods} {period_word}s forecast ({period_adverb}) &middot; 95% confidence interval</p>
  {warn_html}
  <div class="stats">
    <div class="stat"><div class="sl">Total predicted</div><div class="sv">{_fmt(total_pred, is_money)}</div></div>
    <div class="stat"><div class="sl">{period_word.capitalize()}ly average</div><div class="sv">{_fmt(avg_period, is_money)}</div></div>
    <div class="stat"><div class="sl">95% range (total)</div><div class="sv sv-sm">{_fmt(total_low, is_money)} - {_fmt(total_high, is_money)}</div></div>
    <div class="stat"><div class="sl">Periods</div><div class="sv">{n_periods}</div></div>
  </div>
  {pacing_html}
  <div class="card">
    <div class="ct">Historical + forecast trend</div>
    <div style="position:relative;height:340px"><canvas id="chart"></canvas></div>
  </div>
  <div class="card">
    <div class="ct">{period_word.capitalize()}ly forecast detail</div>
    <table><thead><tr><th>{period_word.capitalize()}</th><th>Predicted</th><th>Low (95%)</th><th>High (95%)</th></tr></thead>
    <tbody>{table_rows}</tbody></table>
  </div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
const todayIndex = {hc - 1 if hc > 0 else -1};
const todayLine = {{
  id: 'todayLine',
  afterDraw(chart) {{
    if (todayIndex < 0) return;
    const {{ctx, chartArea, scales}} = chart;
    const x = scales.x.getPixelForValue(todayIndex);
    if (x < chartArea.left || x > chartArea.right) return;
    ctx.save();
    ctx.strokeStyle = '{d["axis_line"]}';
    ctx.setLineDash([3, 3]);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, chartArea.top);
    ctx.lineTo(x, chartArea.bottom);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '{d["tick"]}';
    ctx.font = '10px -apple-system,BlinkMacSystemFont,sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText('today', x + 5, chartArea.top + 12);
    ctx.restore();
  }}
}};
new Chart(document.getElementById('chart'), {{
  type: 'line',
  data: {{
    labels: {json.dumps(all_labels)},
    datasets: [
      {{label:'High', data:{json.dumps(band_hi)}, borderColor:'transparent', backgroundColor:'{color}1f', fill:'+1', tension:.4, pointRadius:0, borderWidth:0}},
      {{label:'Low', data:{json.dumps(band_lo)}, borderColor:'transparent', backgroundColor:'{color}1f', fill:false, tension:.4, pointRadius:0, borderWidth:0}},
      {{label:'Forecast', data:{json.dumps(fore_data)}, borderColor:'{color}', backgroundColor:'transparent', borderWidth:2.5, borderDash:[5,4], tension:.4, pointRadius:3, pointBackgroundColor:'{color}', pointBorderWidth:0}},
      {{label:'Historical', data:{json.dumps(hist_data)}, borderColor:'{d["label_fg"]}', backgroundColor:'transparent', borderWidth:2, tension:.4, pointRadius:2, pointBackgroundColor:'{d["label_fg"]}', pointBorderWidth:0}},
    ]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    interaction: {{mode:'index', intersect:false}},
    plugins: {{
      legend: {{position:'top', labels:{{color:'{d["text_dim"]}', boxWidth:12, boxHeight:2, font:{{size:11}}, filter:(item)=>item.text==='Historical'||item.text==='Forecast'}}}},
      tooltip: {{backgroundColor:'{d["tooltip_bg"]}', borderColor:'{d["tooltip_border"]}', borderWidth:1, titleColor:'{d["text"]}', bodyColor:'{d["text_dim"]}', padding:10, cornerRadius:8, displayColors:false,
        filter:(item)=>item.dataset.label==='Historical'||item.dataset.label==='Forecast'}}
    }},
    scales: {{
      x: {{grid:{{color:'{d["grid"]}', drawTicks:false}}, border:{{color:'{d["axis_line"]}'}}, ticks:{{color:'{d["tick"]}', maxTicksLimit:12, maxRotation:0, font:{{size:11}}}}}},
      y: {{grid:{{color:'{d["grid"]}', drawTicks:false}}, border:{{display:false}}, ticks:{{color:'{d["tick"]}', font:{{size:11}}, callback:v=>v.toLocaleString()}}}}
    }}
  }},
  plugins: [todayLine]
}});
</script></body></html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path
