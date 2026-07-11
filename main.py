import os
import json
import time
import requests
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai

# 環境変数から設定を取得 (GitHub Secretsから安全に渡されます)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN")
LINE_USER_ID = os.environ.get("LINE_USER_ID")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
SPREADSHEET_KEY = "1-bql8g-s0JcEzy4neAzSaM9cU0dGZQ5eYhhc6cTuwF0"

def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
    )
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_KEY).sheet_by_name("保有銘柄")

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
        
        try:
            info = ticker.info
            
            # 安全にデータを取得（無い場合は歴史データから補完）
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
            
            # E列(5)からR列(18)までの更新データを1行分作成
            update_row = [
                current_price or "",
                change_pct_str,
                change_str,
                volume or "",
                trading_value,
                prev_close or "",
                open_price or "",
                day_high or "",
                day_low or "",
                info.get("fiftyTwoWeekHigh") or "",
                info.get("fiftyTwoWeekLow") or "",
                market_cap_oku,
                per_str,
                pbr_str
            ]
            
            # スプレッドシートへ書き込み
            sheet.update(range_name=f"E{i}:R{i}", values=[update_row])
            print(f"[取得完了] {code}: 現在値 {current_price}円 / PER {per_str} / PBR {pbr_str}")
            time.sleep(1)
            
        except Exception as e:
            print(f"[yfinance例外エラー] {code}: {e}")

def generate_analysis_report(sheet, timing):
    row2 = sheet.row_values(2)
    
    # 列の位置に合わせてデータを抽出
    code = row2[0]
    name = row2[1]
    avg_price = row2[3]
    cur_price = row2[4]
    change_pct = row2[5]
    change_yen = row2[6]
    volume = row2[7]
    trading_value = row2[8]
    open_price = row2[10]
    day_high = row2[11]
    day_low = row2[12]
    week52_high = row2[13]
    week52_low = row2[14]
    market_cap = row2[15]
    per = row2[16]
    pbr = row2[17]

    print(f"【2】Geminiへのリクエスト準備: 銘柄={code} {name}")

    prompt = f"""以下のデータから投資戦略レポートをJSON形式のみで作成してください。解説文は一切除外してください。
【銘柄】{code} {name}
【平均取得単価】{avg_price}円
【本日の値動き】現在値:{cur_price}円 (前日比: {change_pct} / {change_yen})、始値:{open_price}円、高値:{day_high}円、安値:{day_low}円
【相場エネルギー】出来高:{volume}株、売買代金:{trading_value}万円
【長期指標】52週高値:{week52_high}円、52週安値:{week52_low}円、時価総額:${market_cap}億円
【割安性指標】PER:{per}、PBR:{pbr}

【出力形式】次のJSONフォーマットのみを返してください。
{{"title": "{timing}の{name}戦略レポート", "statusColor": "#b91c1c", "metrics": [{{"label":"現在値","value":"{cur_price}円"}},{{"label":"前日比","value":"{change_pct}"}},{{"label":"高安","value":"{day_high}円 / {day_low}円"}},{{"label":"売買代金","value":"{trading_value}万円"}},{{"label":"PER / PBR","value":"{per} / {pbr}"}},{{"label":"52週高安","value":"{week52_high}円 / {week52_low}円"}}], "analysis_1_title": "1. 本日の値動き・テクニカル評価", "analysis_1_content": "分析内容", "analysis_2_title": "2. トレンドと需給動向", "analysis_2_content": "評価内容", "strategy_title": "3. 具体アクションプラン", "strategy_content": "戦略内容"}}"""

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    response = model.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json"}
    )
    
    return json.loads(response.text)

def send_to_line(data):
    if not data:
        return
        
    url = "https://api.line.me/v2/bot/message/push"
    color = data.get("statusColor", "#b91c1c")
    
    flex_metrics = []
    for m in data.get("metrics", []):
        flex_metrics.append({
            "type": "box", "layout": "horizontal", "contents": [
                { "type": "text", "text": m.get("label", "-"), "size": "sm", "color": "#555555" },
                { "type": "text", "text": m.get("value", "-"), "size": "sm", "align": "end", "weight": "bold" }
            ]
        })
        
    flex_message = {
        "to": LINE_USER_ID,
        "messages": [{
            "type": "flex",
            "altText": data.get("title", "レポート")[:40],
            "contents": {
                "type": "bubble",
                "header": {
                    "type": "box", "layout": "vertical", "backgroundColor": color,
                    "contents": [{ "type": "text", "text": data.get("title", "レポート")[:40], "weight": "bold", "color": "#ffffff", "size": "md" }]
                },
                "body": {
                    "type": "box", "layout": "vertical", "spacing": "md",
                    "contents": [
                        { "type": "box", "layout": "vertical", "spacing": "sm", "contents": flex_metrics },
                        { "type": "separator" },
                        { "type": "text", "text": data.get("analysis_1_title", "分析1"), "weight": "bold", "size": "sm" },
                        { "type": "text", "text": data.get("analysis_1_content", "内容なし"), "wrap": True, "size": "xs", "color": "#333333" },
                        { "type": "text", "text": data.get("analysis_2_title", "分析2"), "weight": "bold", "size": "sm" },
                        { "type": "text", "text": data.get("analysis_2_content", "内容なし"), "wrap": True, "size": "xs", "color": "#333333" },
                        { "type": "text", "text": data.get("strategy_title", "戦略"), "weight": "bold", "size": "sm", "color": "#b91c1c" },
                        { "type": "text", "text": data.get("strategy_content", "内容なし"), "wrap": True, "size": "xs", "color": "#333333" }
                    ]
                }
            }
        }]
    }
    
    headers = {
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    res = requests.post(url, headers=headers, json=flex_message)
    print(f"【3】LINE送信完了 ステータス: {res.status_code}")

if __name__ == "__main__":
    sheet = get_sheet()
    update_stock_data(sheet)
    report = generate_analysis_report(sheet, "朝")
    send_to_line(report)