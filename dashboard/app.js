/**
 * app.js — Portfolio Dashboard
 * data.json（GitHub Actions が generate_charts.py で生成）を読み込んで UI を描画する
 */

const DATA_URL = './data.json';

// ========================
// ユーティリティ
// ========================

const fmt  = v => (v == null || v === 0) ? '---' : Math.round(v).toLocaleString('ja-JP');
const fmtF = (v, d=1) => (v == null) ? '---' : parseFloat(v).toFixed(d);

function fmtPct(val) {
  if (val == null) return '---';
  const sign = val >= 0 ? '+' : '';
  return `${sign}${parseFloat(val).toFixed(2)}%`;
}

function pnlCls(val) {
  if (val == null) return 'neutral';
  return val > 0 ? 'positive' : val < 0 ? 'negative' : 'neutral';
}

function recClass(rec) {
  if (!rec) return 'rec-hold';
  if (rec.includes('強気')) return 'rec-strong-buy';
  if (rec.includes('買い')) return 'rec-buy';
  if (rec.includes('利確') || rec.includes('一部')) return 'rec-partial';
  if (rec.includes('売却')) return 'rec-sell';
  return 'rec-hold';
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
// サマリーカード
// ========================

function renderSummary(portfolio, stockCount) {
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
    ? 'linear-gradient(135deg,#111d2e,#0d2218)'
    : 'linear-gradient(135deg,#111d2e,#221218)';
}

// ========================
// Chart.js
// ========================

function renderChart(stocks) {
  const ctx   = document.getElementById('portfolioChart').getContext('2d');
  const valid = stocks.filter(s => s.pnl_pct != null);
  const labels = valid.map(s => s.code);
  const values = valid.map(s => s.pnl_pct);
  const bg     = values.map(v => v >= 0 ? 'rgba(34,197,94,.65)' : 'rgba(244,63,94,.65)');
  const border = values.map(v => v >= 0 ? '#22c55e' : '#f43f5e');

  new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{ label:'含み損益(%)', data:values, backgroundColor:bg, borderColor:border, borderWidth:1, borderRadius:4, borderSkipped:false }]
    },
    options: {
      responsive:true, maintainAspectRatio:false,
      plugins: {
        legend: { display:false },
        tooltip: {
          backgroundColor:'#111d2e', borderColor:'#1e3050', borderWidth:1,
          titleColor:'#e8f0fe', bodyColor:'#8fabc7',
          callbacks: {
            title: ctx => `${ctx[0].label} — ${valid[ctx[0].dataIndex]?.name ?? ''}`,
            label: item => ` ${fmtPct(item.parsed.y)}`,
          }
        }
      },
      scales: {
        x: { grid:{ color:'rgba(30,48,80,.8)' }, ticks:{ color:'#8fabc7', font:{ size:10 } } },
        y: {
          grid:{ color:'rgba(30,48,80,.8)' },
          ticks:{ color:'#8fabc7', callback: v => `${v>=0?'+':''}${v.toFixed(1)}%` },
          border:{ dash:[4,4] }
        }
      },
      animation: { duration:700, easing:'easeOutQuart' }
    }
  });
}

// ========================
// AI レポートセクション
// ========================

function renderAIReport(report, today) {
  if (!report || !report.title) return;

  const section = document.getElementById('section-report');
  section.style.display = '';
  document.getElementById('report-title').textContent = `🤖 ${report.title}`;
  document.getElementById('perf-date').textContent    = today || '---';

  // アラートバナー
  const banner = document.getElementById('alerts-banner');
  if (report.alerts && report.alerts.length) {
    banner.style.display = '';
    banner.innerHTML = report.alerts.map(a => {
      const isInfo = a.startsWith('💡') || a.startsWith('ℹ️');
      return `<div class="alert-item ${isInfo ? 'info' : ''}">${a}</div>`;
    }).join('');
  }

  // マーケットストリップ
  const strip = document.getElementById('report-strip');
  const stripItems = [];
  if (report.benchmark) stripItems.push(`<span class="strip-item">📊 ${report.benchmark}</span>`);
  if (report.weather)   stripItems.push(`<span class="strip-divider">|</span><span class="strip-item">🗓️ ${report.weather}</span>`);
  if (stripItems.length) { strip.style.display = ''; strip.innerHTML = stripItems.join(''); }

  // タブコンテンツ
  setTabContent('tab-market', [
    report.market_summary ? block('🌐 市場概況', report.market_summary) : '',
    report.analysis_market ? block('🔍 詳細分析', report.analysis_market) : '',
  ]);

  setTabContent('tab-technical', [
    report.analysis_technical ? block('📉 テクニカル総合', report.analysis_technical) : '',
  ]);

  setTabContent('tab-portfolio', [
    report.analysis_portfolio ? block('🗂️ ポートフォリオ評価', report.analysis_portfolio) : '',
  ]);

  // 戦略タブ — カード2列 + 明日見通し
  const strategyHTML = `
    <div class="strategy-grid">
      <div class="strategy-card short-term">
        <div class="strategy-card-label">⚡ 短期 (今日〜今週)</div>
        <div class="strategy-card-body">${escape(report.strategy_short || '---')}</div>
      </div>
      <div class="strategy-card mid-term">
        <div class="strategy-card-label">🗓 中期 (1〜3ヶ月)</div>
        <div class="strategy-card-body">${escape(report.strategy_mid || '---')}</div>
      </div>
    </div>
    ${report.tomorrow_outlook ? `
    <div class="outlook-box">
      <strong>明日の見通し</strong>
      ${escape(report.tomorrow_outlook)}
    </div>` : ''}`;
  document.getElementById('tab-strategy').innerHTML = strategyHTML;

  // タブ切り替え
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
    });
  });
}

function block(title, content) {
  return `<div class="report-block">
    <div class="report-block-title">${title}</div>
    <div class="report-block-body">${escape(content)}</div>
  </div>`;
}

function setTabContent(id, parts) {
  document.getElementById(id).innerHTML = parts.join('');
}

function escape(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ========================
// 銘柄カード
// ========================

function renderStockCard(stock, index) {
  const { pnl, pnl_pct, current_price, quantity, avg_cost,
          change_pct_str, recommendation, consensus_target, stop_loss,
          target_divergence_comment, risk_factors, technical_detail, news_impact } = stock;

  const cls       = pnlCls(pnl);
  const pnlSign   = (pnl ?? 0) >= 0 ? '+' : '';
  const barPct    = pnl_pct != null ? Math.min(Math.abs(pnl_pct) / 30 * 100, 100) : 0;
  const barColor  = (pnl ?? 0) >= 0 ? '#22c55e' : '#f43f5e';
  const chgCls    = pnlCls(parseFloat((change_pct_str || '0').replace(/[+%]/g,'')));
  const recCls    = recClass(recommendation);

  // 目標株価乖離度
  let targetDevHTML = '';
  if (consensus_target && consensus_target > 0 && current_price > 0) {
    const dev = ((consensus_target - current_price) / current_price * 100).toFixed(1);
    const devSign = dev >= 0 ? '+' : '';
    const devColor = dev >= 0 ? '#22c55e' : '#f43f5e';
    targetDevHTML = `<span style="font-size:.6rem;color:${devColor};font-weight:700;"> (現在比 ${devSign}${dev}%)</span>`;
  }

  // チャート画像
  const imgHtml = stock.chart_url
    ? `<img class="stock-chart-img" src="${stock.chart_url}" alt="${stock.code} chart" loading="lazy"
          onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">`
      + `<div class="stock-chart-placeholder" style="display:none;">📊 チャートデータなし</div>`
    : `<div class="stock-chart-placeholder">📊 チャートデータなし</div>`;

  return `
    <div class="stock-card" style="animation-delay:${index * 0.04}s">
      <div class="stock-card-header">
        <div>
          <span class="stock-code">${stock.code}</span>
          <div class="stock-name">${stock.name}</div>
          <span class="stock-sector">${stock.sector || '---'}</span>
          ${recommendation ? `<div><span class="rec-badge ${recCls}">${recommendation}</span></div>` : ''}
        </div>
        <div class="stock-price-block">
          <div class="stock-price">¥${fmt(current_price)}</div>
          <div class="stock-change ${chgCls}">${change_pct_str || '---'}</div>
        </div>
      </div>

      <div class="stock-chart-wrap">${imgHtml}</div>

      <div class="stock-metrics">
        <div class="metric"><div class="metric-label">PER</div><div class="metric-value">${stock.per || '---'}</div></div>
        <div class="metric"><div class="metric-label">PBR</div><div class="metric-value">${stock.pbr || '---'}</div></div>
        <div class="metric"><div class="metric-label">配当</div><div class="metric-value">${stock.div_yield || '---'}</div></div>
        <div class="metric">
          <div class="metric-label">感情</div>
          <div class="metric-value" style="color:${stock.sentiment==='ポジティブ'?'#4ade80':stock.sentiment==='ネガティブ'?'#f87171':'#94a3b8'}">
            ${stock.sentiment==='ポジティブ'?'📈':stock.sentiment==='ネガティブ'?'📉':'➡️'} ${stock.sentiment||'---'}
          </div>
        </div>
      </div>

      ${(consensus_target || stop_loss) ? `
      <div class="stock-targets">
        <div class="target-item">
          <div class="target-label">🎯 機関コンセンサス目標</div>
          <div class="target-value positive">¥${consensus_target ? fmt(consensus_target) : '---'}${targetDevHTML}</div>
          ${target_divergence_comment ? `<div class="target-basis">${target_divergence_comment}</div>` : ''}
        </div>
        <div class="target-item">
          <div class="target-label">🛑 ストップロス</div>
          <div class="target-value negative">¥${stop_loss ? fmt(stop_loss) : '---'}</div>
        </div>
      </div>` : ''}

      ${technical_detail ? `
      <div class="stock-technical">
        <div class="tech-title">📉 テクニカル詳細</div>
        <div class="tech-body">${technical_detail}</div>
      </div>` : ''}

      ${(risk_factors || news_impact) ? `
      <div class="stock-risk">
        ${risk_factors ? `<div class="risk-label">⚠️ リスク要因</div>${risk_factors}<br>` : ''}
        ${news_impact  ? `<span style="color:#60a5fa;font-size:.58rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;">📰 ニュース影響</span> ${news_impact}` : ''}
      </div>` : ''}

      <div class="stock-pnl-bar">
        <div class="pnl-label-row">
          <span>${quantity}株 × ¥${fmt(avg_cost)}</span>
          <span class="pnl-amount ${cls}">
            ${pnlSign}¥${fmt(Math.abs(pnl ?? 0))} (${fmtPct(pnl_pct)})
          </span>
        </div>
        <div class="pnl-bar-track">
          <div class="pnl-bar-fill" style="width:0%;background:${barColor};" data-target="${barPct}"></div>
        </div>
      </div>
    </div>`;
}

function animatePnlBars() {
  document.querySelectorAll('.pnl-bar-fill').forEach(el => {
    const t = el.dataset.target;
    requestAnimationFrame(() => setTimeout(() => { el.style.width = `${t}%`; }, 120));
  });
}

// ========================
// 履歴
// ========================

function renderHistory(history) {
  const sec = document.getElementById('section-history');
  if (!history || !history.length) { sec.style.display = 'none'; return; }
  sec.style.display = '';
  document.getElementById('history-list').innerHTML = history.map((h, i) => {
    const time = (h.ts || '').split(' ')[1] || '';
    return `<div class="history-item" style="animation-delay:${i * .04}s">
      <div class="history-header">
        <span class="history-date">📅 ${h.date} ${time}</span>
        <span class="history-timing">${h.timing || ''}</span>
      </div>
      ${h.alerts    ? `<div class="history-alerts">⚠️ ${h.alerts}</div>` : ''}
      ${h.benchmark ? `<div class="history-benchmark">📊 ${h.benchmark}</div>` : ''}
      <div class="history-strategy">${h.strategy || 'データなし'}</div>
    </div>`;
  }).join('');
}

// ========================
// メイン
// ========================

async function init() {
  try {
    const data = await loadData();

    // タイムスタンプ
    if (data.updated_at) {
      const d = new Date(data.updated_at);
      document.getElementById('updated-at').textContent =
        `最終更新: ${d.toLocaleString('ja-JP', { timeZone:'Asia/Tokyo', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit' })}`;
    }

    const today = data.today || '---';
    document.getElementById('perf-date').textContent        = today;
    document.getElementById('stocks-count-badge').textContent = `${data.stocks.length} 銘柄`;

    renderSummary(data.portfolio, data.stocks.length);
    renderChart(data.stocks);
    renderAIReport(data.ai_report, today);

    document.getElementById('stocks-grid').innerHTML =
      data.stocks.map((s, i) => renderStockCard(s, i)).join('');
    animatePnlBars();

    renderHistory(data.history);

    document.getElementById('loading').style.display      = 'none';
    document.getElementById('main-content').style.display = '';
  } catch (err) {
    console.error('Dashboard load error:', err);
    document.getElementById('loading').style.display      = 'none';
    document.getElementById('error-screen').style.display = '';
  }
}

document.addEventListener('DOMContentLoaded', init);
