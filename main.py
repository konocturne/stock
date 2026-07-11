import os
import json
import time
import re
from datetime import datetime, timedelta, timezone
import requests
import xml.etree.ElementTree as ET
import yfinance as yf
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
from dotenv import load_dotenv

# .envファイルから環境変数を読み込む (ローカル実行用)
load_dotenv()

# ========================
# 設定
# ========================
GEMINI_API_KEY        = os.environ.get("GEMINI_API_KEY")
LINE_ACCESS_TOKEN     = os.environ.get("LINE_ACCESS_TOKEN")
LINE_USER_ID          = os.environ.get("LINE_USER_ID")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
SPREADSHEET_KEY       = "1-bql8g-s0JcEzy4neAzSaM9cU0dGZQ5eYhhc6cTuwF0"
GEMINI_MODEL          = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GITHUB_PAGES_URL      = os.environ.get("GITHUB_PAGES_URL", "")
LAST_REPORT_FILE      = "last_report.json"

JST = timezone(timedelta(hours=9))

# ========================
# 認証ユーティリティ
# ========================

def _get_creds_dict():
    """Google Credentials を環境変数またはJSONファイルから取得"""
    if GOOGLE_CREDENTIALS_JSON:
        try:
            return json.loads(GOOGLE_CREDENTIALS_JSON)
        except json.JSONDecodeError:
            pass
    json_path = "gen-lang-client-0001329181-b47d41c19dcb.json"
    if os.path.exists(json_path):
        with open(json_path, "r") as f:
            return json.load(f)
    raise ValueError("Google credentials are not set")

def get_spreadsheet():
    """スプレッドシートオブジェクトを返す"""
    creds = Credentials.from_service_account_info(
        _get_creds_dict(),
        scopes=["https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"]
    )
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_KEY)

# ========================
# スプレッドシート初期化
# ========================

def initialize_headers(sheet):
    headers = [
        "銘柄コード", "銘柄名", "保有数", "平均取得単価",
        "現在値", "前日比(%)", "前日比(円)", "出来高", "売買代金(万円)",
        "前日終値", "始値", "高値", "安値", "52週高値", "52週安値",
        "時価総額(億円)", "PER", "PBR", "配当利回り(%)", "1株配当(円)", "ROE(%)", "業種"
    ]
    current = sheet.row_values(1)
    if len(current) < len(headers) or current[:len(headers)] != headers:
        sheet.update(range_name="A1:V1", values=[headers])

def _get_or_create_sheet(spreadsheet, title, headers):
    """指定タイトルのシートを取得、なければ作成する"""
    try:
        return spreadsheet.worksheet(title)
    except Exception:
        sheet = spreadsheet.add_worksheet(title=title, rows=10000, cols=len(headers))
        col_end = chr(64 + len(headers))
        sheet.update(range_name=f"A1:{col_end}1", values=[headers])
        return sheet

# ========================
# 状態管理（スプレッドシートで永続化）
# report_state.json は廃止 — GitHub Actions はステートレスのため
# ========================

def load_previous_state(spreadsheet):
    """「状態」シートから前回のAI予測を読み込む"""
    try:
        state_sheet = _get_or_create_sheet(spreadsheet, "状態", ["日付", "時間帯", "戦略"])
        values = state_sheet.get_all_values()
        if len(values) >= 2 and len(values[1]) >= 3:
            return {"date": values[1][0], "timing": values[1][1], "strategy": values[1][2]}
    except Exception as e:
        print(f"[警告] 前回状態の読み込みエラー: {e}")
    return None

def save_current_state(spreadsheet, timing, strategy):
    """「状態」シートに今回のAI戦略を保存"""
    try:
        state_sheet = _get_or_create_sheet(spreadsheet, "状態", ["日付", "時間帯", "戦略"])
        today = datetime.now(JST).strftime("%Y-%m-%d")
        state_sheet.update(range_name="A2:C2", values=[[today, timing, strategy]])
    except Exception as e:
        print(f"[警告] 状態の保存エラー: {e}")

# ========================
# 時間帯判定
# ========================

def get_current_timing():
    test = os.environ.get("TEST_TIMING")
    if test in ["朝", "昼", "夜"]:
        return test
    hour = datetime.now(JST).hour
    if 5 <= hour < 11:
        return "朝"
    elif 11 <= hour < 16:
        return "昼"
    return "夜"

# ========================
# 市場指標取得（日経225含む / ベンチマーク用）
# ========================

def get_market_indicators():
    print("【システム】市場指標を取得中...")
    indicators = {
        "S&P 500":  "^GSPC",
        "NASDAQ":   "^IXIC",
        "SOX指数":  "^SOX",
        "日経225":  "^N225",
        "日経先物": "NK=F",
    }
    result = {}
    for name, symbol in indicators.items():
        for attempt in range(3):
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="2d")
                if len(hist) >= 2:
                    price = hist['Close'].iloc[-1]
                    prev  = hist['Close'].iloc[-2]
                    pct   = (price - prev) / prev * 100
                    sign  = "+" if pct > 0 else ""
                    result[name] = {
                        "price":          f"{price:,.2f}",
                        "change_pct":     f"{sign}{pct:.2f}%",
                        "change_pct_raw": pct,
                    }
                else:
                    result[name] = {"price": "取得失敗", "change_pct": "---", "change_pct_raw": 0}
                break
            except Exception:
                if attempt == 2:
                    result[name] = {"price": "エラー", "change_pct": "---", "change_pct_raw": 0}
                time.sleep(0.5)
    return result

# ========================
# テクニカル指標計算（RSI / MACD / ボリンジャーバンド / SMA50）
# 追加 API コール一切なし — yfinance の 6mo データを流用
# ========================

def calculate_technical_indicators(hist: pd.DataFrame) -> dict:
    if hist.empty or len(hist) < 26:
        return {
            "rsi": None, "macd": None, "macd_signal": None,
            "bb_upper": None, "bb_lower": None, "sma50": None,
            "tech_signal": "データ不足",
        }

    close = hist['Close']

    # RSI (14日)
    delta = close.diff()
    gain  = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss  = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rsi_val = float((100 - 100 / (1 + gain / loss)).iloc[-1])

    # MACD (12, 26, 9)
    ema12      = close.ewm(span=12, adjust=False).mean()
    ema26      = close.ewm(span=26, adjust=False).mean()
    macd_line  = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_val   = float(macd_line.iloc[-1])
    signal_val = float(signal_line.iloc[-1])

    # ボリンジャーバンド (20日, 2σ)
    sma20      = close.rolling(20).mean()
    std20      = close.rolling(20).std()
    bb_upper_val = float((sma20 + 2 * std20).iloc[-1])
    bb_lower_val = float((sma20 - 2 * std20).iloc[-1])

    # SMA50
    sma50_val   = float(close.tail(50).mean()) if len(close) >= 50 else None
    current_price = float(close.iloc[-1])

    # シグナル文字列
    signals = []
    if   rsi_val >= 70: signals.append(f"RSI過熱({rsi_val:.0f})")
    elif rsi_val <= 30: signals.append(f"RSI売られすぎ({rsi_val:.0f})")
    else:               signals.append(f"RSI中立({rsi_val:.0f})")

    signals.append("MACD↑ゴールデン" if macd_val > signal_val else "MACD↓デッド")

    if   current_price > bb_upper_val: signals.append("BB上限突破(過熱)")
    elif current_price < bb_lower_val: signals.append("BB下限割れ(売られすぎ)")
    else:                               signals.append("BB圏内")

    if sma50_val:
        if   current_price > sma50_val * 1.05: signals.append("SMA50大幅上回り")
        elif current_price < sma50_val * 0.95: signals.append("SMA50大幅下回り")

    return {
        "rsi": rsi_val, "macd": macd_val, "macd_signal": signal_val,
        "bb_upper": bb_upper_val, "bb_lower": bb_lower_val,
        "sma50": sma50_val, "tech_signal": " / ".join(signals),
    }

# ========================
# ニュース取得
# ========================

def fetch_recent_news(code, name):
    url = f"https://news.yahoo.co.jp/rss/search?p={code}&ei=UTF-8"
    titles = []
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            root = ET.fromstring(res.text)
            for item in root.findall('./channel/item')[:3]:
                t = item.find('title')
                if t is not None and t.text:
                    titles.append(t.text)
    except Exception:
        pass
    return " / ".join(titles) if titles else "直近の目立ったニュースはありません。"

# ========================
# 夜間PTS取得（リトライ付き）
# ========================

def get_pts_price(code):
    print(f"【システム】銘柄 {code} の夜間PTS情報を取得中...")
    url     = f"https://kabutan.jp/stock/?code={code}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    for attempt in range(2):
        try:
            res = requests.get(url, headers=headers, timeout=8)
            if res.status_code == 200:
                m = re.search(
                    r'class="kabuka1">PTS</div>\s*<div class="kabuka2">([^<]+)</div>',
                    res.text
                )
                if m:
                    return m.group(1).strip()
            break
        except Exception:
            time.sleep(1)
    return None

# ========================
# フォーマットユーティリティ
# ========================

def format_currency(val):
    try:
        f = float(str(val).replace(",", ""))
        if f == 0:
            return "---"
        return f"{int(f):,}" if f.is_integer() else f"{f:,.1f}"
    except Exception:
        return str(val)

# ========================
# 株データ更新（yfinance → スプレッドシート書き込み）
# ========================

def update_stock_data(sheet):
    """
    yfinanceで最新株価・財務情報を取得し、スプレッドシートに書き込む。
    テクニカル指標を計算し、プロンプト用コンテキストを返す。
    追加 API コール: yfinance のみ（無料・制限なし）
    """
    print("【1】yfinanceからのデータ取得とテクニカル分析を開始します")
    records = sheet.get_all_values()
    technical_context = {}

    for i, row in enumerate(records[1:], start=2):
        if not row or not row[0].strip():
            continue
        code = row[0].strip()
        row  = row + [""] * (22 - len(row))

        for attempt in range(3):
            try:
                ticker = yf.Ticker(f"{code}.T")
                info   = ticker.info
                name   = info.get("longName") or info.get("shortName") or code
                hist   = ticker.history(period="6mo")

                if not hist.empty:
                    current_price = float(hist['Close'].iloc[-1])
                    prev_close    = float(hist['Close'].iloc[-2]) if len(hist) > 1 else current_price
                    open_price    = float(hist['Open'].iloc[-1])
                    day_high      = float(hist['High'].iloc[-1])
                    day_low       = float(hist['Low'].iloc[-1])
                    volume        = int(hist['Volume'].iloc[-1])
                else:
                    current_price = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
                    prev_close    = float(info.get("previousClose") or info.get("regularMarketPreviousClose") or 0)
                    open_price    = float(info.get("open") or 0)
                    day_high      = float(info.get("dayHigh") or 0)
                    day_low       = float(info.get("dayLow") or 0)
                    volume        = int(info.get("volume") or 0)
                    hist          = pd.DataFrame()

                tech = calculate_technical_indicators(hist)

                # 含み損益計算
                try:
                    avg_cost = float(str(row[3]).replace(",", "")) if row[3] else 0
                    quantity = int(str(row[2]).replace(",", ""))   if row[2] else 0
                except Exception:
                    avg_cost, quantity = 0, 0

                cost_total = avg_cost * quantity
                eval_total = current_price * quantity
                pnl        = eval_total - cost_total
                pnl_pct    = (pnl / cost_total * 100) if cost_total > 0 else 0
                pnl_sign   = "+" if pnl >= 0 else ""

                raw_change     = current_price - prev_close
                raw_change_pct = (raw_change / prev_close * 100) if prev_close else 0
                change_str     = f"{'+' if raw_change > 0 else ''}{format_currency(raw_change)}円"
                change_pct_str = f"{'+' if raw_change_pct > 0 else ''}{raw_change_pct:.2f}%"

                trading_value  = round((current_price * volume) / 10000) if current_price and volume else 0
                market_cap_oku = round((info.get("marketCap") or 0) / 100000000)

                per       = info.get("forwardPE") or info.get("trailingPE")
                pbr       = info.get("priceToBook")
                div_yield = info.get("dividendYield")

                recent_news = fetch_recent_news(code, name)

                # テクニカルコンテキスト文字列
                if tech["rsi"]:
                    tech_text = (
                        f"【テクニカル】{tech['tech_signal']}\n"
                        f"　RSI:{tech['rsi']:.1f} / MACD:{tech['macd']:.2f}(sig:{tech['macd_signal']:.2f})\n"
                        f"　BB上:{format_currency(tech['bb_upper'])} / BB下:{format_currency(tech['bb_lower'])}"
                    )
                else:
                    tech_text = f"【テクニカル】{tech['tech_signal']}"

                pnl_text = (
                    f"【含み損益】{pnl_sign}{format_currency(pnl)}円 "
                    f"({pnl_sign}{pnl_pct:.2f}%) "
                    f"評価額:{format_currency(eval_total)}円"
                )
                technical_context[code] = f"{tech_text}\n{pnl_text}\n【ニュース】{recent_news}"

                # スプレッドシート更新
                update_row = [
                    name, row[2], row[3],
                    format_currency(current_price), change_pct_str, change_str,
                    format_currency(volume), format_currency(trading_value),
                    format_currency(prev_close), format_currency(open_price),
                    format_currency(day_high), format_currency(day_low),
                    format_currency(info.get("fiftyTwoWeekHigh") or 0),
                    format_currency(info.get("fiftyTwoWeekLow") or 0),
                    format_currency(market_cap_oku),
                    f"{per:.1f}倍" if per else "---",
                    f"{pbr:.2f}倍" if pbr else "---",
                    f"{div_yield * 100:.2f}%" if div_yield else "---",
                    f"{format_currency(info.get('dividendRate') or 0)}円",
                    f"{(info.get('returnOnEquity') or 0) * 100:.2f}%",
                    info.get("sector") or "---",
                ]
                sheet.update(range_name=f"B{i}:V{i}", values=[update_row])
                print(f"[取得完了] {code}: {name} / {format_currency(current_price)}円 ({change_pct_str})")
                time.sleep(0.5)
                break  # 成功
            except Exception as e:
                print(f"[エラー] {code} (試行{attempt+1}/3): {e}")
                if attempt < 2:
                    time.sleep(1)

    return technical_context

# ========================
# Gemini 分析レポート生成
# ★ 1実行あたり必ず1回のみ呼び出す ★
# 感情分析・ベンチマーク比較・テクニカル分析を全て1プロンプトに統合
# ========================

def generate_analysis_report(sheet, spreadsheet, timing, tech_context, market_data):
    records = sheet.get_all_values()
    if len(records) < 2:
        return None

    today_str = datetime.now(JST).strftime("%Y-%m-%d")
    stocks_prompt_text = ""

    for row in records[1:]:
        row  = row + [""] * (22 - len(row))
        code = row[0].strip()
        if not code:
            continue

        pts_info = ""
        if timing == "夜":
            pts      = get_pts_price(code)
            pts_info = f"\n【夜間PTS】{pts}円" if pts else "\n【夜間PTS】取得不可"

        stocks_prompt_text += f"""
---
【銘柄】{code} {row[1]} (業種: {row[21]})
【保有状況】取得単価:{row[3]}円 / 保有数:{row[2]}株
【本日の値動き】現在値:{row[4]}円 (前日比: {row[5]} / {row[6]})、出来高:{row[7]}株、売買代金:{row[8]}万円
【長期指標】52週高値:{row[13]}円、安値:{row[14]}円、時価総額:{row[15]}億円
【バリュエーション】PER:{row[16]}、PBR:{row[17]}、配当利回り:{row[18]}
{tech_context.get(code, "")}{pts_info}
"""

    market_str    = "\n".join([f"・{k}: {v['price']} ({v['change_pct']})" for k, v in market_data.items()])
    nikkei_change = market_data.get("日経225", {}).get("change_pct", "---")

    prev_state   = load_previous_state(spreadsheet)
    prev_context = ""
    if prev_state and prev_state.get("date") == today_str:
        prev_context = (
            f"\n【前回のあなたの予測 ({prev_state['timing']})】\n{prev_state['strategy']}\n"
            "※この過去の予測と現在の結果を比較して、答え合わせや見直しを行ってください。"
        )

    if timing == "朝":
        role_prompt = f"""あなたはプロの証券アナリストです。本日は朝礼の時間です。
前日の米国・日本市場の結果と各銘柄の最新ニュース・テクニカル指標（RSI/MACD/BB）から、本日の日本市場開始前の地合いを評価してください。
【市場指標】
{market_str}
今日の寄り付きで狙うべきアクションプラン（利確・押し目買い・静観など）を提案してください。"""
    elif timing == "昼":
        role_prompt = f"""あなたはプロの証券アナリストです。現在は昼休み（前場引け後）です。
前場の実際の値動きを見て、朝立てた予測との答え合わせを行ってください。
【現在の市場指標】
{market_str}
想定外の連れ高・連れ安、出来高急増、RSI/MACD/BBシグナルを確認し、後場に向けたアクションを提案してください。"""
    else:
        role_prompt = f"""あなたはプロの証券アナリストです。現在は大引け後（夜）です。
本日の最終的な値動きと夜間PTSを総合的に分析し、1日の総括を行ってください。
【現在の市場指標】
{market_str}
テクニカル指標の類似パターンも考慮し、明日以降の中長期戦略を構築してください。"""

    prompt = f"""{role_prompt}
{prev_context}

以下の保有銘柄データから、ポートフォリオ全体をスキャンした総合投資戦略レポートをJSON形式のみで作成してください。Markdownは不要。

【保有銘柄データ】
{stocks_prompt_text}

【出力形式】必ず次のJSON構造のみを返すこと。
{{
  "title": "{timing}の証券アナリスト・レポート",
  "statusColor": "#b91c1c",
  "alerts": ["🚨 XX銘柄で過熱感のサイン", "💡 XXセクターに好材料"],
  "weather": "半導体:☀️ / 銀行:☁️",
  "benchmark": "日経225({nikkei_change}) vs ポートフォリオ: ±X.XX%",
  "stocks": [{{
    "name": "銘柄名",
    "code": "コード",
    "price": "現在値(前日比)",
    "sentiment": "ポジティブ/ネガティブ/ニュートラル",
    "info": "ニュース・テクニカルの要約（50字以内）"
  }}],
  "analysis_1_title": "市場環境と答え合わせ",
  "analysis_1_content": "分析内容（200字以内）",
  "analysis_2_title": "テクニカル＆セクター分析",
  "analysis_2_content": "RSI・MACD・BB・過去パターンを含む分析（200字以内）",
  "strategy_title": "アクションプラン",
  "strategy_content": "具体的な売買戦略（200字以内）"
}}"""

    print(f"【2】Gemini ({GEMINI_MODEL}) で分析レポートを生成中 (本実行で1回のみ)...")
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)

    # 429 レート制限に対して指数バックオフでリトライ
    for attempt in range(3):
        try:
            response = model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            report = json.loads(response.text)
            save_current_state(spreadsheet, timing, report.get("strategy_content", ""))
            return report
        except Exception as e:
            err_str = str(e)
            if "429" in err_str and attempt < 2:
                wait = (2 ** attempt) * 10
                print(f"[警告] Gemini APIレート制限 — {wait}秒待機後リトライ")
                time.sleep(wait)
            else:
                print(f"[エラー] Gemini API: {e}")
                if attempt == 2:
                    raise
    return None

# ========================
# LINE 送信（Flex Message + チャート画像 + 感情カラー + ベンチマーク）
# ========================

def send_to_line(data, today_str=None):
    if not data:
        return
    url = "https://api.line.me/v2/bot/message/push"

    sentiment_colors = {
        "ポジティブ": "#15803d",
        "ネガティブ": "#b91c1c",
        "ニュートラル": "#475569",
    }

    # 銘柄テーブル
    flex_stocks = [
        {
            "type": "box", "layout": "horizontal", "contents": [
                {"type": "text", "text": "銘柄",    "size": "xs", "color": "#888888", "weight": "bold", "flex": 2},
                {"type": "text", "text": "値動き",  "size": "xs", "color": "#888888", "align": "center", "weight": "bold", "flex": 3},
                {"type": "text", "text": "感情/一言", "size": "xs", "color": "#888888", "align": "end", "weight": "bold", "flex": 5},
            ]
        },
        {"type": "separator", "margin": "sm"},
    ]

    for s in data.get("stocks", []):
        sentiment = s.get("sentiment", "ニュートラル")
        s_color   = sentiment_colors.get(sentiment, "#475569")
        tag       = sentiment[:3] if len(sentiment) >= 3 else sentiment
        flex_stocks.append({
            "type": "box", "layout": "horizontal", "margin": "sm", "contents": [
                {"type": "text", "text": s.get("name", ""),  "size": "xs", "weight": "bold", "wrap": True, "flex": 2},
                {"type": "text", "text": s.get("price", ""), "size": "xs", "align": "center", "wrap": True, "flex": 3},
                {"type": "text", "text": f"[{tag}] {s.get('info', '')}",
                 "size": "xxs", "align": "end", "wrap": True, "color": s_color, "flex": 5},
            ]
        })

    alerts_box = [
        {"type": "text", "text": a, "size": "sm", "color": "#b91c1c", "weight": "bold", "wrap": True}
        for a in data.get("alerts", [])
    ]

    body_contents = []
    if alerts_box:
        body_contents.append({
            "type": "box", "layout": "vertical",
            "backgroundColor": "#fee2e2", "paddingAll": "sm", "cornerRadius": "md",
            "contents": alerts_box,
        })
    if data.get("benchmark"):
        body_contents.append({
            "type": "text", "text": f"📊 {data['benchmark']}",
            "size": "xs", "color": "#1d4ed8", "wrap": True, "margin": "sm",
        })
    body_contents += [
        {"type": "box", "layout": "vertical", "spacing": "xs", "contents": flex_stocks},
        {"type": "separator", "margin": "lg"},
        {"type": "text", "text": data.get("analysis_1_title", ""), "weight": "bold", "size": "sm", "color": "#334155"},
        {"type": "text", "text": data.get("analysis_1_content", ""), "wrap": True, "size": "xs", "color": "#475569"},
        {"type": "text", "text": data.get("analysis_2_title", ""), "weight": "bold", "size": "sm", "color": "#334155", "margin": "md"},
        {"type": "text", "text": data.get("analysis_2_content", ""), "wrap": True, "size": "xs", "color": "#475569"},
        {
            "type": "box", "layout": "vertical", "margin": "lg",
            "backgroundColor": "#eff6ff", "paddingAll": "md", "cornerRadius": "md",
            "contents": [
                {"type": "text", "text": data.get("strategy_title", ""), "weight": "bold", "size": "sm", "color": "#1d4ed8"},
                {"type": "text", "text": data.get("strategy_content", ""), "wrap": True, "size": "xs", "color": "#1e3a8a", "margin": "sm"},
            ],
        },
    ]

    bubble = {
        "type": "bubble",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#1e293b",
            "contents": [
                {"type": "text", "text": data.get("title", "レポート"), "weight": "bold", "color": "#ffffff", "size": "md"},
                {"type": "text", "text": f"セクター: {data.get('weather', '')}", "color": "#cbd5e1", "size": "sm", "margin": "sm"},
            ],
        },
        "body": {"type": "box", "layout": "vertical", "spacing": "md", "contents": body_contents},
    }

    # ポートフォリオ概要チャートをヒーロー画像として添付
    if GITHUB_PAGES_URL and today_str:
        overview_url = f"{GITHUB_PAGES_URL}/charts/{today_str}/portfolio_overview.png"
        bubble["hero"] = {
            "type": "image",
            "url": overview_url,
            "size": "full",
            "aspectRatio": "20:8",
            "aspectMode": "cover",
            "action": {"type": "uri", "uri": f"{GITHUB_PAGES_URL}/"},
        }

    flex_message = {
        "to": LINE_USER_ID,
        "messages": [{
            "type": "flex",
            "altText": data.get("title", "アナリストレポート"),
            "contents": bubble,
        }],
    }

    try:
        res = requests.post(
            url,
            headers={"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"},
            json=flex_message,
        )
        print(f"【3】LINE送信完了 ステータス: {res.status_code}")
        if res.status_code != 200:
            print(f"[警告] LINE APIレスポンス: {res.text[:300]}")
    except Exception as e:
        print(f"【3】LINE送信エラー: {e}")

# ========================
# メイン処理
# ========================

if __name__ == "__main__":
    spreadsheet = get_spreadsheet()
    sheet       = spreadsheet.worksheet("保有銘柄")
    initialize_headers(sheet)

    timing    = get_current_timing()
    today_str = datetime.now(JST).strftime("%Y-%m-%d")
    print(f"=== 実行開始: {today_str} {timing} (モデル: {GEMINI_MODEL}) ===")

    tech_context = update_stock_data(sheet)
    market_data  = get_market_indicators()
    report       = generate_analysis_report(sheet, spreadsheet, timing, tech_context, market_data)

    if report:
        send_to_line(report, today_str)
        # history.py 用にレポートを一時保存
        with open(LAST_REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump({"report": report, "timing": timing, "date": today_str}, f, ensure_ascii=False)
        print(f"【完了】レポートを {LAST_REPORT_FILE} に保存")

    print("=== 実行完了 ===")