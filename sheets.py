"""Google スプレッドシート出力（任意）。1回の実行につき API 呼び出しは数回だけ"""
from __future__ import annotations

from pathlib import Path

HEADER = ["日付", "銘柄コード", "銘柄名", "終値", "前日比(%)", "スコア", "判定", "検出パターン", "RSI", "実行時刻"]


def append_daily(rows: list[dict], settings: dict, base: Path) -> int:
    key = settings.get("spreadsheet_key")
    cred = base / settings.get("credentials_file", "credentials.json")
    if not key or not cred.exists() or not rows:
        return 0
    import gspread  # 使うときだけ import

    client = gspread.service_account(filename=str(cred))
    book = client.open_by_key(key)
    name = settings.get("sheet_name", "Daily")
    try:
        ws = book.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(title=name, rows=1000, cols=len(HEADER))
        ws.append_row(HEADER)
        ws.freeze(rows=1)

    values = [[r["date"], r["code"], r["name"], r["close"], r["change_pct"], r["score"],
               r["decision"], r["patterns"], r["rsi"], r["run_at"]] for r in rows]
    ws.append_rows(values, value_input_option="USER_ENTERED")
    return len(values)
