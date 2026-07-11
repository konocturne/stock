"""
history.py — AIレポートをスプレッドシートの「履歴」シートに追記
main.py が生成した last_report.json を読み込んで保存する
"""
import os
import sys
import json
from datetime import datetime, timedelta, timezone
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
SPREADSHEET_KEY         = "1-bql8g-s0JcEzy4neAzSaM9cU0dGZQ5eYhhc6cTuwF0"
LAST_REPORT_FILE        = os.environ.get("LAST_REPORT_FILE", "last_report.json")

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

def _get_or_create_history_sheet(spreadsheet):
    try:
        return spreadsheet.worksheet("履歴")
    except Exception:
        headers = ["日付", "時間帯", "タイムスタンプ", "アラート", "天気", "ベンチマーク", "アクションプラン"]
        sheet   = spreadsheet.add_worksheet(title="履歴", rows=10000, cols=len(headers))
        sheet.update(range_name="A1:G1", values=[headers])
        return sheet

# ========================
# 履歴保存
# ========================

def save_to_history(spreadsheet, report: dict, timing: str, date_str: str):
    history_sheet = _get_or_create_history_sheet(spreadsheet)

    ts_str     = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    alerts_str = " / ".join(report.get("alerts", []))

    row_data = [
        date_str,
        timing,
        ts_str,
        alerts_str,
        report.get("weather", ""),
        report.get("benchmark", ""),
        report.get("strategy_content", "")[:500],  # 500字上限
    ]

    values   = history_sheet.get_all_values()
    next_row = len(values) + 1
    history_sheet.update(range_name=f"A{next_row}:G{next_row}", values=[row_data])
    print(f"【履歴】スプレッドシートに保存完了 (行{next_row}): {date_str} {timing}")

# ========================
# メイン処理
# ========================

if __name__ == "__main__":
    if not os.path.exists(LAST_REPORT_FILE):
        print(f"[スキップ] レポートファイルが見つかりません: {LAST_REPORT_FILE}")
        sys.exit(0)  # エラーでもワークフローを止めない

    try:
        with open(LAST_REPORT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        report   = data.get("report", {})
        timing   = data.get("timing", os.environ.get("REPORT_TIMING", "朝"))
        date_str = data.get("date", datetime.now(JST).strftime("%Y-%m-%d"))

        if not report:
            print("[スキップ] レポートデータが空です")
            sys.exit(0)

        spreadsheet = get_spreadsheet()
        save_to_history(spreadsheet, report, timing, date_str)
    except Exception as e:
        print(f"[エラー] 履歴保存失敗 (ワークフローは継続): {e}")
        sys.exit(0)  # エラーでもワークフローを止めない
