"""
紙上トレード（実際のお金を使わない自動売買記録）

判定のたびに呼ばれ、config/settings.json の paper_rules に従って
「シグナルが出たら買い、決めた営業日数が経ったら売る」を記録する。結果は data/paper.json。

- 買い: スコアが閾値以上 かつ そのルールで同じ銘柄を保有していない とき、その時点の株価で買う
        （同じ日に売ったばかりの銘柄は、その日は買い直さない）
- 売り: 買った日の翌営業日から数えて hold_days 営業日目の最初の判定で、その時点の株価で売る
- 当日の株価が取れた銘柄だけが対象（祝日や朝9時台でデータがまだ前日のときは何もしない）
"""
from __future__ import annotations

import json
from datetime import datetime

import common

PAPER_FILE = common.DATA_DIR / "paper.json"


def load() -> dict:
    if PAPER_FILE.exists():
        return json.loads(PAPER_FILE.read_text(encoding="utf-8"))
    return {"positions": [], "closed": []}


def save(book: dict) -> None:
    common.DATA_DIR.mkdir(parents=True, exist_ok=True)
    PAPER_FILE.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")


def _held_days(hist, code: str, entry_date: str) -> int:
    """買った日より後の営業日数（履歴に記録された日付で数える）"""
    h = hist[hist["code"] == code]
    return int((h["date"] > entry_date).sum())


def update(results: list[dict], settings: dict, log=print) -> dict:
    rules = settings.get("paper_rules") or []
    book = load()
    book["rules"] = rules
    if not rules:
        return book

    today = datetime.now(common.JST).strftime("%Y-%m-%d")
    run_at = common.now_str()
    hist = common.load_history()
    live = {r["code"]: r for r in results if r["date"] == today and r.get("close")}

    # 1) 売り
    still_open = []
    for p in book["positions"]:
        rule = next((x for x in rules if x["id"] == p["rule"]), None)
        r = live.get(p["code"])
        if rule and r and _held_days(hist, p["code"], p["entry_date"]) >= rule["hold_days"]:
            pnl = (r["close"] - p["entry_price"]) * p["shares"]
            book["closed"].append(p | {
                "exit_date": today, "exit_at": run_at, "exit_price": r["close"],
                "exit_decision": r["decision"],
                "pnl": round(pnl), "ret": round(r["close"] / p["entry_price"] - 1, 4),
            })
            log(f"[紙上] 売り {p['name']} {r['close']:,} 円 → 損益 {pnl:+,.0f} 円（{rule['name']}）")
        else:
            still_open.append(p)
    book["positions"] = still_open

    # 2) 買い
    for rule in rules:
        for r in live.values():
            if r["score"] is None or r["score"] < rule["threshold"]:
                continue
            if any(p["rule"] == rule["id"] and p["code"] == r["code"] for p in book["positions"]):
                continue
            if any(c["rule"] == rule["id"] and c["code"] == r["code"] and c["exit_date"] == today
                   for c in book["closed"]):
                continue
            book["positions"].append({
                "rule": rule["id"], "code": r["code"], "name": r["name"],
                "entry_date": today, "entry_at": run_at, "entry_price": r["close"],
                "entry_score": r["score"], "entry_decision": r["decision"],
                "shares": int(rule.get("shares", 100)),
                "intraday": bool(r.get("intraday")),
            })
            log(f"[紙上] 買い {r['name']} {r['close']:,} 円 × {rule.get('shares', 100)}株（{rule['name']}）")

    book["updated_at"] = run_at
    save(book)
    return book
