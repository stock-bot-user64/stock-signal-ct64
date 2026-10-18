"""
スマホ版サイト（site/ フォルダ）を生成する

  python mobile.py

site/ の中身
- index.html, sw.js, manifest.webmanifest, icon-*.png … スマホ用アプリ本体（web/mobile からコピー）
- data.json  … 最新の判定・直近の履歴・バックテスト結果
- pc.html    … PC 版ダッシュボード（閲覧専用）

GitHub Actions がこのフォルダを GitHub Pages に公開します。
手元で確認するときは:  python -m http.server -d site 8000  →  http://localhost:8000
"""
from __future__ import annotations

import json
import shutil

import pandas as pd

import common
import report

SITE = common.BASE / "site"
HISTORY_DAYS = 40  # スマホに載せる履歴の営業日数


def _csv(path):
    if not path.exists():
        return None
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = [str(c).strip() for c in df.columns]
    return json.loads(df.to_json(orient="records", force_ascii=False))


def _history():
    h = common.load_history()
    if h.empty:
        return []
    dates = sorted(h["date"].unique())[-HISTORY_DAYS:]
    h = h[h["date"].isin(dates)].copy()
    if "intraday" not in h.columns:
        h["intraday"] = False
    h["intraday"] = h["intraday"].fillna(False).astype(str).str.lower().isin(["true", "1"])
    cols = ["date", "code", "name", "close", "change_pct", "score", "decision", "intraday"]
    return json.loads(h[cols].to_json(orient="records", force_ascii=False))


def data() -> dict:
    meta_file = common.DATA_DIR / "backtest_meta.json"
    return report.state() | {
        "history": _history(),
        "bt_rules": _csv(common.DATA_DIR / "backtest_by_rule.csv"),
        "bt_monthly": _csv(common.DATA_DIR / "backtest_monthly.csv"),
        "bt_meta": json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else None,
        "paper": __import__("paper").load() | {"rules": common.load_settings().get("paper_rules", [])},
    }


def build(out=SITE) -> str:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(common.BASE / "web" / "mobile", out)
    (out / "data.json").write_text(json.dumps(data(), ensure_ascii=False), encoding="utf-8")
    report.build(out / "pc.html")
    (out / ".nojekyll").write_text("")
    return str(out)


if __name__ == "__main__":
    print("出力:", build())
