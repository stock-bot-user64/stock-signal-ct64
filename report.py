"""判定結果を埋め込んだ1ファイル完結の HTML（output/dashboard.html）を生成する"""
from __future__ import annotations

import json

import common


def state() -> dict:
    return {
        "tickers": common.load_tickers(),
        "latest": common.load_latest(),
        "backtest": common.load_backtest_index(),
    }


def build(out=None) -> str:
    out = out or (common.OUTPUT_DIR / "dashboard.html")
    tpl = (common.BASE / "web" / "dashboard.html").read_text(encoding="utf-8")
    data = json.dumps(state(), ensure_ascii=False).replace("</", "<\\/")
    html = tpl.replace("/*__DATA__*/null", data, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return str(out)


if __name__ == "__main__":
    print(build())
