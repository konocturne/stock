/**
 * app.js — Portfolio Dashboard ロジック
 * data.json（GitHub Actions が生成）を読み込んで UI を描画する
 * 外部 API 呼び出し一切なし
 */

const DATA_URL = './data.json';

// ========================
// ユーティリティ
// ========================

function fmt(val) {
  if (val === null || val === undefined || val === 0) return '---';
  return Math.round(val).toLocaleString('ja-JP');
}

function fmtPct(val) {
  if (val === null || val === undefined) return '---';
  const sign = val >= 0 ? '+' : '';
  return `${sign}${val.toFixed(2)}%`;
}

function pnlCls(val) {
  if (!val && val !== 0) return 'neutral';
  return val > 0 ? 'positive' : val < 0 ? 'negative' : 'neutral';
}

// ========================
// データ取得
// ========================

async function loadData() {
  const res = await fetch(`${DATA_URL}?t=${Date.now()}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ========================
// サマリーカード描画
// ========================

function renderSummary(portfolio, stockCount) {
  const { total_eval, total_pnl, total_pnl_pct, total_cost } = portfolio;

  document.getElementById('total-eval').textContent = `¥${fmt(total_eval)}`;
  document.getElementById('total-cost').textContent = `¥${fmt(total_cost)}`;
  document.getElementById('stock-count').textContent = `${stockCount} 銘柄`;

  const pnlEl    = document.getElementById('total-pnl');
  const pnlPctEl = document.getElementById('total-pnl-pct');
  const cls      = pnlCls(total_pnl);

  pnlEl.textContent    = `${total_pnl >= 0 ? '+' : ''}¥${fmt(Math.abs(total_pnl))}`;
  pnlEl.className      = `summary-value ${cls}`;
  pnlPctEl.textContent = fmtPct(total_pnl_pct);
  pnlPctEl.className   = `summary-sub ${cls}`;

  // P&L カードの背景をほんのり色付け
  const cardPnl = document.getElementById('card-pnl');
  cardPnl.style.background = total_pnl >= 0
    ? 'linear-gradient(135deg, #111d2e, #0d2218)'
    : 'linear-gradient(135deg, #111d2e, #221218)';
}

// ========================
// Chart.js バーチャート
// ========================

function renderChart(stocks) {
  const ctx    = document.getElementById('portfolioChart').getContext('2d');
  const valid  = stocks.filter(s => s.pnl_pct !== null && s.pnl_pct !== undefined);

  const labels = valid.map(s => `${s.code}`);
  const values = valid.map(s => s.pnl_pct);
  const bg     = values.map(v => v >= 0 ? 'rgba(34,197,94,0.65)' : 'rgba(244,63,94,0.65)');
  const border = values.map(v => v >= 0 ? '#22c55e' : '#f43f5e');

  new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: '含み損益 (%)',
        data: values,
        backgroundColor: bg,
        borderColor: border,
        borderWidth: 1,
        borderRadius: 4,
        borderSkipped: false,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#111d2e',
          borderColor: '#1e3050',
          borderWidth: 1,
          titleColor: '#e8f0fe',
          bodyColor: '#8fabc7',
          callbacks: {
            title: ctx  => `${ctx[0].label} — ${valid[ctx[0].dataIndex]?.name ?? ''}`,
            label: item => ` ${fmtPct(item.parsed.y)}`,
          },
        },
      },
      scales: {
        x: {
          grid:  { color: 'rgba(30,48,80,0.8)' },
          ticks: { color: '#8fabc7', font: { size: 10 } },
        },
        y: {
          grid:  { color: 'rgba(30,48,80,0.8)' },
          ticks: {
            color: '#8fabc7',
            callback: v => `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`,
          },
          border: { dash: [4, 4] },
        },
      },
      animation: {
        duration: 700,
        easing: 'easeOutQuart',
      },
    },
  });
}

// ========================
// 銘柄カード描画
// ========================

function renderStockCard(stock, index) {
  const { pnl, pnl_pct, current_price, quantity, avg_cost,
          change_pct_str, change_str } = stock;

  const cls      = pnlCls(pnl);
  const pnlSign  = (pnl ?? 0) >= 0 ? '+' : '';
  const maxPct   = 30; // ±30% を 100% 幅とする
  const barPct   = pnl_pct !== null ? Math.min(Math.abs(pnl_pct) / maxPct * 100, 100) : 0;
  const barColor = (pnl ?? 0) >= 0 ? '#22c55e' : '#f43f5e';
  const chgCls   = pnlCls(parseFloat((change_pct_str || '0').replace(/[+%]/g, '')));

  // チャート画像
  const imgHtml = stock.chart_url
    ? `<img class="stock-chart-img"
            src="${stock.chart_url}"
            alt="${stock.code} chart"
            loading="lazy"
            onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">`
    + `<div class="stock-chart-placeholder" style="display:none;">📊 チャートデータなし</div>`
    : `<div class="stock-chart-placeholder">📊 チャートデータなし</div>`;

  return `
    <div class="stock-card" style="animation-delay:${index * 0.045}s">
      <div class="stock-card-header">
        <div>
          <span class="stock-code">${stock.code}</span>
          <div class="stock-name">${stock.name}</div>
          <span class="stock-sector">${stock.sector || '---'}</span>
        </div>
        <div class="stock-price-block">
          <div class="stock-price">¥${fmt(current_price)}</div>
          <div class="stock-change ${chgCls}">${change_pct_str || '---'}</div>
        </div>
      </div>
      <div class="stock-chart-wrap">${imgHtml}</div>
      <div class="stock-metrics">
        <div class="metric">
          <div class="metric-label">PER</div>
          <div class="metric-value">${stock.per || '---'}</div>
        </div>
        <div class="metric">
          <div class="metric-label">PBR</div>
          <div class="metric-value">${stock.pbr || '---'}</div>
        </div>
        <div class="metric">
          <div class="metric-label">配当</div>
          <div class="metric-value">${stock.div_yield || '---'}</div>
        </div>
      </div>
      <div class="stock-pnl-bar">
        <div class="pnl-label-row">
          <span>${quantity}株 × ¥${fmt(avg_cost)}</span>
          <span class="pnl-amount ${cls}">
            ${pnlSign}¥${fmt(Math.abs(pnl ?? 0))}
            &nbsp;(${fmtPct(pnl_pct)})
          </span>
        </div>
        <div class="pnl-bar-track">
          <div class="pnl-bar-fill"
               style="width:0%;background:${barColor};"
               data-target="${barPct}"></div>
        </div>
      </div>
    </div>`;
}

// P&L バーをアニメーション表示
function animatePnlBars() {
  document.querySelectorAll('.pnl-bar-fill').forEach(el => {
    const target = el.dataset.target;
    requestAnimationFrame(() => {
      setTimeout(() => { el.style.width = `${target}%`; }, 100);
    });
  });
}

// ========================
// 履歴セクション描画
// ========================

function renderHistory(history) {
  const section = document.getElementById('history-section');
  if (!history || history.length === 0) {
    section.style.display = 'none';
    return;
  }
  section.style.display = '';
  const container = document.getElementById('history-list');

  container.innerHTML = history.map((h, i) => {
    const time = (h.ts || '').split(' ')[1] || '';
    return `
      <div class="history-item" style="animation-delay:${i * 0.04}s">
        <div class="history-header">
          <span class="history-date">📅 ${h.date} ${time}</span>
          <span class="history-timing">${h.timing || ''}</span>
        </div>
        ${h.alerts   ? `<div class="history-alerts">⚠️ ${h.alerts}</div>`       : ''}
        ${h.benchmark ? `<div class="history-benchmark">📊 ${h.benchmark}</div>` : ''}
        <div class="history-strategy">${h.strategy || 'データなし'}</div>
      </div>`;
  }).join('');
}

// ========================
// メイン初期化
// ========================

async function init() {
  try {
    const data = await loadData();

    // タイムスタンプ
    if (data.updated_at) {
      const d = new Date(data.updated_at);
      const fmt2 = d.toLocaleString('ja-JP', {
        timeZone: 'Asia/Tokyo',
        month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit',
      });
      document.getElementById('updated-at').textContent = `最終更新: ${fmt2}`;
    }

    const today = data.today || '---';
    document.getElementById('perf-date').textContent       = today;
    document.getElementById('stocks-count-badge').textContent = `${data.stocks.length} 銘柄`;

    renderSummary(data.portfolio, data.stocks.length);
    renderChart(data.stocks);

    const grid = document.getElementById('stocks-grid');
    grid.innerHTML = data.stocks.map((s, i) => renderStockCard(s, i)).join('');
    animatePnlBars();

    renderHistory(data.history);

    document.getElementById('loading').style.display       = 'none';
    document.getElementById('main-content').style.display  = '';
  } catch (err) {
    console.error('Dashboard load error:', err);
    document.getElementById('loading').style.display      = 'none';
    document.getElementById('error-screen').style.display = '';
  }
}

document.addEventListener('DOMContentLoaded', init);
