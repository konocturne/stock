import re

with open("dashboard/app.js", "r") as f:
    app_js = f.read()

# 1. Update Chart IDs
app_js = app_js.replace("document.getElementById('portfolioChart')", "document.getElementById('chart-portfolio-allocation')")
app_js = app_js.replace("document.getElementById('valuationPlot')", "document.getElementById('chart-valuation-plot')")

# 2. Update renderAIReport to map to the new prototype structure instead of tabs
new_render_ai = """
function renderAIReport(report, today) {
  if (!report) return;

  const titleEl = document.getElementById('display-header-title');
  if (titleEl && report.title) titleEl.textContent = `🤖 ${report.title}`;

  const banner = document.getElementById('display-alert-banner');
  if (banner && report.alerts && report.alerts.length) {
    banner.style.display = 'block';
    banner.innerHTML = report.alerts.map(a => `<div class="alert-item">${a}</div>`).join('');
  } else if (banner) {
    banner.style.display = 'none';
  }

  const flashText = document.getElementById('display-flash-text');
  if (flashText && report.market_summary) {
    flashText.innerHTML = report.market_summary;
  }

  const strategyShort = document.getElementById('display-strategy-short');
  if (strategyShort && report.strategy_short) {
    strategyShort.innerHTML = `
      <div class="strategy-subblock-title">■ 寄り付きトレード・アクションプラン</div>
      <div class="strategy-subblock-text">${report.strategy_short}</div>
    `;
  }

  const strategyLong = document.getElementById('display-strategy-long');
  if (strategyLong && report.strategy_mid) {
    strategyLong.innerHTML = `
      <div class="strategy-subblock-title">■ 中長期アロケーション再構築方針</div>
      <div class="strategy-subblock-text">${report.strategy_mid}</div>
    `;
    strategyLong.classList.remove('night-only'); // Show it dynamically
  }
}
"""

# Replace the old renderAIReport
app_js = re.sub(r"function renderAIReport\(report, today\) \{.*?\n\}\n\nfunction block", new_render_ai + "\nfunction block", app_js, flags=re.DOTALL)

# Remove setTabContent completely or just leave it unused.
# Let's add switchTiming globally
switch_timing_script = """
window.switchTiming = function(timing) {
  document.querySelectorAll('.timing-btn').forEach(btn => btn.classList.remove('active'));
  event.target.classList.add('active');

  const headerTitle = document.getElementById('display-header-title');
  const headerTime = document.getElementById('display-header-time');
  const alertBanner = document.getElementById('display-alert-banner');
  const flashText = document.getElementById('display-flash-text');
  const strategyShort = document.getElementById('display-strategy-short');
  const strategyLong = document.getElementById('display-strategy-long');

  if (timing === '朝') {
    headerTitle.textContent = "ポートフォリオ投資戦略・日報 (朝版)";
    headerTime.textContent = "本日の寄り付き前シグナル ➔ JST 08:30配信";
    alertBanner.style.display = 'block';
    alertBanner.innerHTML = "⚠️ <strong>朝のアラート:</strong> トヨタ[7203]が52週安値（2,780円）に接近しています。本日の寄り付きから下限防衛の取引判断を準備してください。";
    flashText.innerHTML = "前日の米国市場で半導体SOX指数が+1.8%反発したため、本日の日経平均は上昇して始まる見込みです。しかし為替が1ドル141円台まで急激に円高方向に進行中。これにより、当PFの66.8%を占めるトヨタには強烈な為替下押し圧力が予想されます。<br>寄り付き直後の為替とトヨタの下限ラインの挙動に最大の注意を払ってください。";
    strategyShort.innerHTML = `<div class="strategy-subblock-title">■ 寄り付きトレード・アクションプラン (朝)</div>
      <div class="strategy-subblock-text">
        <ul class="bullet-list">
          <li><span class="highlight-marker-yellow">トヨタ：2,780円の安値サポートを割り込む場合、半分をロスカット。</span></li>
          <li>ソニーG：SOX指数反発に伴い寄り付きから上昇予想。13,500円に利益保護用の逆指値を再設定。</li>
        </ul>
      </div>`;
    if(strategyLong) strategyLong.style.display = 'none';

  } else if (timing === '昼') {
    headerTitle.textContent = "ポートフォリオ投資戦略・日報 (昼版)";
    headerTime.textContent = "前場総括と後場に向けたトレード指示 ➔ JST 12:00配信";
    alertBanner.style.display = 'block';
    alertBanner.innerHTML = "⚠️ <strong>昼のアラート:</strong> 前場終値でトヨタが2,792円まで急落。損切りライン（2,780円）まで残り12円です。";
    flashText.innerHTML = "前場の日経平均は前日比マイナス圏で引けました。為替が一時140.90円まで円高が進んだことが原因です。トヨタは売り込まれたものの、安値2,790円で辛うじて下げ渋っています。ソニーGは為替の影響を受けにくく、前場の終値は前日比+1.5%と好調を維持しています。後場のトヨタのサポート割れにのみ警戒してください。";
    strategyShort.innerHTML = `<div class="strategy-subblock-title">■ 後場に向けたトレード指示 (昼)</div>
      <div class="strategy-subblock-text">
        <ul class="bullet-list">
          <li><span class="highlight-marker-red">トヨタ：後場も下値警戒。2,780円に到達した時点で、成行での一部損切り予約注文を実行。</span></li>
          <li>ソニーG：後場も静観。13,500円の逆指値に変更なし。</li>
        </ul>
      </div>`;
    if(strategyLong) strategyLong.style.display = 'none';

  } else if (timing === '夜') {
    headerTitle.textContent = "ポートフォリオ投資戦略・日報 (夜版)";
    headerTime.textContent = "本日大引けの総括と中長期アロケーション ➔ JST 19:00配信";
    alertBanner.style.display = 'none';
    flashText.innerHTML = "大引けの日経平均は前日比+0.5%で終了しました。午後にかけて急激な円高が一服し、トヨタも2,810円まで買い戻されて安値サポートライン（2,780円）を守りきりました。ソニーGは+2.39%で引け、今日のポートフォリオ評価額は前日比+1.07%となりました。トヨタの下限維持により、短期的なパニック売りは回避されましたが、ポートフォリオのリスク偏重状態は継続しています。";
    strategyShort.innerHTML = "";
    if(strategyLong) {
        strategyLong.style.display = 'block';
        strategyLong.innerHTML = `<div class="strategy-subblock-title">■ 中長期アロケーション再構築方針 (夜)</div>
          <div class="strategy-subblock-text">
            <ol class="numbered-list">
              <li><strong>セクター集中リスクの排除</strong>：トヨタへの過度な資金集中（66.8%）を段階的に縮小し、最大でも単一セクター of 40%以下にします。</li>
              <li><strong>低ベータディフェンシブの組み込み</strong>：売却資金をベータ値の低い「大手都市銀行」または「大手通信インフラ株（KDDI等）」にシフトし、ポートフォリオ全体の平均ベータ値を1.00以下に引き下げます。</li>
            </ol>
          </div>`;
    }
  }
};
"""

app_js += "\n" + switch_timing_script

with open("dashboard/app.js", "w") as f:
    f.write(app_js)

print("Updated app.js")
