import re

with open("dashboard/app.js", "r") as f:
    app_js = f.read()

# Replace document.getElementById('xxx').textContent with optional chaining or if checks
old_summary = """function renderSummary(portfolio, stockCount) {
  const { total_eval, total_pnl, total_pnl_pct, total_cost } = portfolio;
  document.getElementById('total-eval').textContent  = `¥${fmt(total_eval)}`;
  document.getElementById('total-cost').textContent  = `¥${fmt(total_cost)}`;
  document.getElementById('stock-count').textContent = `${stockCount} 銘柄`;

  const cls = pnlCls(total_pnl);
  const pnlEl    = document.getElementById('total-pnl');
  const pnlPctEl = document.getElementById('total-pnl-pct');
  pnlEl.textContent    = `${total_pnl >= 0 ? '+' : ''}¥${fmt(Math.abs(total_pnl))}`;
  pnlEl.className      = `summary-value ${cls}`;
  pnlPctEl.textContent = fmtPct(total_pnl_pct);
  pnlPctEl.className   = `summary-sub ${cls}`;

  const cardPnl = document.getElementById('card-pnl');
  cardPnl.style.background = total_pnl >= 0
    ? 'var(--color-positive-bg)'
    : 'var(--color-negative-bg)';
  cardPnl.style.borderColor = total_pnl >= 0
    ? 'var(--color-positive)'
    : 'var(--color-negative)';
}"""

new_summary = """function renderSummary(portfolio, stockCount) {
  const { total_eval, total_pnl, total_pnl_pct, total_cost } = portfolio;
  const elTotalEval = document.getElementById('total-eval');
  if (elTotalEval) elTotalEval.textContent  = `¥${fmt(total_eval)}`;
  const elTotalCost = document.getElementById('total-cost');
  if (elTotalCost) elTotalCost.textContent  = `¥${fmt(total_cost)}`;
  const elStockCount = document.getElementById('stock-count');
  if (elStockCount) elStockCount.textContent = `${stockCount} 銘柄`;

  const cls = pnlCls(total_pnl);
  const pnlEl    = document.getElementById('total-pnl');
  const pnlPctEl = document.getElementById('total-pnl-pct');
  if (pnlEl) {
    pnlEl.textContent    = `${total_pnl >= 0 ? '+' : ''}¥${fmt(Math.abs(total_pnl))}`;
    pnlEl.className      = `summary-value ${cls}`;
  }
  if (pnlPctEl) {
    pnlPctEl.textContent = fmtPct(total_pnl_pct);
    pnlPctEl.className   = `summary-sub ${cls}`;
  }

  const cardPnl = document.getElementById('card-pnl');
  if (cardPnl) {
    cardPnl.style.background = total_pnl >= 0
      ? 'var(--color-positive-bg)'
      : 'var(--color-negative-bg)';
    cardPnl.style.borderColor = total_pnl >= 0
      ? 'var(--color-positive)'
      : 'var(--color-negative)';
  }
}"""

app_js = app_js.replace(old_summary, new_summary)

with open("dashboard/app.js", "w") as f:
    f.write(app_js)

print("Patched renderSummary in app.js")
