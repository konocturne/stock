import os
import json
import time
import re
from datetime import datetime, timedelta, timezone
import requests
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
from dotenv import load_dotenv

# .envファイルから環境変数を読み込む (ローカル実行用)
load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN")
LINE_USER_ID = os.environ.get("LINE_USER_ID")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
SPREADSHEET_KEY = "1-bql8g-s0JcEzy4neAzSaM9cU0dGZQ5eYhhc6cTuwF0"

def get_current_timing():
    # テストシミュレーション用の環境変数チェック
    test_timing = os.environ.get("TEST_TIMING")
    if test_timing in ["朝", "昼", "夜"]:
        return test_timing
        
    # 日本時間 (JST) を取得して時間帯を判定
    jst = timezone(timedelta(hours=9))
    now_jst = datetime.now(timezone.utc).astimezone(jst)
    hour = now_jst.hour
    
    if 5 <= hour < 11:
        return "朝"
    elif 11 <= hour < 16:
        return "昼"
    else:
        return "夜"

def get_market_indicators():
    print("【システム】米国・外国市場指標を取得中...")
    indicators = {
        "S&P 500": "^GSPC",
        "NASDAQ": "^IXIC",
        "SOX指数": "^SOX",
        "日経先物": "NK=F"
    }
    result = {}
    for name, symbol in indicators.items():
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            price = info.get("regularMarketPrice") or info.get("currentPrice")
            prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
            
            if not price and prev_close:
                hist = ticker.history(period="1d")
                if not hist.empty:
                    price = hist['Close'].iloc[-1]
            
            if price and prev_close:
                change = price - prev_close
                change_pct = (change / prev_close) * 100
                sign = "+" if change > 0 else ""
                result[name] = f"{price:,.2f} ({sign}{change_pct:.2f}%)"
            elif price:
                result[name] = f"{price:,.2f}"
            else:
                result[name] = "取得失敗"
        except Exception as e:
            result[name] = f"エラー: {e}"
    return result

def get_pts_price(code):
    print(f"【システム】銘柄 {code} の夜間PTS情報を取得中...")
    url = f"https://kabutan.jp/stock/?code={code}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            html = res.text
            m = re.search(r'class="kabuka1">PTS</div>\s*<div class="kabuka2">([^<]+)</div>', html)
            if m:
                return m.group(1).strip()
    except Exception as e:
        print(f"【警告】PTS価格の取得中にエラーが発生しました ({code}): {e}")
    return None

def initialize_headers(sheet):
    headers = [
        "銘柄コード", "銘柄名", "保有数", "平均取得単価",
        "現在値", "前日比(%)", "前日比(円)", "出来高", "売買代金(万円)",
        "前日終値", "始値", "高値", "安値", "52週高値", "52週安値",
        "時価総額(億円)", "PER", "PBR", "配当利回り(%)", "1株配当(円)", "ROE(%)", "業種"
    ]
    try:
        current_headers = sheet.row_values(1)
        # ヘッダーが不足または不一致の場合のみ更新
        if len(current_headers) < len(headers) or current_headers[:len(headers)] != headers:
            sheet.update(range_name="A1:V1", values=[headers])
            print("【初期化】スプレッドシートのヘッダーをA列〜V列（22項目）に更新しました。")
    except Exception as e:
        print(f"【警告】ヘッダー初期化中にエラーが発生しました: {e}")

def get_sheet():
    creds_dict = None
    if GOOGLE_CREDENTIALS_JSON:
        try:
            creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        except json.JSONDecodeError:
            pass
            
    if not creds_dict:
        # ローカルのJSONファイルから読み込むフォールバック
        json_path = "gen-lang-client-0001329181-b47d41c19dcb.json"
        if os.path.exists(json_path):
            with open(json_path, "r") as f:
                creds_dict = json.load(f)
        else:
            raise ValueError("Google credentials are not set (missing env var or local JSON file)")
            
    creds = Credentials.from_service_account_info(

        creds_dict,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_KEY).worksheet("保有銘柄")
    initialize_headers(sheet)
    return sheet

def update_stock_data(sheet):
    print("【1】yfinanceからのデータ取得を開始します")
    records = sheet.get_all_values()
    
    for i, row in enumerate(records[1:], start=2):
        if not row or len(row) < 1:
            continue
        code = row[0].strip()
        if not code:
            continue
            
        ticker_symbol = f"{code}.T"
        ticker = yf.Ticker(ticker_symbol)
        
        # 安全のためにrowの要素数を最低4つ（A〜D列分）に拡張
        row = row + [""] * (4 - len(row))
        
        try:
            info = ticker.info
            name = info.get("longName") or info.get("shortName") or info.get("symbol") or ""
            current_price = info.get("currentPrice") or info.get("regularMarketPrice")
            prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
            
            if not current_price and prev_close:
                hist = ticker.history(period="1d")
                if not hist.empty:
                    current_price = hist['Close'].iloc[-1]
                    open_price = hist['Open'].iloc[-1]
                    day_high = hist['High'].iloc[-1]
                    day_low = hist['Low'].iloc[-1]
                    volume = hist['Volume'].iloc[-1]
            else:
                open_price = info.get("open") or info.get("regularMarketOpen")
                day_high = info.get("dayHigh") or info.get("regularMarketDayHigh")
                day_low = info.get("dayLow") or info.get("regularMarketDayLow")
                volume = info.get("volume") or info.get("regularMarketVolume")

            raw_change = current_price - prev_close if current_price and prev_close else 0
            raw_change_pct = (raw_change / prev_close) * 100 if prev_close else 0
            
            change_str = f"+{raw_change:.1f}円" if raw_change > 0 else f"{raw_change:.1f}円"
            change_pct_str = f"+{raw_change_pct:.2f}%" if raw_change_pct > 0 else f"{raw_change_pct:.2f}%"
            
            trading_value = round((current_price * volume) / 10000) if current_price and volume else ""
            market_cap_raw = info.get("marketCap", 0)
            market_cap_oku = round(market_cap_raw / 100000000) if market_cap_raw else ""
            
            per = info.get("forwardPE") or info.get("trailingPE")
            per_str = f"{per:.2f}倍" if per else "---"
            
            pbr = info.get("priceToBook")
            pbr_str = f"{pbr:.2f}倍" if pbr else "---"

            div_yield = info.get("dividendYield")
            div_yield_str = f"{div_yield:.2f}%" if div_yield else "---"
            
            div_rate = info.get("dividendRate")
            div_rate_str = f"{div_rate}円" if div_rate else "---"
            
            roe = info.get("returnOnEquity")
            roe_str = f"{roe * 100:.2f}%" if roe else "---"
            
            sector = info.get("sector") or "---"
            
            # B列からV列までの一括更新データを作成
            update_row = [
                name,                          # B: 銘柄名
                row[2],                        # C: 保有数
                row[3],                        # D: 平均取得単価
                current_price or "",           # E: 現在値
                change_pct_str,                # F: 前日比(%)
                change_str,                    # G: 前日比(円)
                volume or "",                  # H: 出来高
                trading_value,                 # I: 売買代金(万円)
                prev_close or "",              # J: 前日終値
                open_price or "",              # K: 始値
                day_high or "",                # L: 高値
                day_low or "",                 # M: 安値
                info.get("fiftyTwoWeekHigh") or "", # N: 52週高値
                info.get("fiftyTwoWeekLow") or "",  # O: 52週安値
                market_cap_oku,                # P: 時価総額(億円)
                per_str,                       # Q: PER
                pbr_str,                       # R: PBR
                div_yield_str,                 # S: 配当利回り(%)
                div_rate_str,                  # T: 1株配当(円)
                roe_str,                       # U: ROE(%)
                sector                         # V: 業種
            ]
            
            sheet.update(range_name=f"B{i}:V{i}", values=[update_row])
            print(f"[取得完了] {code}: {name} / 現在値 {current_price}円 / 利回り {div_yield_str} / ROE {roe_str}")
            time.sleep(1)
            
        except Exception as e:
            print(f"[yfinance例外エラー] {code}: {e}")

def generate_analysis_report(sheet, timing):
    records = sheet.get_all_values()
    if len(records) < 2:
        print("【警告】スプレッドシートにデータが登録されていません。")
        return None
        
    stocks_data = []
    
    # 2行目以降の全データをループ処理
    for i, row in enumerate(records[1:], start=2):
        if not row or len(row) < 1:
            continue
        code = row[0].strip()
        if not code:
            continue
            
        # 安全のために22列分パディング
        row = row + [""] * (22 - len(row))
        
        name = row[1]
        avg_price = row[3]
        cur_price = row[4]
        change_pct = row[5]
        change_yen = row[6]
        volume = row[7]
        trading_value = row[8]
        prev_close = row[9]
        open_price = row[10]
        day_high = row[11]
        day_low = row[12]
        week52_high = row[13]
        week52_low = row[14]
        market_cap = row[15]
        per = row[16]
        pbr = row[17]
        div_yield = row[18]
        div_rate = row[19]
        roe = row[20]
        sector = row[21]
        
        # 夜間PTS情報の取得（夜のレポートの場合のみ）
        pts_info = ""
        if timing == "夜":
            pts_price = get_pts_price(code)
            if pts_price:
                pts_diff_str = ""
                try:
                    p_val = float(re.sub(r'[^\d.]', '', pts_price))
                    c_val = float(re.sub(r'[^\d.]', '', cur_price))
                    diff = p_val - c_val
                    diff_pct = (diff / c_val) * 100
                    sign = "+" if diff > 0 else ""
                    pts_diff_str = f" (大引け比: {sign}{diff:.1f}円 / {sign}{diff_pct:.2f}%)"
                except Exception:
                    pass
                pts_info = f"夜間PTS価格: {pts_price}{pts_diff_str}"
            else:
                pts_info = "夜間PTS価格: 取引なしまたは取得失敗"

        stocks_data.append({
            "code": code,
            "name": name,
            "avg_price": avg_price,
            "cur_price": cur_price,
            "change_pct": change_pct,
            "change_yen": change_yen,
            "volume": volume,
            "trading_value": trading_value,
            "prev_close": prev_close,
            "open_price": open_price,
            "day_high": day_high,
            "day_low": day_low,
            "week52_high": week52_high,
            "week52_low": week52_low,
            "market_cap": market_cap,
            "per": per,
            "pbr": pbr,
            "div_yield": div_yield,
            "div_rate": div_rate,
            "roe": roe,
            "sector": sector,
            "pts_info": pts_info
        })

    # プロンプト用の保有銘柄テキストの構築
    stocks_prompt_text = ""
    for s in stocks_data:
        pts_part = f"\n【PTS状況】{s['pts_info']}" if s['pts_info'] else ""
        stocks_prompt_text += f"""
---
【銘柄】{s['code']} {s['name']} (業種: {s['sector']})
【平均取得単価】{s['avg_price']}円
【本日の値動き】現在値:{s['cur_price']}円 (前日比: {s['change_pct']} / {s['change_yen']})、始値:{s['open_price']}円、高値:{s['day_high']}円、安値:{s['day_low']}円、前日終値:{s['prev_close']}円
【相場エネルギー】出来高:{s['volume']}株、売買代金:{s['trading_value']}万円
【長期指標】52週高値:{s['week52_high']}円、52週安値:{s['week52_low']}円、時価総額:{s['market_cap']}億円
【指標】PER:{s['per']}、PBR:{s['pbr']}、配当利回り:{s['div_yield']}、1株配当:{s['div_rate']}、ROE:{s['roe']}{pts_part}
"""

    print(f"【2】Geminiへの一括リクエスト準備: {len(stocks_data)}銘柄 ({timing}の総合レポート)")

    timing_info = ""
    analysis_1_title = "1. 保有銘柄全体のテクニカル・需給評価"
    analysis_2_title = "2. ポートフォリオのトレンド分析"
    strategy_title = "3. ポートフォリオ全体のアクションプラン"

    if timing == "朝":
        market_data = get_market_indicators()
        market_str = "\n".join([f"・{k}: {v}" for k, v in market_data.items()])
        timing_info = f"""
【前日の海外市場・外部指標】
{market_str}
※特にSOX指数（半導体株価指数）の値動きや主要米国指数の動向を分析し、今日の日本市場開始前の地合いを評価してください。
また、今日の日本市場開始に伴い、保有銘柄それぞれの寄り付き・値動きがどうなりそうか予測してください。
"""
        analysis_1_title = "1. 海外市場の動向と本日の地合い予測"
        analysis_2_title = "2. 保有銘柄の本日寄り付き・値動き予測"
        strategy_title = "3. 本日のポートフォリオ戦略"

    elif timing == "昼":
        timing_info = f"""
※現在は【昼（前場終了後）】です。
前場（9:00〜11:30）の株価変動と出来高データを踏まえ、後場（12:30〜15:00）に向けての値動き予想や、保有銘柄全体へのアプローチ（押し目買い・ホールド・利益確定などの投資アクション）を総合的に示してください。
"""
        analysis_1_title = "1. 前場時点の保有銘柄評価"
        analysis_2_title = "2. 後場（12:30〜）の値動き・トレンド予想"
        strategy_title = "3. 後場のトレードアクションプラン"

    elif timing == "夜":
        timing_info = f"""
※現在は【夜（本日大引け後・夜間PTS稼働時間中）】です。
本日の大引け確定値、および各銘柄の夜間PTS取引データ（提示されている場合）を総合的に分析し、明日以降の株価動向、あるいは中長期的なポートフォリオの投資判断（買い増し、売却、静観など）を評価してください。
"""
        analysis_1_title = "1. 本日大引けと夜間PTSの動向分析"
        analysis_2_title = "2. 明日以降の保有銘柄トレンド予測"
        strategy_title = "3. 明日以降のポートフォリオ戦略"

    prompt = f"""以下の保有銘柄データから、ポートフォリオ全体をスキャンした{timing}の総合投資戦略レポートをJSON形式のみで作成してください。解説文やMarkdownのマークアップは一切除外してください。

【保有銘柄データ】
{stocks_prompt_text}
{timing_info}

【出力形式】次のJSONフォーマットのみを返してください。
{{"title": "{timing}の保有銘柄・総合戦略レポート", "statusColor": "#b91c1c", "stocks": [{{"name":"銘柄名1", "code":"コード1", "price":"現在値1(前日比1)", "info":"平均取得単価や配当など簡潔な補足"}}, {{"name":"銘柄名2", "code":"コード2", "price":"現在値2(前日比2)", "info":"補足"}}], "analysis_1_title": "{analysis_1_title}", "analysis_1_content": "分析内容", "analysis_2_title": "{analysis_2_title}", "analysis_2_content": "評価内容", "strategy_title": "{strategy_title}", "strategy_content": "戦略内容"}}"""

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
    response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
    return json.loads(response.text)

def send_to_line(data):
    if not data:
        return
    url = "https://api.line.me/v2/bot/message/push"
    color = data.get("statusColor", "#b91c1c")
    
    # 複数銘柄のリストテーブル用のFlex componentsを組み立てる
    flex_stocks = []
    
    # テーブルヘッダー
    flex_stocks.append({
        "type": "box", "layout": "horizontal", "contents": [
            { "type": "text", "text": "銘柄 (コード)", "size": "xs", "color": "#aaaaaa", "weight": "bold" },
            { "type": "text", "text": "現在値 (前日比)", "size": "xs", "color": "#aaaaaa", "align": "center", "weight": "bold" },
            { "type": "text", "text": "補足情報", "size": "xs", "color": "#aaaaaa", "align": "end", "weight": "bold" }
        ]
    })
    flex_stocks.append({ "type": "separator", "margin": "xs" })
    
    # 各銘柄のデータ行を追加
    for s in data.get("stocks", []):
        flex_stocks.append({
            "type": "box", "layout": "horizontal", "margin": "sm", "contents": [
                { "type": "text", "text": f"{s.get('name', '')} ({s.get('code', '')})", "size": "xs", "weight": "bold", "wrap": True },
                { "type": "text", "text": s.get("price", "-"), "size": "xs", "align": "center", "wrap": True },
                { "type": "text", "text": s.get("info", "-"), "size": "xs", "align": "end", "wrap": True, "color": "#555555" }
            ]
        })
        
    flex_message = {
        "to": LINE_USER_ID,
        "messages": [{
            "type": "flex",
            "altText": data.get("title", "総合レポート")[:40],
            "contents": {
                "type": "bubble",
                "header": {
                    "type": "box", "layout": "vertical", "backgroundColor": color,
                    "contents": [{ "type": "text", "text": data.get("title", "総合レポート")[:40], "weight": "bold", "color": "#ffffff", "size": "md" }]
                },
                "body": {
                    "type": "box", "layout": "vertical", "spacing": "md",
                    "contents": [
                        # 銘柄リストテーブル
                        { "type": "box", "layout": "vertical", "spacing": "xs", "contents": flex_stocks },
                        { "type": "separator" },
                        # 分析セクション1
                        { "type": "text", "text": data.get("analysis_1_title", "分析1"), "weight": "bold", "size": "sm" },
                        { "type": "text", "text": data.get("analysis_1_content", "内容なし"), "wrap": True, "size": "xs", "color": "#333333" },
                        # 分析セクション2
                        { "type": "text", "text": data.get("analysis_2_title", "分析2"), "weight": "bold", "size": "sm" },
                        { "type": "text", "text": data.get("analysis_2_content", "内容なし"), "wrap": True, "size": "xs", "color": "#333333" },
                        # 投資戦略セクション
                        { "type": "text", "text": data.get("strategy_title", "戦略"), "weight": "bold", "size": "sm", "color": "#b91c1c" },
                        { "type": "text", "text": data.get("strategy_content", "内容なし"), "wrap": True, "size": "xs", "color": "#333333" }
                    ]
                }
            }
        }]
    }
    
    try:
        res = requests.post(url, headers={"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"}, json=flex_message)
        print(f"【3】LINE送信完了 ステータス: {res.status_code}")
    except Exception as e:
        print(f"【3】LINE送信エラー: {e}")


if __name__ == "__main__":
    sheet = get_sheet()
    update_stock_data(sheet)
    timing = get_current_timing()  # 現在時刻から「朝・昼・夜」を自動判定
    report = generate_analysis_report(sheet, timing)
    send_to_line(report)