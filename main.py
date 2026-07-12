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
# 銘柄名取得 (Yahoo!ファイナンス)
# ========================

def get_japanese_stock_name(code):
    url = f"https://finance.yahoo.co.jp/quote/{code}.T"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            m = re.search(r'<title>(.*?)【', res.text)
            if m:
                return m.group(1).strip()
    except Exception:
        pass
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
                # スプレッドシートにある既存の銘柄名（日本語）を優先、無ければYahooファイナンスからスクレイピング、それでも無ければyfinance
                name = row[1].strip() if len(row) > 1 and row[1].strip() else None
                if not name:
                    name = get_japanese_stock_name(code)
                if not name:
                    name = info.get("longName") or info.get("shortName") or code
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
                rev_growth = info.get("revenueGrowth")
                earn_growth = info.get("earningsGrowth")

                recent_news = fetch_recent_news(code, name)

                # アナリストコンセンサス取得
                target_mean = info.get("targetMeanPrice")
                target_high = info.get("targetHighPrice")
                target_low  = info.get("targetLowPrice")
                analysts_count = info.get("numberOfAnalystOpinions")
                
                rec_mean = info.get("recommendationMean")
                if rec_mean:
                    if rec_mean <= 1.5: rec_text = "強気買い"
                    elif rec_mean <= 2.5: rec_text = "買い"
                    elif rec_mean <= 3.5: rec_text = "保有"
                    elif rec_mean <= 4.5: rec_text = "売り"
                    else: rec_text = "強気売り"
                    rec_str = f"{rec_text} (スコア:{rec_mean})"
                else:
                    rec_str = info.get("recommendationKey") or "データなし"

                beta = info.get("beta")
                w52_high = info.get("fiftyTwoWeekHigh")
                w52_low = info.get("fiftyTwoWeekLow")

                analyst_text = ""
                if target_mean and target_mean > 0:
                    analyst_text = (
                        f"【機関コンセンサス】平均目標: {format_currency(target_mean)}円 "
                        f"(高値: {format_currency(target_high)}円 / 安値: {format_currency(target_low)}円)\n"
                        f"　推奨: {rec_str} / アナリスト数: {analysts_count}名\n"
                        f"【指標・リスク】ベータ値(市場連動): {beta} / 52週高値: {format_currency(w52_high)}円 / 52週安値: {format_currency(w52_low)}円"
                    )
                else:
                    analyst_text = f"【機関コンセンサス】データなし\n【指標・リスク】ベータ値: {beta} / 52週高値: {format_currency(w52_high)}円 / 52週安値: {format_currency(w52_low)}円"

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
                
                funda_text = (
                    f"【ファンダメンタル】PER: {f'{per:.1f}' if per else '---'} / PBR: {f'{pbr:.2f}' if pbr else '---'} / 配当利回り: {f'{div_yield:.2f}' if div_yield else '---'}%\n"
                    f"　売上成長率: {f'{rev_growth*100:.1f}%' if rev_growth else '---'} / 利益成長率: {f'{earn_growth*100:.1f}%' if earn_growth else '---'}"
                )

                technical_context[code] = f"{tech_text}\n{funda_text}\n{analyst_text}\n{pnl_text}\n【ニュース】{recent_news}"

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
        role_prompt = f"""あなたはプロの証券アナリストです。本日は日本市場の寄り付き前（朝）です。
前日の米国市場や為替動向、各銘柄の最新状況から、本日の寄り付き直後に取るべき「即時アクション（利確・損切り指値・追加購入の可否）」に特化した指示を作成してください。
【市場指標】
{market_str}
特に本日意識すべき損切り指値水準や、ナンピン買いの禁止・制限を明確にトレーダーマニュアル形式で作成してください。"""
    elif timing == "昼":
        role_prompt = f"""あなたはプロの証券アナリストです。現在は昼休み（前場大引け後・後場寄り付き前）です。
前場の株価変動や出来高の推移、為替の急変動を確認し、後場に向けた「即時アクション（前場の安値割れに伴う損切り注文の準備など）」を提示してください。
【現在の市場指標】
{market_str}
前場に損切り目安や節目の価格にどこまで接近したか、後場の開始時にどの価格で売買注文を実行すべきかを指示してください。"""
    else:
        role_prompt = f"""あなたはプロの証券アナリストです。本日は大引け後（夜）です。
本日の最終値動き、夜間PTS、および本日発表されたマクロニュースや競合他社の動向を多角的に分析し、中長期的なアロケーション方針と将来ロードマップを構築してください。
【現在の市場指標】
{market_str}
過去のチャートパターンアノマリーとの類似性分析、およびセクター内の競合他社（ホンダ、日産、テスラ、任天堂、キーエンス等の具体名）との相関分析を必ず絶対参照（名指し）で行ってください。"""

    prompt = f"""{role_prompt}
{prev_context}

以下の保有銘柄データから、ポートフォリオ全体をスキャンした詳細な投資戦略レポートをJSON形式のみで作成してください。Markdownは不要。
専門的なアナリストとして、テクニカル・ファンダメンタル両面から徹底分析してください。
目標株価、推奨度、損切りラインなどはAIで独自算出せず、データ内にある「機関コンセンサス」「52週安値」等の客観的な指標を優先して使用し、事実情報に基づいた分析をしてください。
重要なルール：必ず全ての出力を自然な日本語で行うこと（英語の見出しや格付けは一切混ぜず、完全に日本語化してください）。

【重要指示：テキストの装飾】
分析テキスト（特に `valuation_commentary` や `momentum_analysis_list`, `chart_analogy_commentary`, `news_correlation_commentary`）の文中において、重要なキーワードやシグナルに対して、以下のHTMLタグを積極的に埋め込んで装飾してください：
- 黄色蛍光ペン: `<span class="highlight-marker-yellow">重要単語</span>`
- 緑色蛍光ペン（好材料・割安等）: `<span class="highlight-marker-green">好材料・目標</span>`
- 赤色蛍光ペン（悪材料・損切等）: `<span class="highlight-marker-red">リスク・損切り</span>`
- ポジティブカラー太字: `<span style="color: var(--color-positive); font-weight: 700;">ポジティブ内容</span>`
- ネガティブカラー太字: `<span style="color: var(--color-negative); font-weight: 700;">ネガティブ内容</span>`

【保有銘柄データ】
{stocks_prompt_text}

【出力形式】必ず次のJSON構造のみを返すこと。
{{
  "title": "{timing}のポートフォリオ投資戦略・日報",
  "statusColor": "#b91c1c",
  "alerts": ["🚨 A社が52週安値接近", "💡 B社に好材料"],
  "market_summary": "市場全体の概況・地合いを400字程度で解説。適宜HTMLハイライトタグを埋め込んでください。",
  "tomorrow_outlook": "明日の見通しを200字程度で。適宜HTMLハイライトタグを埋め込んでください。",
  "stocks": [{{
    "name": "銘柄名",
    "code": "コード",
    "price": "現在値（前日比%）",
    "sentiment": "ポジティブ/ネガティブ/ニュートラル",
    "sentiment_reason": "感情判定の根拠",
    "analyst_rating": "総合投資判断（必ず「維持 (HOLD)」「買い増し (BUY)」「売り (SELL)」のいずれかから選択）",
    "consensus_target": 0,
    "target_divergence_comment": "機関平均目標と現在値の乖離に対する見解",
    "stop_loss_guide": 0,
    "risk_comment": "ベータ値や直近のボラティリティを踏まえた客観的なリスク解説",
    "technical_detail": "RSI・MACD・BB・SMAを使った詳細テクニカル解説",
    "news_impact": "直近ニュースの影響評価",
    "personal_action": "保有数と取得単価(含み損益)を加味した個人へのアクション提案",
    "comprehensive_analysis": "PERなどのファンダメンタル指標、現在値と目標株価の乖離、テクニカル指標、および関連ニュースを総合し、AIアナリストとしての見解・意見を400〜600字程度の詳細なテキストで記述してください。",
    "one_liner": "LINEに送る超短い一言コメント（20字以内）",
    "execution_manual": {{
      "scenario_a": "日足終値がロスカット目安を割り込んだ場合の具体的執行指示（100-150字、HTMLタグ含む）",
      "scenario_b": "場中の一時的節目割れや反発時の具体的執行指示（100-150字、HTMLタグ含む）",
      "scenario_c": "指値・逆指値の具体的設定指示（100-150字、HTMLタグ含む）"
    }},
    "valuation_rationale": {{
      "technical": "テクニカル面の判定（「🟡 維持 (反発待ち)」「🟢 買い増し (トレンド追従)」「🔴 売り (悪化警戒)」など）とその短い分析理由（30字以内）",
      "valuation": "バリュエーション面の判定（「🟢 買い増し (超割安)」「🟡 維持 (適正価値)」「🔴 売り (割高)」など）とその短い分析理由（30字以内）",
      "macro_news": "ニュース・マクロ面の判定（「🔴 売り (悪化警戒)」「🟢 買い増し (好材料発生)」「🟡 維持 (中立)」など）とその短い分析理由（30字以内）"
    }},
    "valuation_commentary": "財務×テクニカルの複合分析に関する200-300字程度の解説。HTML強調タグ（highlight-marker-*など）や文字色スタイルを適切に埋め込んでください。",
    "momentum_analysis_list": [
      "出来高の変化に関する具体的な分析（出来高急増、セリングクライマックス等を50-70字で。HTMLタグ含む）",
      "RSIの推移と買われすぎ・売られすぎの判定（50-70字で。HTMLタグ含む）",
      "ボリバン幅の拡大・縮小とトレンドの強さ（50-70字で。HTMLタグ含む）"
    ],
    "broker_targets": [
      {{"broker": "野村證券", "target": 3400, "rating": "買い (継続)", "date": "2026/06/15"}},
      {{"broker": "大和証券", "target": 3250, "rating": "強気 (継続)", "date": "2026/06/28"}},
      {{"broker": "ゴールドマン・サックス", "target": 3100, "rating": "中立 (継続)", "date": "2026/07/02"}},
      {{"broker": "JPモルガン証券", "target": 2950, "rating": "中立 (継続)", "date": "2026/07/08"}}
    ],
    "broker_commentary": "主要証券会社の目標株価コンセンサスに対する200字程度のアナリスト分析。SOTPモデルなどの算出根拠や目標引き下げリスクを含め、HTML強調タグやカラータグを適切に埋め込んでください。",
    "chart_analogy_commentary": "過去の特定の年月日におけるチャート類似パターンとの類似度（％）や当時の底打ち・高値ブレイク推移、今回の優位性・アノマリーに関する200-300字程度のテクニカル分析。HTML強調タグやカラータグを適切に埋め込んでください。",
    "news_correlation_commentary": "本日発表されたマクロニュース（金利、為替など）およびセクター競合銘柄（対象銘柄の具体的な競合他社名とコード）との相関・値動きの影響に関する200-300字程度の解説（絶対参照）。HTML強調タグやカラータグを適切に埋め込んでください。",
    "risk_catalyst_profile": {{
      "earnings_date": "次の決算発表予定日（YYYY/MM/DD）",
      "max_loss_var": "1日最大想定損失額の推計値と前提条件（例：-¥114,000円）",
      "beta": "ベータ値（例：1.28）",
      "target_timeline": "目標株価到達の想定期間（例：3ヶ月以内、6ヶ月以内など）"
    }}
  }}],
  "analysis_market": "市場環境の詳細分析（400〜600字程度で詳細に。適宜HTMLハイライトタグを埋め込んでください。）",
  "analysis_technical": "テクニカル総合評価・セクターローテーション・特筆すべきパターン（400〜600字程度で詳細に。適宜HTMLハイライトタグを埋め込んでください。）",
  "analysis_portfolio": "ポートフォリオ全体のバランス・将来見通しロードマップ・マイルストーン（X月後半のA社底打ちロード、Y月前半のB社上値ブレイクロードなどタイムラインに沿って400字程度で詳細に記述。適宜HTMLハイライトタグを埋め込んでください。）",
  "strategy_short": "今日〜今週の短期アクションプラン（300字程度で詳細に。適宜HTMLハイライトタグを埋め込んでください。）",
  "strategy_mid": "1〜3ヶ月の中期戦略・注目イベント（300字程度で詳細に。適宜HTMLハイライトタグを埋め込んでください。）"
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
# LINE 送信（超ミニマル版 — 重要情報のみ）
# 詳細はダッシュボードで確認できるため、LINEは通知として機能する最小限に絞る
# ========================

import re

def strip_html(text):
    if not text:
        return ""
    return re.sub(r'<[^>]+>', '', text)

def send_to_line(data, today_str=None, dashboard_url=""):
    if not data:
        return
    url = "https://api.line.me/v2/bot/message/push"

    s_emoji = {"ポジティブ": "📈", "ネガティブ": "📉", "ニュートラル": "➡️"}
    r_color = {
        "強気買い": "#15803d", "買い増し": "#16a34a",
        "保有": "#475569", "一部利確": "#b45309",
        "利確": "#ea580c", "売却": "#b91c1c",
    }

    alert_contents = []
    for a in data.get("alerts", [])[:2]:
        clean_alert = strip_html(a)
        alert_contents.append({
            "type": "text", "text": f"⚠️ {clean_alert}",
            "size": "sm", "wrap": True, "color": "#fca5a5", "weight": "bold",
        })

    stock_rows = []
    for s in data.get("stocks", []):
        emoji  = s_emoji.get(s.get("sentiment", "ニュートラル"), "➡️")
        rec    = s.get("analyst_rating", "データなし").split(" ")[0]
        c      = r_color.get(rec, "#94a3b8")
        liner  = strip_html(s.get("one_liner") or "")
        code   = s.get("code", "")
        name   = s.get("name", "")
        price  = s.get("price", "")

        stock_rows.append({
            "type": "box", "layout": "vertical", "margin": "md",
            "contents": [
                {
                    "type": "box", "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": f"{emoji} {code} {name}", "size": "sm", "weight": "bold", "color": "#e2e8f0", "flex": 7},
                        {"type": "text", "text": f"[{rec}]", "size": "xs", "color": c, "align": "end", "flex": 3, "weight": "bold"}
                    ]
                },
                {"type": "text", "text": f"価格: {price}", "size": "xs", "color": "#94a3b8", "margin": "xs"},
                {"type": "text", "text": liner, "size": "xs", "color": "#cbd5e1", "wrap": True, "margin": "xs"}
            ]
        })

    strategy_short = strip_html(data.get("strategy_short") or "")[:80]
    if len(strip_html(data.get("strategy_short") or "")) > 80:
        strategy_short += "…"

    body_contents = []
    if alert_contents:
        body_contents.append({
            "type": "box", "layout": "vertical",
            "backgroundColor": "#2a0a0a", "paddingAll": "md", "cornerRadius": "sm",
            "contents": alert_contents,
        })
        body_contents.append({"type": "separator", "margin": "md"})

    if stock_rows:
        body_contents.extend(stock_rows)
        body_contents.append({"type": "separator", "margin": "md"})

    body_contents.append({
        "type": "text",
        "text": f"📌 アクションプラン:\n{strategy_short}",
        "size": "sm", "wrap": True, "color": "#a5b4fc", "margin": "md",
    })

    footer_contents = []
    if dashboard_url:
        footer_contents.append({
            "type": "button",
            "action": {"type": "uri", "label": "📊 ダッシュボードを開く", "uri": dashboard_url},
            "style": "primary", "color": "#1d4ed8", "height": "sm",
        })

    bubble = {
        "type": "bubble", "size": "mega",
        "header": {
            "type": "box", "layout": "vertical",
            "backgroundColor": "#0f172a", "paddingAll": "md",
            "contents": [
                {"type": "text", "text": strip_html(data.get("title", "レポート")),
                 "weight": "bold", "color": "#f1f5f9", "size": "md", "wrap": True},
            ],
        },
        "body": {
            "type": "box", "layout": "vertical",
            "spacing": "sm", "paddingAll": "md",
            "backgroundColor": "#1e293b",
            "contents": body_contents,
        },
    }
    if footer_contents:
        bubble["footer"] = {
            "type": "box", "layout": "vertical", "paddingAll": "md",
            "backgroundColor": "#1e293b",
            "contents": footer_contents,
        }

    alt_text = strip_html(data.get("title", "アナリストレポート"))
    if data.get("alerts"):
        alt_text += " " + strip_html(data["alerts"][0])[:30]

    flex_message = {
        "to": LINE_USER_ID,
        "messages": [{
            "type": "flex",
            "altText": alt_text,
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
    timing       = get_current_timing()
    today_str    = datetime.now(JST).strftime("%Y-%m-%d")
    now_jst      = datetime.now(JST)

    # 自動実行（スケジュール / API自動キック）かつ土日の場合はスキップ
    # 手動実行（workflow_dispatch）やローカル実行の場合は土日でも実行する
    github_event = os.environ.get("GITHUB_EVENT_NAME", "")
    is_automated = github_event in ("schedule", "repository_dispatch")
    if is_automated and now_jst.weekday() >= 5:
        print(f"=== [自動実行スキップ] {today_str} ({now_jst.strftime('%A')}) は土日のため、処理を実行せず早期終了します。 ===")
        import sys
        sys.exit(0)

    spreadsheet = get_spreadsheet()
    sheet       = spreadsheet.worksheet("保有銘柄")
    initialize_headers(sheet)

    dashboard_url = f"{GITHUB_PAGES_URL}?t={int(datetime.now().timestamp())}" if GITHUB_PAGES_URL else ""
    print(f"=== 実行開始: {today_str} {timing} (モデル: {GEMINI_MODEL}) ===")

    tech_context = update_stock_data(sheet)
    market_data  = get_market_indicators()
    report       = generate_analysis_report(sheet, spreadsheet, timing, tech_context, market_data)

    if report:
        send_to_line(report, today_str, dashboard_url=dashboard_url)
        # generate_charts.py / history.py 用にレポートを一時保存
        with open(LAST_REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump({"report": report, "timing": timing, "date": today_str}, f, ensure_ascii=False)
        print(f"【完了】レポートを {LAST_REPORT_FILE} に保存")

    print("=== 実行完了 ===")