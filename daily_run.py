"""
毎日の判定バッチ（旧 Stockmain.py + Gmail2MeSA.py の後継）

  python daily_run.py              # 全銘柄を判定 → 履歴保存 → シート → メール → ダッシュボード生成
  python daily_run.py --no-mail    # メールを送らない
  python daily_run.py --codes 7203 6996   # 指定銘柄だけ

東証の大引けは 15:30。当日の確定足で判定するため 16:00 以降の実行を推奨。
"""
from __future__ import annotations

import argparse
import math
import sys
import time
import traceback
from datetime import datetime

import common
from analyzer import StockAnalyzer


def fetch_prices(code: str, period: str, retries: int = 3):
    """Yahoo が一時的にエラーを返すことがあるので数回やり直す"""
    import yfinance as yf
    last_err = None
    for i in range(retries):
        try:
            df = yf.download(code, period=period, interval="1d", auto_adjust=False,
                             progress=False, threads=False)
            if df is not None and len(df):
                return df
        except Exception as e:
            last_err = e
        time.sleep(3 * (i + 1))
    if last_err:
        raise last_err
    return None


def _num(x, nd=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else round(x, nd)


def analyze_one(code: str, name: str, settings: dict, fetch=fetch_prices) -> dict:
    raw = fetch(code, settings["history_period"])
    if raw is None or len(raw) == 0:
        raise RuntimeError("株価データを取得できませんでした（コード誤り・上場廃止の可能性）")
    an = StockAnalyzer(raw)
    df = an.run_all()
    if len(df) < 80:
        raise RuntimeError(f"データが {len(df)} 日分しかなく、75日線を計算できません")

    last, prev = df.iloc[-1], df.iloc[-2]
    last_date = df.index[-1]
    n = settings["chart_days"]
    tail = df.tail(n)

    # 直近のシグナル日（チャート上のマーカー用）
    sig_days = [
        {"d": d.strftime("%Y-%m-%d"), "decision": r["Decision"], "score": _num(r["Score"], 1)}
        for d, r in tail.iterrows() if r["Decision"] != "HOLD"
    ]
    return {
        "code": code,
        "name": name,
        "date": last_date.strftime("%Y-%m-%d"),
        "stale_days": (datetime.now(common.JST).date() - last_date.date()).days,
        "intraday": common.is_intraday(last_date.date()),
        "close": _num(last["Close"], 1),
        "change_pct": _num((last["Close"] / prev["Close"] - 1) * 100),
        "score": _num(last["Score"], 1),
        "decision": last["Decision"],
        "prev_decision": prev["Decision"],
        "patterns": last["Detected_Patterns"],
        "breakdown": an.explain(-1),
        "rsi": _num(last["RSI_14"], 1),
        "sma25_gap": _num((last["Close"] / last["SMA_25"] - 1) * 100),
        "sma75_gap": _num((last["Close"] / last["SMA_75"] - 1) * 100),
        "chart": {
            "d": [d.strftime("%m/%d") for d in tail.index],
            "o": [_num(v, 1) for v in tail["Open"]],
            "h": [_num(v, 1) for v in tail["High"]],
            "l": [_num(v, 1) for v in tail["Low"]],
            "c": [_num(v, 1) for v in tail["Close"]],
            "sma25": [_num(v, 1) for v in tail["SMA_25"]],
            "sma75": [_num(v, 1) for v in tail["SMA_75"]],
            "bbu": [_num(v, 1) for v in tail["BB_Upper"]],
            "bbl": [_num(v, 1) for v in tail["BB_Lower"]],
            "score": [_num(v, 1) for v in tail["Score"]],
        },
        "signals": sig_days,
    }


def run(codes=None, mail=True, sheets=True, log=print, fetch=fetch_prices, paper=False) -> dict:
    common.load_dotenv()
    settings = common.load_settings()
    tickers = common.load_tickers(enabled_only=codes is None)
    if codes:
        wanted = {common.normalize_code(c) for c in codes}
        tickers = [t for t in common.load_tickers() if t["code"] in wanted]
    run_at = common.now_str()

    results, errors = [], []
    for t in tickers:
        log(f"{t['code']} {t.get('name','')} を解析中…")
        try:
            r = analyze_one(t["code"], t.get("name") or t["code"], settings, fetch)
            results.append(r)
            log(f"  → {r['decision']} (スコア {r['score']:+.1f})")
        except Exception as e:  # 1銘柄の失敗で全体を止めない
            errors.append({"code": t["code"], "name": t.get("name", ""), "error": str(e)})
            log(f"  × エラー: {e}")
            traceback.print_exc()

    # すでに記録済みの (日付, 銘柄) … 祝日に実行すると前営業日の結果が再度返るため、
    # 通知とスプレッドシートは「新しい日付の結果」だけを対象にする
    seen = set(zip(*[common.load_history()[c].astype(str) for c in ("date", "code")]))
    fresh = [r for r in results if (r["date"], r["code"]) not in seen]

    # 履歴（同日同銘柄は上書き）
    hist_rows = [{k: r[k] for k in ("date", "code", "name", "close", "change_pct",
                                    "score", "decision", "patterns", "rsi", "intraday")} | {"run_at": run_at}
                 for r in results]
    if hist_rows:
        common.upsert_history(hist_rows)

    # latest.json（部分実行のときは既存結果とマージ）
    if not results and errors:
        # 全銘柄失敗（Yahoo 側の障害など）のときは前回の結果を消さずにエラーだけ記録
        prev = common.load_latest()
        prev["errors"] = errors
        prev["failed_at"] = run_at
        common.save_latest(prev)
        log("すべての銘柄で取得に失敗しました。前回の結果を残します")
        return prev | {"all_failed": True}

    latest = common.load_latest() if codes else {"results": []}
    merged = {r["code"]: r for r in latest.get("results", [])}
    merged.update({r["code"]: r for r in results})
    active = {t["code"] for t in common.load_tickers()}
    payload = {
        "generated_at": run_at,
        "intraday": any(r.get("intraday") for r in merged.values()),
        "results": [r for c, r in merged.items() if c in active],
        "errors": errors,
    }
    common.save_latest(payload)

    if sheets:
        try:
            fresh_codes = {(r["date"], r["code"]) for r in fresh}
            rows = [h for h in hist_rows if (h["date"], h["code"]) in fresh_codes]
            n = __import__("sheets").append_daily(rows, settings, common.BASE)
            if n:
                log(f"スプレッドシートに {n} 行追記しました")
        except Exception as e:
            log(f"スプレッドシート書き込み失敗: {e}")

    signals = [r for r in fresh if r["decision"] in settings["notify_decisions"]]
    if mail and len(fresh) < len(results):
        log(f"{len(results) - len(fresh)} 銘柄は記録済みの日付のため通知・シート追記を省略")
    if mail and signals:
        import notify
        if notify.mail_configured():
            try:
                notify.send_digest(signals, results[0]["date"])
                log(f"シグナル {len(signals)} 件をメール送信しました")
            except Exception as e:
                log(f"メール送信失敗: {e}")
        else:
            log("メール設定（GMAIL_USER 等）が無いため送信をスキップ")

    if paper and codes is None:
        try:
            __import__("paper").update(results, settings, log=log)
        except Exception as e:
            log(f"紙上トレードの更新に失敗: {e}")
            traceback.print_exc()

    import report
    path = report.build()
    log(f"ダッシュボードを出力: {path}")
    return payload


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", nargs="*", help="指定銘柄だけ実行（例: 7203 6996）")
    ap.add_argument("--no-mail", action="store_true")
    ap.add_argument("--no-sheet", action="store_true")
    ap.add_argument("--paper", action="store_true", help="紙上トレードを記録する（GitHub での定時実行用）")
    a = ap.parse_args()
    out = run(codes=a.codes or None, mail=not a.no_mail, sheets=not a.no_sheet, paper=a.paper)
    if out.get("all_failed"):
        sys.exit(1)  # GitHub Actions では失敗としてメール通知される
