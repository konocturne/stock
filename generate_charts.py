"""
generate_charts.py — matplotlib チャート生成 + data.json 出力
★ 外部 API 一切不使用（yfinance + matplotlib のみ）★
★ GitHub Actions で main.py より先に実行し、gh_pages_output/ に出力 ★
"""
import os
import json
import time
from datetime import datetime, timedelta, timezone

import yfinance as yf
import pandas as pd

import matplotlib
matplotlib.use('Agg')  # GUI なし（サーバー実行用）
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.font_manager as fm

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
SPREADSHEET_KEY         = "1-bql8g-s0JcEzy4neAzSaM9cU0dGZQ5eYhhc6cTuwF0"
OUTPUT_DIR              = "gh_pages_output"  # GitHub Pages デプロイ対象ディレクトリ
JST                     = timezone(timedelta(hours=9))

# ========================
# matplotlib ダークテーマ設定
# ========================

# 日本語フォントを自動検出（GitHub Actions で fonts-noto-cjk 導入後に機能）
_jp_candidates = [f.fname for f in fm.fontManager.ttflist
                  if any(k in f.name for k in ['Noto Sans CJK', 'Noto Sans JP'])]
if _jp_candidates:
    plt.rcParams['font.family'] = fm.FontProperties(fname=_jp_candidates[0]).get_name()

plt.rcParams.update({
    'axes.unicode_minus': False,
    'figure.facecolor':   '#0f172a',
    'axes.facecolor':     '#1e293b',
    'axes.edgecolor':     '#334155',
    'axes.labelcolor':    '#94a3b8',
    'text.color':         '#f1f5f9',
    'xtick.color':        '#94a3b8',
    'ytick.color':        '#94a3b8',
    'grid.color':         '#334155',
    'grid.alpha':         0.5,
    'grid.linewidth':     0.5,
})

# ========================
# 認証
# ========================

def _get_creds_dict():
    if GOOGLE_CREDENTIALS_JSON:
        try:
            return json.loads(GOOGLE_CREDENTIALS_JSON)
        except Exception:
            pass
    json_path = "gen-lang-client-0001329181-b47d41c19dcb.json"
    if os.path.exists(json_path):
        with open(json_path, "r") as f:
            return json.load(f)
    raise ValueError("Google credentials not set")

def get_spreadsheet():
    creds = Credentials.from_service_account_info(
        _get_creds_dict(),
        scopes=["https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"]
    )
    return gspread.authorize(creds).open_by_key(SPREADSHEET_KEY)

# ========================
# 個別銘柄チャート生成
# SMA50 / SMA20 / ボリンジャーバンド / 出来高
# ========================

def generate_stock_chart(code: str, name: str, hist: pd.DataFrame, output_path: str) -> bool:
    if hist.empty or len(hist) < 20:
        return False

    close = hist['Close']
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20
    sma50    = close.rolling(50).mean() if len(close) >= 50 else None

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(10, 6),
        gridspec_kw={'height_ratios': [3, 1], 'hspace': 0.04},
        facecolor='#0f172a',
    )

    dates = hist.index

    # 価格チャート
    ax1.plot(dates, close,    color='#38bdf8', linewidth=1.5, label='Close', zorder=3)
    if sma50 is not None:
        ax1.plot(dates, sma50, color='#f59e0b', linewidth=1.0, linestyle='--', alpha=0.8, label='SMA50', zorder=2)
    ax1.plot(dates, sma20,    color='#a78bfa', linewidth=0.8, linestyle=':', alpha=0.7, label='SMA20', zorder=2)
    ax1.fill_between(dates, bb_upper, bb_lower, alpha=0.08, color='#a78bfa')
    ax1.plot(dates, bb_upper, color='#a78bfa', linewidth=0.5, alpha=0.4)
    ax1.plot(dates, bb_lower, color='#a78bfa', linewidth=0.5, alpha=0.4)

    ax1.set_title(f'[{code}] {name}', color='#f1f5f9', fontsize=11, fontweight='bold', pad=8, loc='left')
    ax1.legend(loc='upper left', facecolor='#1e293b', edgecolor='#334155',
               labelcolor='#94a3b8', fontsize=8, framealpha=0.8)
    ax1.grid(True)
    ax1.set_xticklabels([])
    ax1.yaxis.set_label_position('right')
    ax1.yaxis.tick_right()

    # 出来高チャート（陽線/陰線で色分け）
    vol_colors = [
        '#22c55e' if float(hist['Close'].iloc[i]) >= float(hist['Open'].iloc[i]) else '#ef4444'
        for i in range(len(hist))
    ]
    ax2.bar(dates, hist['Volume'], color=vol_colors, alpha=0.7, width=1.0)
    ax2.set_ylabel('Vol', color='#94a3b8', fontsize=8)
    ax2.grid(True, axis='y')
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
    ax2.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0, interval=2))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=30, ha='right', fontsize=7)
    ax2.yaxis.set_label_position('right')
    ax2.yaxis.tick_right()
    ax2.tick_params(axis='y', labelsize=7)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=100, bbox_inches='tight', facecolor='#0f172a', edgecolor='none')
    plt.close(fig)
    return True

# ========================
# ポートフォリオ概要チャート（含み損益バー）
# ========================

def generate_portfolio_overview(stocks_data: list, output_path: str) -> bool:
    valid = [(s['code'], s['name'][:5], s['pnl_pct']) for s in stocks_data if s.get('pnl_pct') is not None]
    if not valid:
        return False

    fig, ax = plt.subplots(figsize=(max(8, len(valid) * 1.2), 4), facecolor='#0f172a')

    labels = [f"{code}\n{name}" for code, name, _ in valid]
    values = [pct for _, _, pct in valid]
    colors = ['#22c55e' if v >= 0 else '#ef4444' for v in values]

    bars = ax.bar(labels, values, color=colors, alpha=0.85, width=0.6, zorder=2)
    ax.axhline(y=0, color='#475569', linewidth=1.0, zorder=1)

    for bar, val in zip(bars, values):
        sign  = "+" if val >= 0 else ""
        y_off = 0.3 if val >= 0 else -0.3
        va    = 'bottom' if val >= 0 else 'top'
        ax.text(bar.get_x() + bar.get_width() / 2., bar.get_height() + y_off,
                f'{sign}{val:.1f}%', ha='center', va=va,
                color='#f1f5f9', fontsize=9, fontweight='bold')

    ax.set_title('Portfolio P&L (%)', color='#f1f5f9', fontsize=13, fontweight='bold', pad=10)
    ax.grid(True, axis='y')
    ax.set_ylabel('%', color='#94a3b8', fontsize=9)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=100, bbox_inches='tight', facecolor='#0f172a', edgecolor='none')
    plt.close(fig)
    return True

# ========================
# スプレッドシートデータをダッシュボード用 dict に整形
# ========================

def _to_float(val):
    try:
        return float(str(val).replace(",", "").replace("円", "").replace("---", "0").replace("%", ""))
    except Exception:
        return 0.0

def build_stocks_data(records: list, today_str: str) -> tuple:
    """(stocks_list, portfolio_summary) を返す"""
    stocks      = []
    total_cost  = 0.0
    total_eval  = 0.0

    for row in records[1:]:
        row  = row + [""] * (22 - len(row))
        code = row[0].strip()
        if not code:
            continue
        try:
            current_price = _to_float(row[4])
            quantity      = _to_float(row[2])
            avg_cost      = _to_float(row[3])

            cost_total = avg_cost * quantity
            eval_total = current_price * quantity
            pnl        = eval_total - cost_total
            pnl_pct    = round(pnl / cost_total * 100, 2) if cost_total > 0 else None

            total_cost += cost_total
            total_eval += eval_total

            stocks.append({
                "code":           code,
                "name":           row[1],
                "quantity":       int(quantity),
                "avg_cost":       avg_cost,
                "current_price":  current_price,
                "change_pct_str": row[5],
                "change_str":     row[6],
                "per":            row[16],
                "pbr":            row[17],
                "div_yield":      row[18],
                "sector":         row[21],
                "pnl":            round(pnl, 0),
                "pnl_pct":        pnl_pct,
                "eval_total":     round(eval_total, 0),
                "cost_total":     round(cost_total, 0),
                "chart_url":      f"charts/{today_str}/{code}.png",
            })
        except Exception as e:
            print(f"[警告] {code} データ整形エラー: {e}")

    total_pnl     = total_eval - total_cost
    total_pnl_pct = round(total_pnl / total_cost * 100, 2) if total_cost > 0 else 0.0

    portfolio = {
        "total_cost":    round(total_cost, 0),
        "total_eval":    round(total_eval, 0),
        "total_pnl":     round(total_pnl, 0),
        "total_pnl_pct": total_pnl_pct,
    }
    return stocks, portfolio

def get_history_data(spreadsheet) -> list:
    """「履歴」シートから最新 10 件を取得"""
    try:
        history_sheet = spreadsheet.worksheet("履歴")
        values        = history_sheet.get_all_values()
        if len(values) < 2:
            return []
        recent = values[1:][-10:][::-1]  # 最新 10 件を降順
        return [
            {
                "date":      r[0] if len(r) > 0 else "",
                "timing":    r[1] if len(r) > 1 else "",
                "ts":        r[2] if len(r) > 2 else "",
                "alerts":    r[3] if len(r) > 3 else "",
                "weather":   r[4] if len(r) > 4 else "",
                "benchmark": r[5] if len(r) > 5 else "",
                "strategy":  r[6] if len(r) > 6 else "",
            }
            for r in recent
        ]
    except Exception:
        return []

# ========================
# メイン処理
# ========================

if __name__ == "__main__":
    today_str     = datetime.now(JST).strftime("%Y-%m-%d")
    charts_dir    = os.path.join(OUTPUT_DIR, "charts", today_str)
    github_pages  = os.environ.get("GITHUB_PAGES_URL", "")
    last_report_file = os.environ.get("LAST_REPORT_FILE", "last_report.json")

    print("【チャート生成】スプレッドシートからデータ取得中...")
    spreadsheet = get_spreadsheet()
    sheet       = spreadsheet.worksheet("保有銘柄")
    records     = sheet.get_all_values()

    # データ整形
    stocks_data, portfolio = build_stocks_data(records, today_str)
    history_data           = get_history_data(spreadsheet)

    # last_report.json の読み込み（main.py が生成した Gemini レポート）
    ai_report = {}
    if os.path.exists(last_report_file):
        try:
            with open(last_report_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
                ai_report = saved.get("report", {})
            print(f"[AIレポート] {last_report_file} の読み込み完了")
        except Exception as e:
            print(f"[警告] {last_report_file} の読み込み失敗: {e}")

    # AIレポートの銘柄データを stocks_data にマージ
    report_stocks_map = {
        s.get("code", ""): s
        for s in ai_report.get("stocks", [])
    }
    for stock in stocks_data:
        rs = report_stocks_map.get(stock["code"], {})
        stock["sentiment"]            = rs.get("sentiment", "")
        stock["sentiment_reason"]     = rs.get("sentiment_reason", "")
        stock["recommendation"]       = rs.get("recommendation", "")
        stock["recommendation_reason"]= rs.get("recommendation_reason", "")
        stock["target_price"]         = rs.get("target_price", 0)
        stock["target_basis"]         = rs.get("target_basis", "")
        stock["stop_loss"]            = rs.get("stop_loss", 0)
        stock["risk_factors"]         = rs.get("risk_factors", "")
        stock["technical_detail"]     = rs.get("technical_detail", "")
        stock["news_impact"]          = rs.get("news_impact", "")

    # 各銘柄チャート生成
    for stock in stocks_data:
        code = stock["code"]
        name = stock["name"]
        try:
            hist        = yf.Ticker(f"{code}.T").history(period="6mo")
            output_path = os.path.join(charts_dir, f"{code}.png")
            ok          = generate_stock_chart(code, name, hist, output_path)
            print(f"[{'生成完了' if ok else 'スキップ'}] {code}: {name}")
            time.sleep(0.5)
        except Exception as e:
            print(f"[エラー] {code}: {e}")

    # ポートフォリオ概要チャート
    overview_path = os.path.join(charts_dir, "portfolio_overview.png")
    if generate_portfolio_overview(stocks_data, overview_path):
        print("[生成完了] portfolio_overview.png")

    # ダッシュボード用 data.json 生成（AIレポートを包括）
    data_json = {
        "updated_at":       datetime.now(JST).isoformat(),
        "today":            today_str,
        "github_pages_url": github_pages,
        "portfolio":        portfolio,
        "stocks":           stocks_data,
        "history":          history_data,
        # Gemini AIレポート全体（ダッシュボード用）
        "ai_report": {
            "title":              ai_report.get("title", ""),
            "alerts":             ai_report.get("alerts", []),
            "weather":            ai_report.get("weather", ""),
            "benchmark":          ai_report.get("benchmark", ""),
            "market_summary":     ai_report.get("market_summary", ""),
            "tomorrow_outlook":   ai_report.get("tomorrow_outlook", ""),
            "analysis_market":    ai_report.get("analysis_market", ""),
            "analysis_technical": ai_report.get("analysis_technical", ""),
            "analysis_portfolio": ai_report.get("analysis_portfolio", ""),
            "strategy_short":     ai_report.get("strategy_short", ""),
            "strategy_mid":       ai_report.get("strategy_mid", ""),
        } if ai_report else None,
    }
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    data_path = os.path.join(OUTPUT_DIR, "data.json")
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data_json, f, ensure_ascii=False, indent=2)

    print(f"[生成完了] data.json ({len(stocks_data)}銘柄 / AIレポート: {'OK' if ai_report else '未取得'})")  
    print(f"【チャート生成完了】出力先: {charts_dir}/")

