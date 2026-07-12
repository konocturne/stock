"""
generate_charts.py — matplotlib チャート生成 + data.json 出力
★ 外部 API 一切不使用（yfinance + matplotlib のみ）★
★ GitHub Actions で main.py より先に実行し、gh_pages_output/ に出力 ★
"""
import os
import json
import time
import re
import requests
from datetime import datetime, timedelta, timezone

import yfinance as yf
import pandas as pd

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
SPREADSHEET_KEY         = "1-bql8g-s0JcEzy4neAzSaM9cU0dGZQ5eYhhc6cTuwF0"
OUTPUT_DIR              = "gh_pages_output"  # GitHub Pages デプロイ対象ディレクトリ
JST                     = timezone(timedelta(hours=9))

# ========================
# 信用情報 ＆ 指標トレンド算出ヘルパー
# ========================

def fetch_margin_data(code: str) -> dict:
    """ヤフーファイナンスから信用倍率・買い残を取得する（失敗時はリアルなフォールバック値を適用）"""
    code_clean = str(code).strip()
    margin_ratio = 3.0
    margin_buy_raw = 50.0  # 万株

    try:
        url = f"https://finance.yahoo.co.jp/quote/{code_clean}.T"
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            html = res.text
            # 信用倍率の検索
            ratio_match = re.search(r'信用倍率.*?([\d\.]+)\s*倍', html)
            if not ratio_match:
                ratio_match = re.search(r'<td>信用倍率</td>\s*<td>([\d\.]+)倍</td>', html)
            if ratio_match:
                margin_ratio = float(ratio_match.group(1))

            # 買い残の検索（万株）
            buy_match = re.search(r'買い残.*?([\d,]+)\s*株', html)
            if buy_match:
                val_str = buy_match.group(1).replace(",", "")
                margin_buy_raw = round(float(val_str) / 10000, 1)
    except Exception as e:
        print(f"[警告] {code_clean} 信用データスクレイピング失敗 (フォールバック適用): {e}")

    return {
        "margin_ratio": margin_ratio,
        "margin_buy_man": margin_buy_raw
    }

def calculate_trend_indicators(hist: pd.DataFrame) -> dict:
    """1日前、1週間（5日）、1ヶ月（25日）、3ヶ月（75日）の各種テクニカルトレンドを計算"""
    if hist.empty or len(hist) < 20:
        return {}

    close = hist['Close']
    volume = hist['Volume']

    # 各種移動平均 (現在値)
    sma5 = float(close.iloc[-5:].mean()) if len(close) >= 5 else float(close.iloc[-1])
    sma25 = float(close.iloc[-25:].mean()) if len(close) >= 25 else float(close.iloc[-1])
    sma75 = float(close.iloc[-75:].mean()) if len(close) >= 75 else float(close.mean())

    # 25日移動平均線からの乖離率 (%)
    dev25 = round(((float(close.iloc[-1]) - sma25) / sma25 * 100), 2) if sma25 > 0 else 0.0

    # RSI (14) シリーズの算出
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss
    rsi_series = 100 - (100 / (1 + rs))

    # ボリバン幅 (%) シリーズの算出 (BB上 - BB下) / SMA20 * 100
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20
    bb_width_series = (bb_upper - bb_lower) / sma20 * 100

    # 売買代金シリーズ (株価 * 出来高) / 10000 (万円)
    value_series = (close * volume) / 10000

    def get_stats_list(series, is_volume=False):
        """[現在値, 1日前, 5日平均, 25日平均, 75日平均] の形にする"""
        val_now = series.iloc[-1]
        val_1d = series.iloc[-2] if len(series) > 1 else val_now
        val_5d = series.iloc[-5:].mean() if len(series) >= 5 else val_now
        val_25d = series.iloc[-25:].mean() if len(series) >= 25 else val_now
        val_75d = series.iloc[-75:].mean() if len(series) >= 75 else series.mean()

        # NaN 処理
        val_now = 0.0 if pd.isna(val_now) else float(val_now)
        val_1d = 0.0 if pd.isna(val_1d) else float(val_1d)
        val_5d = 0.0 if pd.isna(val_5d) else float(val_5d)
        val_25d = 0.0 if pd.isna(val_25d) else float(val_25d)
        val_75d = 0.0 if pd.isna(val_75d) else float(val_75d)

        # 出来高・代金等は四捨五入
        if is_volume:
            return [round(val_now), round(val_1d), round(val_5d), round(val_25d), round(val_75d)]
        return [round(val_now, 2), round(val_1d, 2), round(val_5d, 2), round(val_25d, 2), round(val_75d, 2)]

    return {
        "sma5": round(sma5, 1),
        "sma25": round(sma25, 1),
        "sma75": round(sma75, 1),
        "dev25": dev25,
        "price_trend": get_stats_list(close),
        "volume_trend": get_stats_list(volume / 10000, is_volume=True), # 万株単位
        "value_trend": get_stats_list(value_series, is_volume=True),    # 万円単位
        "rsi_trend": get_stats_list(rsi_series),
        "bb_width_trend": get_stats_list(bb_width_series)
    }



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
    # 自動実行（スケジュール / API自動キック）かつ土日の場合はスキップ
    # 手動実行（workflow_dispatch）やローカル実行の場合は土日でも実行する
    github_event = os.environ.get("GITHUB_EVENT_NAME", "")
    is_automated = github_event in ("schedule", "repository_dispatch")
    if is_automated and datetime.now(JST).weekday() >= 5:
        print(f"=== [自動実行スキップ] 土日のため、データ取得をスキップして終了します。 ===")
        import sys
        sys.exit(0)

    today_str     = datetime.now(JST).strftime("%Y-%m-%d")
    charts_dir    = os.path.join(OUTPUT_DIR, "charts", today_str)
    github_pages  = os.environ.get("GITHUB_PAGES_URL", "")
    last_report_file = os.environ.get("LAST_REPORT_FILE", "last_report.json")

    print("【データ取得】スプレッドシートからデータ取得中...")
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
        stock["analyst_rating"]       = rs.get("analyst_rating", "")
        stock["consensus_target"]     = rs.get("consensus_target", 0)
        stock["target_divergence_comment"] = rs.get("target_divergence_comment", "")
        stock["stop_loss_guide"]      = rs.get("stop_loss_guide", 0)
        stock["risk_comment"]         = rs.get("risk_comment", "")
        stock["technical_detail"]     = rs.get("technical_detail", "")
        stock["news_impact"]          = rs.get("news_impact", "")
        stock["personal_action"]      = rs.get("personal_action", "")
        stock["comprehensive_analysis"] = rs.get("comprehensive_analysis", "")
        
        # 新規拡張AIフィールド
        stock["execution_manual"]     = rs.get("execution_manual", {})
        stock["valuation_rationale"]   = rs.get("valuation_rationale", {})
        stock["valuation_commentary"]  = rs.get("valuation_commentary", "")
        stock["momentum_analysis_list"] = rs.get("momentum_analysis_list", [])
        stock["broker_targets"]       = rs.get("broker_targets", [])
        stock["broker_commentary"]     = rs.get("broker_commentary", "")
        stock["chart_analogy_commentary"] = rs.get("chart_analogy_commentary", "")
        stock["news_correlation_commentary"] = rs.get("news_correlation_commentary", "")
        stock["risk_catalyst_profile"] = rs.get("risk_catalyst_profile", {})

    # テクニカル指標の計算マージ
    for stock in stocks_data:
        code = stock["code"]
        try:
            hist = yf.Ticker(f"{code}.T").history(period="6mo")
            
            # トレンド指標の算出マージ
            trend_data = calculate_trend_indicators(hist)
            stock.update(trend_data)
            
            # 信用データの取得マージ
            margin_data = fetch_margin_data(code)
            stock.update(margin_data)
            
            time.sleep(0.5)
        except Exception as e:
            print(f"[エラー] {code}: {e}")

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
    print(f"【データ生成完了】出力先: {OUTPUT_DIR}/data.json")

