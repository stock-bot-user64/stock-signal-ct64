"""
設定・銘柄リスト・履歴データの読み書き（全スクリプト共通）

銘柄リストはここ1か所（config/tickers.json）で管理します。
旧コードでは Stockmain.py / StockmainV1.py / backtest_SAv1 にそれぞれ
リストが書かれていたため、追加・削除のたびに複数ファイルの修正が必要でした。
"""
from __future__ import annotations

import json
import os
import re
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
CONFIG_DIR = BASE / "config"
DATA_DIR = BASE / "data"
OUTPUT_DIR = BASE / "output"
TICKERS_FILE = CONFIG_DIR / "tickers.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
HISTORY_FILE = DATA_DIR / "history.csv"
LATEST_FILE = DATA_DIR / "latest.json"
BACKTEST_FILE = DATA_DIR / "backtest_summary.csv"

_lock = threading.Lock()

DEFAULT_SETTINGS = {
    "history_period": "2y",           # 指標計算に使う期間（75日線に十分な長さ）
    "notify_decisions": ["STRONG BUY", "BUY", "SELL", "STRONG SELL"],
    "spreadsheet_key": "",
    "sheet_name": "Daily",
    "credentials_file": "credentials.json",
    "chart_days": 90,                 # ダッシュボードに描く日数
}


# ------------------------------------------------------------------ .env
def load_dotenv(path: Path = BASE / ".env") -> None:
    """依存ライブラリなしで .env を読み込む（既存の環境変数を優先）"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    if os.getenv("SPREADSHEET_KEY"):  # GitHub の Secrets などから上書き
        s["spreadsheet_key"] = os.environ["SPREADSHEET_KEY"]
    return s


# --------------------------------------------------------------- 銘柄リスト
CODE_RE = re.compile(r"^[0-9A-Z]{4}$")


def normalize_code(raw: str) -> str:
    """'7203' / '７２０３' / '7203.t' / '130a' → '7203.T' / '130A.T'。指数(^N225)等はそのまま"""
    code = unicodedata.normalize("NFKC", raw or "").strip().upper()
    if CODE_RE.match(code):
        code += ".T"
    return code


def load_tickers(enabled_only: bool = False) -> list[dict]:
    if not TICKERS_FILE.exists():
        return []
    try:
        items = json.loads(TICKERS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"config/tickers.json の書き方に誤りがあります（{e.lineno}行目付近）。"
                         "カンマや \" の抜けを確認してください") from None
    if enabled_only:
        items = [t for t in items if t.get("enabled", True)]
    return items


def save_tickers(items: list[dict]) -> None:
    with _lock:
        TICKERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = TICKERS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(TICKERS_FILE)


def ticker_name(code: str) -> str:
    for t in load_tickers():
        if t["code"] == code:
            return t.get("name") or code
    return code


# ----------------------------------------------------------------- 履歴
HISTORY_COLS = ["date", "code", "name", "close", "change_pct", "score",
                "decision", "patterns", "rsi", "run_at", "intraday"]


def load_history() -> pd.DataFrame:
    if not HISTORY_FILE.exists():
        return pd.DataFrame(columns=HISTORY_COLS)
    return pd.read_csv(HISTORY_FILE, dtype={"code": str, "date": str}).fillna({"patterns": ""})


def upsert_history(rows: list[dict]) -> pd.DataFrame:
    """同じ (日付, 銘柄) は上書き。1日に何度実行しても重複しない"""
    with _lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        new = pd.DataFrame(rows, columns=HISTORY_COLS)
        hist = pd.concat([load_history(), new], ignore_index=True)
        hist = hist.drop_duplicates(["date", "code"], keep="last").sort_values(["date", "code"])
        hist.to_csv(HISTORY_FILE, index=False, encoding="utf-8-sig")
        return hist


def load_latest() -> dict:
    if LATEST_FILE.exists():
        return json.loads(LATEST_FILE.read_text(encoding="utf-8"))
    return {"generated_at": None, "results": [], "errors": []}


def save_latest(payload: dict) -> None:
    with _lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        LATEST_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------ バックテスト
def load_backtest_index() -> dict:
    """銘柄ごとの BUY/STRONG BUY 実績（backtest.py の出力）を {code: [...]} で返す"""
    if not BACKTEST_FILE.exists():
        return {}
    df = pd.read_csv(BACKTEST_FILE, encoding="utf-8-sig")
    df.columns = [c.strip().lstrip("﻿") for c in df.columns]
    out: dict[str, list] = {}
    for r in df.to_dict("records"):
        out.setdefault(r["Ticker"], []).append({
            "threshold": float(r["Score_Threshold"]),
            "hold": int(r["Holding_Period"]),
            "trades": int(r["Total_Trades"]),
            "win_rate": round(float(r["Win_Rate (%)"]), 1),
            "avg_ret": round(float(r["Avg_Profit_Rate"]) * 100, 2),
            "pnl": None if pd.isna(r.get("Total_PnL_Yen")) else float(r["Total_PnL_Yen"]),
            "avg_pnl": None if pd.isna(r.get("Avg_PnL_Yen")) else float(r["Avg_PnL_Yen"]),
        })
    return out


JST = timezone(timedelta(hours=9))


def is_intraday(bar_date) -> bool:
    """最新の足が今日の日付で、まだ大引け(15:30)前なら場中＝暫定"""
    now = datetime.now(JST)
    return bar_date == now.date() and (now.hour, now.minute) < (15, 30)


def now_str() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M")
