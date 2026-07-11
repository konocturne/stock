import os
import json
import time
import re
from datetime import datetime, timedelta, timezone
import requests
import xml.etree.ElementTree as ET
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
STATE_FILE = "report_state.json"

def get_current_timing():
    test_timing = os.environ.get("TEST_TIMING")
    if test_timing in ["朝", "昼", "夜"]:
        return test_timing
        
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
            hist = ticker.history(period="2d")
            if len(hist) >= 2:
                price = hist['Close'].iloc[-1]
                prev_close = hist['Close'].iloc[-2]
                change = price - prev_close
                change_pct = (change / prev_close) * 100
                sign = "+" if change > 0 else ""
                result[name] = f"{price:,.2f} ({sign}{change_pct:.2f}%)"
            else:
                result[name] = "取得失敗"
        except Exception as e:
            result[name] = f"エラー"
    return result

def fetch_recent_news(code, name):
    # Yahooファイナンスのニュース検索RSSを利用
    url = f"https://news.yahoo.co.jp/rss/search?p={code}&ei=UTF-8"
    news_titles = []
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            root = ET.fromstring(res.text)
            for item in root.findall('./channel/item')[:3]:  # 最新3件
                title = item.find('title').text
                news_titles.append(title)
    except Exception:
        pass
    
    if not news_titles:
        return "直近の目立ったニュースはありません。"
    return " / ".join(news_titles)

def get_pts_price(code):
    print(f"【システム】銘柄 {code} の夜間PTS情報を取得中...")
    url = f"https://kabutan.jp/stock/?code={code}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            m = re.search(r'class="kabuka1">PTS</div>\s*<div class="kabuka2">([^<]+)</div>', res.text)
            if m:
                return m.group(1).strip()
    except Exception:
        pass
    return None

def format_currency(val):
    try:
        f_val = float(val)
        if f_val.is_integer():
            return f"{int(f_val):,}"
        return f"{f_val:,.1f}"
    except:
        return val

def initialize_headers(sheet):
    headers = [
        "銘柄コード", "銘柄名", "保有数", "平均取得単価",
        "現在値", "前日比(%)", "前日比(円)", "出来高", "売買代金(万円)",
        "前日終値", "始値", "高値", "安値", "52週高値", "52週安値",
        "時価総額(億円)", "PER", "PBR", "配当利回り(%)", "1株配当(円)", "ROE(%)", "業種"
    ]
    current_headers = sheet.row_values(1)
    if len(current_headers) < len(headers) or current_headers[:len(headers)] != headers:
        sheet.update(range_name="A1:V1", values=[headers])

def get_sheet():
    creds_dict = None
    if GOOGLE_CREDENTIALS_JSON:
        try:
            creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        except json.JSONDecodeError:
            pass
            
    if not creds_dict:
        json_path = "gen-lang-client-0001329181-b47d41c19dcb.json"
        if os.path.exists(json_path):
            with open(json_path, "r") as f:
                creds_dict = json.load(f)
        else:
            raise ValueError("Google credentials are not set")
            
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_KEY).worksheet("保有銘柄")
    initialize_headers(sheet)
    return sheet

def update_stock_data(sheet):
    print("【1】yfinanceからのデータ取得とコンテキスト分析を開始します")
    records = sheet.get_all_values()
    
    technical_context = {}
    
    for i, row in enumerate(records[1:], start=2):
        if not row or len(row) < 1: continue
        code = row[0].strip()
        if not code: continue
            
        ticker_symbol = f"{code}.T"
        ticker = yf.Ticker(ticker_symbol)
        row = row + [""] * (4 - len(row))
        
        try:
            info = ticker.info
            name = info.get("longName") or info.get("shortName") or code
            
            # 過去半年のデータでテクニカル分析を簡易実行
            hist = ticker.history(period="6mo")
            current_price = 0
            sma50 = 0
            tech_signal = "ニュートラル"
            
            if not hist.empty:
                current_price = hist['Close'].iloc[-1]
                prev_close = hist['Close'].iloc[-2] if len(hist) > 1 else current_price
                open_price = hist['Open'].iloc[-1]
                day_high = hist['High'].iloc[-1]
                day_low = hist['Low'].iloc[-1]
                volume = hist['Volume'].iloc[-1]
                
                if len(hist) >= 50:
                    sma50 = hist['Close'].tail(50).mean()
                    if current_price > sma50 * 1.05: tech_signal = "上昇トレンド（過熱感あり）"
                    elif current_price < sma50 * 0.95: tech_signal = "下降トレンド（反発待ち）"
                    else: tech_signal = "揉み合い（SMA50付近）"
            else:
                current_price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
                prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose") or 0
                open_price = info.get("open") or 0
                day_high = info.get("dayHigh") or 0
                day_low = info.get("dayLow") or 0
                volume = info.get("volume") or 0

            raw_change = current_price - prev_close if current_price and prev_close else 0
            raw_change_pct = (raw_change / prev_close) * 100 if prev_close else 0
            
            change_str = f"+{format_currency(raw_change)}円" if raw_change > 0 else f"{format_currency(raw_change)}円"
            change_pct_str = f"+{raw_change_pct:.2f}%" if raw_change_pct > 0 else f"{raw_change_pct:.2f}%"
            
            trading_value = round((current_price * volume) / 10000) if current_price and volume else 0
            market_cap_raw = info.get("marketCap", 0)
            market_cap_oku = round(market_cap_raw / 100000000) if market_cap_raw else 0
            
            # 各種数値をカンマ区切りにフォーマット
            c_price_str = format_currency(current_price)
            c_vol_str = format_currency(volume)
            c_tv_str = format_currency(trading_value)
            c_mc_str = format_currency(market_cap_oku)
            
            per = info.get("forwardPE") or info.get("trailingPE")
            per_str = f"{per:.1f}倍" if per else "---"
            pbr = info.get("priceToBook")
            pbr_str = f"{pbr:.2f}倍" if pbr else "---"
            div_yield = info.get("dividendYield")
            div_yield_str = f"{div_yield * 100:.2f}%" if div_yield else "---"
            
            sector = info.get("sector") or "---"
            
            # ニュース取得
            recent_news = fetch_recent_news(code, name)
            technical_context[code] = f"【テクニカル】{tech_signal} (SMA50: {format_currency(sma50)}円)\n【ニュース】{recent_news}"
            
            update_row = [
                name, row[2], row[3], c_price_str, change_pct_str, change_str,
                c_vol_str, c_tv_str, format_currency(prev_close), format_currency(open_price),
                format_currency(day_high), format_currency(day_low),
                format_currency(info.get("fiftyTwoWeekHigh") or 0), format_currency(info.get("fiftyTwoWeekLow") or 0),
                c_mc_str, per_str, pbr_str, div_yield_str,
                f"{format_currency(info.get('dividendRate') or 0)}円",
                f"{(info.get('returnOnEquity') or 0) * 100:.2f}%", sector
            ]
            
            sheet.update(range_name=f"B{i}:V{i}", values=[update_row])
            print(f"[取得完了] {code}: {name} / {c_price_str}円")
            time.sleep(0.5)
        except Exception as e:
            print(f"[エラー] {code}: {e}")
            
    return technical_context

def load_previous_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return None

def save_current_state(timing, strategy):
    data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timing": timing,
        "strategy": strategy
    }
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False)

def generate_analysis_report(sheet, timing, tech_context):
    records = sheet.get_all_values()
    if len(records) < 2:
        return None
        
    stocks_prompt_text = ""
    for row in records[1:]:
        if len(row) < 22: row += [""] * (22 - len(row))
        code, name = row[0].strip(), row[1]
        if not code: continue
        
        pts_info = ""
        if timing == "夜":
            pts = get_pts_price(code)
            pts_info = f"\n【夜間PTS】{pts}" if pts else ""
            
        t_ctx = tech_context.get(code, "")
            
        stocks_prompt_text += f"""
---
【銘柄】{code} {name} (業種: {row[21]})
【保有状況】取得単価:{row[3]}円 / 保有数:{row[2]}株
【本日の値動き】現在値:{row[4]}円 (前日比: {row[5]} / {row[6]})、出来高:{row[7]}株、売買代金:{row[8]}万円
【長期指標】52週高値:{row[13]}円、安値:{row[14]}円、時価総額:{row[15]}億円
【指標】PER:{row[16]}、PBR:{row[17]}、配当利回り:{row[18]}
{t_ctx}{pts_info}
"""

    prev_state = load_previous_state()
    prev_context = ""
    if prev_state and prev_state["date"] == datetime.now().strftime("%Y-%m-%d"):
        prev_context = f"\n【前回のあなたの予測 ({prev_state['timing']})】\n{prev_state['strategy']}\n※この過去の予測と現在の結果を比較して、答え合わせや見直しを行ってください。"

    if timing == "朝":
        market_data = get_market_indicators()
        market_str = "\n".join([f"・{k}: {v}" for k, v in market_data.items()])
        role_prompt = f"""あなたはプロの証券アナリストです。本日は朝礼の時間です。
前日の米国市場の結果（以下）と各銘柄の最新ニュースから、本日の日本市場開始前の地合いを評価してください。
{market_str}
セクターの風潮やテクニカル指標の過去の類似パターンを加味し、今日の寄り付きで狙うべきアクションプラン（利確、押し目買い、静観など）を提案してください。"""
    elif timing == "昼":
        role_prompt = """あなたはプロの証券アナリストです。現在は昼休み（前場引け後）です。
前場の実際の値動きを見て、朝立てた予測（存在する場合）との答え合わせを行ってください。
想定外の連れ高・連れ安や、出来高急増などの需給シグナルがないかを観察し、後場に向けたトレードアクションを提案してください。"""
    else:
        role_prompt = """あなたはプロの証券アナリストです。現在は大引け後（夜）です。
本日の最終的な値動きと、夜間PTSの動向、引け後ニュースを総合的に分析し、1日の総括を行ってください。
過去の類似チャートパターンも考慮に入れ、明日以降の中長期的なポートフォリオのトレンドと戦略を構築してください。"""

    prompt = f"""{role_prompt}
{prev_context}

以下の保有銘柄データから、ポートフォリオ全体をスキャンした総合投資戦略レポートをJSON形式のみで作成してください。Markdownマークアップは除外してください。

【保有銘柄データ】
{stocks_prompt_text}

【出力形式】必ず次のJSON構造のみを返すこと。
{{
  "title": "{timing}の証券アナリスト・レポート",
  "statusColor": "#b91c1c",
  "alerts": ["🚨 XX銘柄で過熱感のサイン", "💡 XXセクターに好材料のニュース"],
  "weather": "半導体:☀️ / 銀行:☁️",
  "stocks": [{{"name":"銘柄名", "code":"コード", "price":"現在値(前日比)", "info":"ニュースやテクニカルの要約"}}],
  "analysis_1_title": "市場環境と答え合わせ",
  "analysis_1_content": "分析内容",
  "analysis_2_title": "テクニカル＆セクター分析",
  "analysis_2_content": "過去の類似パターンを含めた分析",
  "strategy_title": "アクションプラン",
  "strategy_content": "具体的な売買戦略"
}}"""

    genai.configure(api_key=GEMINI_API_KEY)
    # gemini-1.5-pro を使うとより高度なコンテキスト分析が可能（ローカル環境に依存しますが、Flashでも動作します）
    model = genai.GenerativeModel('gemini-1.5-pro')
    response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
    report = json.loads(response.text)
    
    # 状態の保存
    save_current_state(timing, report.get("strategy_content", ""))
    
    return report

def send_to_line(data):
    if not data: return
    url = "https://api.line.me/v2/bot/message/push"
    
    flex_stocks = []
    flex_stocks.append({
        "type": "box", "layout": "horizontal", "contents": [
            { "type": "text", "text": "銘柄", "size": "xs", "color": "#888888", "weight": "bold", "flex": 3 },
            { "type": "text", "text": "現在値(比)", "size": "xs", "color": "#888888", "align": "center", "weight": "bold", "flex": 3 },
            { "type": "text", "text": "一言", "size": "xs", "color": "#888888", "align": "end", "weight": "bold", "flex": 4 }
        ]
    })
    flex_stocks.append({ "type": "separator", "margin": "sm" })
    
    for s in data.get("stocks", []):
        flex_stocks.append({
            "type": "box", "layout": "horizontal", "margin": "sm", "contents": [
                { "type": "text", "text": s.get("name", ""), "size": "xs", "weight": "bold", "wrap": True, "flex": 3 },
                { "type": "text", "text": s.get("price", ""), "size": "xs", "align": "center", "wrap": True, "flex": 3 },
                { "type": "text", "text": s.get("info", ""), "size": "xxs", "align": "end", "wrap": True, "color": "#555555", "flex": 4 }
            ]
        })

    alerts_box = []
    for alert in data.get("alerts", []):
        alerts_box.append({
            "type": "text", "text": alert, "size": "sm", "color": "#b91c1c", "weight": "bold", "wrap": True
        })

    flex_message = {
        "to": LINE_USER_ID,
        "messages": [{
            "type": "flex",
            "altText": data.get("title", "アナリストレポート"),
            "contents": {
                "type": "bubble",
                "header": {
                    "type": "box", "layout": "vertical", "backgroundColor": "#1e293b",
                    "contents": [
                        { "type": "text", "text": data.get("title", "レポート"), "weight": "bold", "color": "#ffffff", "size": "md" },
                        { "type": "text", "text": f"セクター予報: {data.get('weather', '')}", "color": "#cbd5e1", "size": "sm", "margin": "sm" }
                    ]
                },
                "body": {
                    "type": "box", "layout": "vertical", "spacing": "md",
                    "contents": [
                        { "type": "box", "layout": "vertical", "backgroundColor": "#fee2e2", "paddingAll": "sm", "cornerRadius": "md", "contents": alerts_box } if alerts_box else { "type": "filler" },
                        { "type": "box", "layout": "vertical", "spacing": "xs", "contents": flex_stocks },
                        { "type": "separator", "margin": "lg" },
                        { "type": "text", "text": data.get("analysis_1_title", ""), "weight": "bold", "size": "sm", "color": "#334155" },
                        { "type": "text", "text": data.get("analysis_1_content", ""), "wrap": True, "size": "xs", "color": "#475569" },
                        { "type": "text", "text": data.get("analysis_2_title", ""), "weight": "bold", "size": "sm", "color": "#334155", "margin": "md" },
                        { "type": "text", "text": data.get("analysis_2_content", ""), "wrap": True, "size": "xs", "color": "#475569" },
                        { "type": "box", "layout": "vertical", "margin": "lg", "backgroundColor": "#eff6ff", "paddingAll": "md", "cornerRadius": "md", "contents": [
                            { "type": "text", "text": data.get("strategy_title", ""), "weight": "bold", "size": "sm", "color": "#1d4ed8" },
                            { "type": "text", "text": data.get("strategy_content", ""), "wrap": True, "size": "xs", "color": "#1e3a8a", "margin": "sm" }
                        ]}
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
    timing = get_current_timing()
    tech_context = update_stock_data(sheet)
    report = generate_analysis_report(sheet, timing, tech_context)
    send_to_line(report)