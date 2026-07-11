"""
alert.py — 価格急変・出来高急増アラート
★ Gemini API 一切不使用 ★
★ 全アラートを LINE 1通にまとめて送信（LINE無料枠を節約）★
"""
import os
import json
import time
from datetime import datetime, timedelta, timezone
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials
import requests
from dotenv import load_dotenv

load_dotenv()

LINE_ACCESS_TOKEN       = os.environ.get("LINE_ACCESS_TOKEN")
LINE_USER_ID            = os.environ.get("LINE_USER_ID")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
SPREADSHEET_KEY         = "1-bql8g-s0JcEzy4neAzSaM9cU0dGZQ5eYhhc6cTuwF0"

PRICE_ALERT_THRESHOLD   = 5.0   # ±5% 以上で価格急変アラート
VOLUME_SPIKE_MULTIPLIER = 2.0   # 直近5日平均の 2倍以上で出来高急増アラート

JST = timezone(timedelta(hours=9))

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

def _get_or_create_alert_sheet(spreadsheet):
    try:
        return spreadsheet.worksheet("アラート履歴")
    except Exception:
        sheet = spreadsheet.add_worksheet(title="アラート履歴", rows=10000, cols=5)
        sheet.update(range_name="A1:E1", values=[["日付", "時刻", "銘柄コード", "銘柄名", "アラート内容"]])
        return sheet

# ========================
# アラートチェック（Gemini 不使用 — 純粋な数値判定）
# ========================

def check_alerts(sheet):
    """
    スプレッドシートの保有銘柄に対して以下を確認:
      1. 前日比 ±PRICE_ALERT_THRESHOLD% 以上の価格急変
      2. 出来高が直近5日平均の VOLUME_SPIKE_MULTIPLIER 倍以上
    """
    records = sheet.get_all_values()
    alerts  = []

    for row in records[1:]:
        if not row or not row[0].strip():
            continue
        code = row[0].strip()
        name = row[1] if len(row) > 1 else code

        try:
            ticker = yf.Ticker(f"{code}.T")
            hist   = ticker.history(period="10d")

            if hist.empty or len(hist) < 2:
                continue

            current_price = float(hist['Close'].iloc[-1])
            prev_close    = float(hist['Close'].iloc[-2])
            if prev_close == 0:
                continue

            change_pct = (current_price - prev_close) / prev_close * 100

            # --- 価格急変チェック ---
            if abs(change_pct) >= PRICE_ALERT_THRESHOLD:
                emoji     = "📈🚨" if change_pct > 0 else "📉🚨"
                direction = "急騰" if change_pct > 0 else "急落"
                alerts.append({
                    "code": code, "name": name, "type": "price",
                    "message": f"{emoji} {name}({code}) {direction}: {change_pct:+.2f}% ({current_price:,.0f}円)",
                })

            # --- 出来高急増チェック ---
            if len(hist) >= 6:
                today_vol = int(hist['Volume'].iloc[-1])
                avg_5d    = float(hist['Volume'].iloc[-6:-1].mean())
                if avg_5d > 0 and today_vol >= avg_5d * VOLUME_SPIKE_MULTIPLIER:
                    ratio = today_vol / avg_5d
                    alerts.append({
                        "code": code, "name": name, "type": "volume",
                        "message": f"📊 {name}({code}) 出来高急増: {ratio:.1f}倍 ({today_vol:,}株)",
                    })

            time.sleep(0.5)
        except Exception as e:
            print(f"[エラー] {code} のアラートチェック失敗: {e}")

    return alerts

# ========================
# LINE 送信（全アラートを 1通にまとめる）
# ========================

def send_alert_to_line(alerts):
    """
    ★ LINE 無料枠節約のため全アラートを 1通にまとめて送信 ★
    アラートがなければ呼び出さない
    """
    url      = "https://api.line.me/v2/bot/message/push"
    now_str  = datetime.now(JST).strftime("%H:%M")

    alert_contents = []
    for a in alerts:
        color = "#b91c1c" if a["type"] == "price" else "#92400e"
        alert_contents.append({
            "type": "text",
            "text": a["message"],
            "size": "sm",
            "wrap": True,
            "color": color,
        })

    flex_message = {
        "to": LINE_USER_ID,
        "messages": [{
            "type": "flex",
            "altText": f"⚠️ 株価アラート ({len(alerts)}件)",
            "contents": {
                "type": "bubble",
                "header": {
                    "type": "box", "layout": "vertical", "backgroundColor": "#7f1d1d",
                    "contents": [
                        {"type": "text", "text": "⚠️ 株価アラート", "weight": "bold", "color": "#ffffff", "size": "md"},
                        {"type": "text", "text": f"{now_str} 検知 / {len(alerts)}件", "color": "#fca5a5", "size": "xs", "margin": "sm"},
                    ],
                },
                "body": {
                    "type": "box", "layout": "vertical", "spacing": "sm",
                    "contents": alert_contents,
                },
            },
        }],
    }

    try:
        res = requests.post(
            url,
            headers={"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"},
            json=flex_message,
        )
        print(f"アラート送信完了: ステータス {res.status_code}")
        if res.status_code != 200:
            print(f"[警告] LINE APIレスポンス: {res.text[:200]}")
    except Exception as e:
        print(f"アラート送信エラー: {e}")

# ========================
# アラート履歴をスプレッドシートに保存
# ========================

def save_alert_history(alert_sheet, today_str, alerts):
    try:
        values   = alert_sheet.get_all_values()
        next_row = len(values) + 1
        now_str  = datetime.now(JST).strftime("%H:%M")
        rows     = [[today_str, now_str, a["code"], a["name"], a["message"]] for a in alerts]
        if rows:
            end_row = next_row + len(rows) - 1
            alert_sheet.update(range_name=f"A{next_row}:E{end_row}", values=rows)
    except Exception as e:
        print(f"[警告] アラート履歴保存エラー: {e}")

# ========================
# メイン処理
# ========================

if __name__ == "__main__":
    today_str = datetime.now(JST).strftime("%Y-%m-%d")

    spreadsheet  = get_spreadsheet()
    sheet        = spreadsheet.worksheet("保有銘柄")
    alert_sheet  = _get_or_create_alert_sheet(spreadsheet)

    alerts = check_alerts(sheet)

    if alerts:
        print(f"アラート検知: {len(alerts)}件")
        for a in alerts:
            print(f"  - {a['message']}")
        send_alert_to_line(alerts)          # 全アラートを 1通で送信
        save_alert_history(alert_sheet, today_str, alerts)
    else:
        print("アラート条件に該当する銘柄なし — LINE送信なし")
