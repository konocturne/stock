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
  if (!rec) return 'hold';
  if (rec.includes('強気') || rec.includes('買い増し') || rec.includes('BUY')) return 'buy';
  if (rec.includes('売り') || rec.includes('SELL')) return 'sell';
  return 'hold';
}

// 投資判断バッジの表示調整
function renderRatingBadge(rating) {
  if (!rating) return '';
  const cleanRating = rating.split(" ")[0]; // "買い増し" 等を取得
  let cls = 'hold';
  if (cleanRating.includes('買い') || cleanRating.includes('強気買い') || cleanRating.includes('買い増し')) cls = 'buy';
  if (cleanRating.includes('売り') || cleanRating.includes('強気売り') || cleanRating.includes('売却')) cls = 'sell';
  
  return `<span class="decision-badge ${cls}">${cleanRating}</span>`;
}

// トレンド比較用矢印アイコン
function getTrendIcon(nowVal, prevVal) {
  if (nowVal > prevVal) return '<span style="color:var(--color-negative); font-weight:700;">▲ (上昇)</span>'; // 日本株は赤が上昇
  if (nowVal < prevVal) return '<span style="color:var(--color-positive); font-weight:700;">▼ (下落)</span>'; // 日本株は緑が下落
  return '<span style="color:var(--text-muted);">▶ (横ばい)</span>';
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
    ? 'var(--color-positive-bg)'
    : 'var(--color-negative-bg)';
  cardPnl.style.borderColor = total_pnl >= 0
    ? 'var(--color-positive)'
    : 'var(--color-negative)';
}

// ========================
// Chart.js 描画 (上値期待ポテンシャル横棒 & 需給散布図)
// ========================

function renderCharts(stocks) {
  // 1. 上値ポテンシャル横棒グラフ
  const ctxPot = document.getElementById('portfolioChart').getContext('2d');
  const dataList = stocks.map(s => {
    const price = s.current_price || 0;
    const target = s.consensus_target || 0;
    const pot = (price > 0 && target > 0) ? ((target - price) / price * 100) : 0;
    return {
      code: s.code,
      name: s.name,
      pot: Math.max(0, pot)
    };
  });

  new Chart(ctxPot, {
    type: 'bar',
    data: {
      labels: dataList.map(d => `${d.code} ${d.name}`),
      datasets: [{
        label: '上値ポテンシャル (%)',
        data: dataList.map(d => d.pot),
        backgroundColor: 'rgba(30, 58, 138, 0.75)', // ネイビー
        borderColor: 'var(--color-primary)',
        borderWidth: 2,
        borderRadius: 4
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1e293b',
          titleColor: '#ffffff',
          bodyColor: '#e2e8f0',
          callbacks: {
            label: (ctx) => ` 上値ポテンシャル: +${ctx.parsed.x.toFixed(1)}%`
          }
        }
      },
      scales: {
        x: {
          grid: { color: '#e2e8f0' },
          ticks: { color: '#334155', font: { weight: 'bold' }, callback: v => `+${v}%` }
        },
        y: {
          grid: { display: false },
          ticks: { color: '#0f172a', font: { weight: 'bold', size: 11 } }
        }
      }
    }
  });

  // 2. 需給散布図 (信用倍率 vs 25日乖離率)
  const ctxVal = document.getElementById('valuationPlot').getContext('2d');
  const scatterData = stocks.map(s => {
    const xVal = s.margin_ratio != null ? parseFloat(s.margin_ratio) : 3.0;
    const yVal = s.dev25 != null ? parseFloat(s.dev25) : 0.0;
    return {
      x: xVal,
      y: yVal,
      code: s.code,
      name: s.name
    };
  });

  new Chart(ctxVal, {
    type: 'scatter',
    data: {
      datasets: [{
        label: '保有銘柄',
        data: scatterData,
        backgroundColor: 'var(--color-negative)',
        borderColor: '#0f172a',
        borderWidth: 2,
        pointRadius: 10,
        pointHoverRadius: 12
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1e293b',
          titleColor: '#ffffff',
          bodyColor: '#e2e8f0',
          callbacks: {
            label: (ctx) => {
              const p = ctx.raw;
              return ` ${p.code} ${p.name}: 信用倍率 ${p.x.toFixed(2)}倍 / 25日線乖離率 ${p.y.toFixed(2)}%`;
            }
          }
        }
      },
      scales: {
        x: {
          title: { display: true, text: '信用倍率 (倍)', color: '#0f172a', font: { weight: 'bold', size: 12 } },
          grid: { color: '#e2e8f0' },
          ticks: { color: '#334155', font: { weight: 'bold' } },
          min: 0,
          max: 10
        },
        y: {
          title: { display: true, text: '25日線乖離率 (%)', color: '#0f172a', font: { weight: 'bold', size: 12 } },
          grid: { color: '#e2e8f0' },
          ticks: { color: '#334155', font: { weight: 'bold' }, callback: v => `${v}%` },
          min: -15,
          max: 15
        }
      }
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
    banner.innerHTML = report.alerts.map(a => `<div class="alert-item">${a}</div>`).join('');
  }

  // マーケットストリップ
  const strip = document.getElementById('report-strip');
  const stripItems = [];
  if (report.benchmark) stripItems.push(`<span class="strip-item">📊 ${report.benchmark}</span>`);
  if (report.weather)   stripItems.push(`<span class="strip-divider">|</span><span class="strip-item">🗓️ ${report.weather}</span>`);
  if (stripItems.length) { strip.style.display = ''; strip.innerHTML = stripItems.join(''); }

  // タブコンテンツ (重要: HTML装飾タグ highlight-marker-* を有効にするため escape せずに innerHTML に格納する)
  setTabContent('tab-market', [
    report.market_summary ? block('🌐 市場概況サマリー', report.market_summary) : '',
    report.analysis_market ? block('🔍 アナリスト市場詳細分析', report.analysis_market) : '',
  ]);

  setTabContent('tab-technical', [
    report.analysis_technical ? block('📉 テクニカル総合評価', report.analysis_technical) : '',
  ]);

  setTabContent('tab-portfolio', [
    report.analysis_portfolio ? block('🗂️ ポートフォリオ全体評価', report.analysis_portfolio) : '',
  ]);

  // 戦略タブ
  const strategyHTML = `
    <div class="strategy-grid">
      <div class="strategy-card short-term">
        <div class="strategy-card-label">⚡ 短期戦略 (今日〜今週のアクションプラン)</div>
        <div class="strategy-card-body">${report.strategy_short || '---'}</div>
      </div>
      <div class="strategy-card mid-term">
        <div class="strategy-card-label">🗓 中期戦略 (1〜3ヶ月のイベント展望)</div>
        <div class="strategy-card-body">${report.strategy_mid || '---'}</div>
      </div>
    </div>
    ${report.tomorrow_outlook ? `
    <div class="outlook-box">
      <strong>明日の地合い見通し</strong>
      ${report.tomorrow_outlook}
    </div>` : ''}`;
  document.getElementById('tab-strategy').innerHTML = strategyHTML;

  // 将来見通しロードマップテキストの挿入
  const roadmapTextEl = document.getElementById('portfolio-roadmap-text');
  if (roadmapTextEl && report.analysis_portfolio) {
    roadmapTextEl.innerHTML = report.analysis_portfolio;
  }

  // タブ切り替えイベント
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
    <div class="report-block-body">${content}</div>
  </div>`;
}

function setTabContent(id, parts) {
  document.getElementById(id).innerHTML = parts.join('');
}

// ========================
// 銘柄詳細カードレンダリング (プロトタイプ完全移植)
// ========================

function renderStockCard(stock, index) {
  const { pnl, pnl_pct, current_price, quantity, avg_cost, change_pct_str } = stock;

  const cls       = pnlCls(pnl);
  const pnlSign   = (pnl ?? 0) >= 0 ? '+' : '';
  const barPct    = pnl_pct != null ? Math.min(Math.abs(pnl_pct) / 30 * 100, 100) : 0;
  const barColor  = (pnl ?? 0) >= 0 ? 'var(--color-positive)' : 'var(--color-negative)';
  const chgCls    = pnlCls(parseFloat((change_pct_str || '0').replace(/[+%]/g,'')));

  // 各種価格指標
  const stopLoss = stock.stop_loss_guide || 0;
  const target = stock.consensus_target || 0;
  const avgCost = stock.avg_cost || 0;
  const current = stock.current_price || 0;

  // 節目メーターの座標計算
  const minVal = Math.min(stopLoss || current, avgCost || current, current) * 0.95;
  const maxVal = Math.max(target || current, current) * 1.05;
  const range = maxVal - minVal;
  const getPct = (val) => range > 0 ? ((val - minVal) / range * 100) : 50;

  const currentPct = getPct(current);
  const stopLossPct = stopLoss ? getPct(stopLoss) : null;
  const targetPct = target ? getPct(target) : null;
  const avgCostPct = avgCost ? getPct(avgCost) : null;

  // PER/PBR のスケール座標
  const perVal = parseFloat(stock.per) || 0;
  const pbrVal = parseFloat(stock.pbr) || 0;
  const perPct = Math.min(Math.max(perVal / 30 * 100, 0), 100);
  const pbrPct = Math.min(Math.max(pbrVal / 3.0 * 100, 0), 100);

  // 指標トレンドテーブルデータ取得
  const pt = stock.price_trend || [0, 0, 0, 0, 0];
  const vt = stock.volume_trend || [0, 0, 0, 0, 0];
  const rt = stock.rsi_trend || [0, 0, 0, 0, 0];
  const bt = stock.bb_width_trend || [0, 0, 0, 0, 0];

  const priceIcon = getTrendIcon(pt[0], pt[1]);
  const volIcon = getTrendIcon(vt[0], vt[1]);
  const rsiIcon = getTrendIcon(rt[0], rt[1]);
  const bbIcon = getTrendIcon(bt[0], bt[1]);

  // 証券会社目標テーブル
  const brokers = stock.broker_targets || [];
  let brokerRowsHTML = '';
  if (brokers.length > 0) {
    brokerRowsHTML = brokers.map(b => `
      <tr>
        <td class="broker-name-cell">${b.broker}</td>
        <td class="num" style="color:var(--color-primary); font-weight:700;">¥${fmt(b.target)}</td>
        <td>${b.rating || '---'}</td>
        <td>${b.date || '---'}</td>
      </tr>
    `).join('');
  } else {
    brokerRowsHTML = `<tr><td colspan="4" style="text-align:center; color:var(--text-muted);">証券会社目標のデータはありません。</td></tr>`;
  }


  // リスクプロファイル
  const profile = stock.risk_catalyst_profile || {};

  return `
    <div class="stock-card" style="animation-delay:${index * 0.04}s">
      <!-- ==================== A. 結論・取引マニュアル・リスク (横幅100%全展開) ==================== -->
      <div class="decision-row">
        <span class="decision-label">総合投資判断</span>
        ${renderRatingBadge(stock.analyst_rating)}
      </div>

      <div class="stock-meta-header">
        <div class="stock-title-area">
          <span class="stock-meta-name-code">${stock.code} ${stock.name}</span>
          <span class="stock-meta-sub">${stock.sector || '---'}</span>
        </div>
        <div class="stock-price-block-pro">
          <div class="stock-price-val-pro">¥${fmt(current_price)}</div>
          <div class="stock-price-chg-pro ${chgCls}">${change_pct_str || '---'}</div>
        </div>
      </div>

      <!-- 具体的アクション指示 -->
      <div class="live-action-box">
        <div class="live-action-title">
          <span>⚠️ 本日の最適行動・指値水準 (トレーダーマニュアル)</span>
        </div>
        <div style="font-size:13.5px; line-height:1.65; color:var(--text-main);">
          <p style="margin-bottom:8px;"><b>シナリオA (終値損切り目安割れ):</b> ${stock.execution_manual?.scenario_a || '---'}</p>
          <p style="margin-bottom:8px;"><b>シナリオB (場中の節目割れ・反発):</b> ${stock.execution_manual?.scenario_b || '---'}</p>
          <p><b>シナリオC (指値・逆指値設定):</b> ${stock.execution_manual?.scenario_c || '---'}</p>
        </div>
      </div>

      <!-- リスク・カタリストプロファイル -->
      <div class="risk-catalyst-card">
        <div class="risk-cat-item">
          <span class="risk-cat-lbl">直近決算予定日 (カタリスト警戒)</span>
          <span class="risk-cat-val" style="color:var(--color-negative);">${profile.earnings_date || '---'}</span>
        </div>
        <div class="risk-cat-item">
          <span class="risk-cat-lbl">1日最大想定損失額 (VaR 95%)</span>
          <span class="risk-cat-val">${profile.max_loss_var || '---'}</span>
        </div>
        <div class="risk-cat-item">
          <span class="risk-cat-lbl">ベータ値 (市場感応度)</span>
          <span class="risk-cat-val">${profile.beta || '---'}</span>
        </div>
        <div class="risk-cat-item">
          <span class="risk-cat-lbl">目標価格到達想定期間</span>
          <span class="risk-cat-val" style="color:var(--color-warning);">${profile.target_timeline || '---'}</span>
        </div>
      </div>

      <!-- ==================== B. テーマ別レイアウトブロック ==================== -->

      <!-- 【評価軸1】割安性評価 ＆ 判断の客観的根拠 -->
      <div class="theme-block-title-bar">📊 【評価軸1】割安性評価 ＆ 判断の客観的根拠</div>
      <div class="theme-block-grid">
        <!-- 左側 -->
        <div>
          <!-- テクニカル分析詳細 -->
          <div class="opinion-card">
            <div class="opinion-card-title">📈 テクニカル分析・モメンタム</div>
            <div style="font-size:13.5px; line-height:1.75; color:var(--text-main);">
              <p style="margin-bottom:10px;">${stock.technical_detail || '---'}</p>
              <div class="momentum-block-highlight" style="padding:10px; background-color:#fafbfc; border-radius:6px; border:1.5px dashed var(--border-color); font-size:12.5px;">
                <p style="margin-bottom:4px;"><b>出来高変化:</b> ${stock.momentum_analysis_list?.[0] || '---'}</p>
                <p style="margin-bottom:4px;"><b>RSI乖離:</b> ${stock.momentum_analysis_list?.[1] || '---'}</p>
                <p><b>ボリバン幅:</b> ${stock.momentum_analysis_list?.[2] || '---'}</p>
              </div>
            </div>
          </div>

          <!-- 感情・ニュース影響 -->
          <div class="opinion-card">
            <div class="opinion-card-title">💬 市場センチメント ＆ ニュース影響</div>
            <div style="font-size:13.5px; line-height:1.7;">
              <p style="margin-bottom:6px;">
                <b>感情極性:</b> 
                <span style="font-weight:700; color:${stock.sentiment==='ポジティブ'?'var(--color-positive)':'var(--color-negative)'}">
                  ${stock.sentiment==='ポジティブ'?'📈':'📉'} ${stock.sentiment||'ニュートラル'}
                </span>
                (${stock.sentiment_reason || ''})
              </p>
              <p><b>材料・ニュース影響:</b> ${stock.news_impact || '---'}</p>
            </div>
          </div>
        </div>
        
        <!-- 右側 -->
        <div>
          <!-- バリュエーション visualizer -->
          <div class="valuation-visualizer" style="margin-bottom:16px;">
            <div class="valuation-bar-group">
              <div class="valuation-bar-header">
                <span>PER (株価収益率)</span>
                <span class="positive">${stock.per || '---'}</span>
              </div>
              <div class="valuation-scale-container">
                <div class="valuation-marker" style="left: ${perPct}%;"></div>
              </div>
              <div class="valuation-scale-labels">
                <span>0倍</span>
                <span>15倍 (適正)</span>
                <span>30倍</span>
              </div>
            </div>
            <div class="valuation-bar-group">
              <div class="valuation-bar-header">
                <span>PBR (純資産倍率)</span>
                <span class="positive">${stock.pbr || '---'}</span>
              </div>
              <div class="valuation-scale-container">
                <div class="valuation-marker" style="left: ${pbrPct}%;"></div>
              </div>
              <div class="valuation-scale-labels">
                <span>0.0倍</span>
                <span>1.0倍 (解散価値)</span>
                <span>3.0倍</span>
              </div>
            </div>
          </div>

          <!-- 財務×テクニカル複合分析 -->
          <div class="opinion-card" style="margin-bottom:16px; background-color:#fafbfc;">
            <div class="opinion-card-title">📊 財務 ＆ テクニカル複合評価</div>
            <div style="font-size:13.5px; line-height:1.75; color:var(--text-main);">${stock.valuation_commentary || '---'}</div>
          </div>
        </div>
      </div>

      <!-- 【評価軸2】株価位置 ＆ 短期モメンタム -->
      <div class="theme-block-title-bar">📈 【評価軸2】株価位置 ＆ 短期モメンタム</div>
      <div class="theme-block-grid">
        <!-- 左側 -->
        <div>
          <!-- 節目メーター -->
          <div class="price-position-meter-card">
            <div class="meter-title">📍 株価位置 ＆ 重要節目メーター</div>
            <div class="meter-bar-wrapper">
              <div class="meter-current-pin" style="left: ${currentPct}%;"></div>
              <div class="meter-current-label" style="left: ${currentPct}%;">現在: ¥${fmt(current)}</div>
              ${stopLoss ? \`
                <div class="meter-line stop-loss" style="left: ${stopLossPct}%;"></div>
                <div class="meter-line-label" style="left: ${stopLossPct}%;">損切: ¥${fmt(stopLoss)}</div>
              \` : ''}
              ${avgCost ? \`
                <div class="meter-line" style="left: ${avgCostPct}%; background-color:#3b82f6; width:2px;"></div>
                <div class="meter-line-label" style="left: ${avgCostPct}%; color:#1e3a8a;">取得平均: ¥${fmt(avgCost)}</div>
              \` : ''}
              ${target ? \`
                <div class="meter-line target" style="left: ${targetPct}%;"></div>
                <div class="meter-line-label" style="left: ${targetPct}%;">目標: ¥${fmt(target)}</div>
              \` : ''}
            </div>
            <div class="meter-scale-extremes">
              <span>安値圏 (¥${fmt(minVal)})</span>
              <span>高値圏 (¥${fmt(maxVal)})</span>
            </div>
          </div>
          
          <!-- 個人戦略提案 -->
          <div class="opinion-card analyst" style="border-left-color: var(--color-primary-border); background-color: var(--color-primary-light);">
            <div class="opinion-card-title" style="color: var(--color-primary);">👤 個人宛トレード戦略提案</div>
            <div style="font-size:13.5px; line-height:1.7; color: var(--text-dark);">${stock.personal_action || '---'}</div>
          </div>
        </div>

        <!-- 右側 -->
        <div>
          <!-- 指標トレンド比較テーブル -->
          <div class="trend-table-card" style="margin-bottom:16px;">
            <div class="trend-table-title">📊 主要指標の多期間トレンド比較</div>
            <div class="table-responsive" style="overflow-x: auto; -webkit-overflow-scrolling: touch;">
            <table class="data-table">
              <thead>
                <tr>
                  <th>指標項目</th>
                  <th>現在値</th>
                  <th>前日比</th>
                  <th>5日平均 (1週)</th>
                  <th>25日平均 (1月)</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td><b>株価 (円)</b></td>
                  <td class="num">¥${fmt(pt[0])}</td>
                  <td class="num">${priceIcon}</td>
                  <td class="num">¥${fmt(pt[2])}</td>
                  <td class="num">¥${fmt(pt[3])}</td>
                </tr>
                <tr>
                  <td><b>出来高 (万株)</b></td>
                  <td class="num">${fmtF(vt[0], 1)}</td>
                  <td class="num">${volIcon}</td>
                  <td class="num">${fmtF(vt[2], 1)}</td>
                  <td class="num">${fmtF(vt[3], 1)}</td>
                </tr>
                <tr>
                  <td><b>RSI (14日)</b></td>
                  <td class="num">${fmtF(rt[0], 1)}</td>
                  <td class="num">${rsiIcon}</td>
                  <td class="num">${fmtF(rt[2], 1)}</td>
                  <td class="num">${fmtF(rt[3], 1)}</td>
                </tr>
                <tr>
                  <td><b>ボリバン幅 (%)</b></td>
                  <td class="num">${fmtF(bt[0], 1)}%</td>
                  <td class="num">${bbIcon}</td>
                  <td class="num">${fmtF(bt[2], 1)}%</td>
                  <td class="num">${fmtF(bt[3], 1)}%</td>
                </tr>
              </tbody>
            </table>
            </div>
          </div>

          <!-- 証券会社目標株価テーブル -->
          <div class="trend-table-card" style="margin-bottom:16px;">
            <div class="trend-table-title">🏢 証券会社別の最新レーティング ＆ 目標株価</div>
            <div class="table-responsive" style="overflow-x: auto; -webkit-overflow-scrolling: touch;">
            <table class="data-table">
              <thead>
                <tr>
                  <th>証券会社</th>
                  <th>目標価格</th>
                  <th>格付け</th>
                  <th>発表日</th>
                </tr>
              </thead>
              <tbody>
                ${brokerRowsHTML}
              </tbody>
            </table>
            </div>
          </div>

          <!-- アナリスト目標価格の算出根拠 -->
          <div class="opinion-card analyst" style="margin-bottom:16px;">
            <div class="opinion-card-title">📝 アナリスト目標価格の算出根拠</div>
            <div style="font-size:13.5px; line-height:1.7; color: var(--text-dark);">${stock.broker_commentary || '---'}</div>
          </div>
        </div>
      </div>

      <!-- 下部: 過去類似チャートアノマリー ＆ マクロニュース競合相関 (横に大きく展開) -->
      <div class="full-width-block">
        <div class="theme-block-title-bar">📅 過去の類似チャートパターン分析</div>
        <div class="pattern-analogy-card">
          <div style="font-size:14px; line-height:1.8; color:var(--text-main);">${stock.chart_analogy_commentary || '---'}</div>
        </div>
      </div>

      <div class="full-width-block">
        <div class="theme-block-title-bar">🔗 関連ニュース ＆ 競合他社・マクロ相関（絶対参照）</div>
        <div class="flash-box" style="background-color:#ffffff; border: 2.5px solid var(--border-color); border-radius:12px; margin-bottom:0;">
          <div style="font-size:14px; line-height:1.8; color:var(--text-main);">${stock.news_correlation_commentary || '---'}</div>
        </div>
      </div>

      <!-- 外部リンク -->
      <div class="source-links-card">
        <div class="source-links-title">🔍 外部参考ソースリンク</div>
        <ul class="source-links-list">
          <li><a href="https://finance.yahoo.co.jp/quote/${stock.code}.T" target="_blank" rel="noopener">Yahoo!ファイナンス (${stock.code}.T)</a></li>
          <li><a href="https://kabutan.jp/stock/?code=${stock.code}" target="_blank" rel="noopener">株探 (kabutan)</a></li>
          <li><a href="https://minkabu.jp/stock/${stock.code}" target="_blank" rel="noopener">みんかぶ (${stock.code})</a></li>
        </ul>
      </div>

      <!-- ポートフォリオP&L簡易表示 -->
      <div class="stock-pnl-bar" style="margin-top:16px; border-top:1.5px dashed var(--border-light); padding-top:12px;">
        <div class="pnl-label-row">
          <span>${quantity}株 × ¥${fmt(avgCost)}</span>
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
    renderCharts(data.stocks); // ポテンシャル横棒 ＆ 信用散布図を描画
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
