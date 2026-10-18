"""
バックテスト（旧 backtest_SAv1 の後継。銘柄は config/tickers.json から読む）

ルール: シグナル日(スコア>=閾値)の翌営業日始値で買い、N営業日後の終値で売る。
損益は「1回の取引で --shares 株（既定100株＝1単元）買う」として円で計算する。

  python backtest.py --year 2026                 # 2026年のシグナルだけで検証
  python backtest.py --start 2025-01-01          # 期間を指定
  python backtest.py --year 2026 --shares 200 --cost 0.1   # 200株・往復0.1%のコスト
  python backtest.py --overlap                   # 旧版と同じ「ポジション重複あり」で集計

出力（data/ フォルダ）
- backtest_summary.csv        条件ごとの勝率・損益（円）・PF・最大ドローダウン・必要資金
- backtest_monthly.csv        条件ごとの月別損益（円、全銘柄合計）
- backtest_trades_details.csv 1取引ごとの明細
"""
from __future__ import annotations

import argparse
import json
from datetime import date

import pandas as pd

import common
from analyzer import StockAnalyzer


def backtest_one(df_raw, code, thresholds, holds, overlap=False, cost_pct=0.0, shares=100):
    df = StockAnalyzer(df_raw).run_all()
    o, c, s = df["Open"].to_numpy(), df["Close"].to_numpy(), df["Score"].to_numpy()
    trades = []
    for th in thresholds:
        for hold in holds:
            busy_until = -1
            for i in range(len(df) - hold - 1):
                if s[i] < th or (not overlap and i <= busy_until):
                    continue
                entry, exit_ = o[i + 1], c[i + 1 + hold]
                cost_yen = entry * shares * cost_pct / 100
                pnl_yen = (exit_ - entry) * shares - cost_yen
                ret = pnl_yen / (entry * shares)
                trades.append({
                    "Ticker": code, "Signal_Date": df.index[i].date(),
                    "Entry_Date": df.index[i + 1].date(), "Exit_Date": df.index[i + 1 + hold].date(),
                    "Score": s[i], "Score_Threshold": th, "Holding_Period": hold,
                    "Entry_Price": round(entry, 1), "Exit_Price": round(exit_, 1), "Shares": shares,
                    "Capital_Yen": round(entry * shares),
                    "Profit_Yen": round(pnl_yen), "Profit_Rate": ret, "Is_Win": int(pnl_yen > 0),
                })
                busy_until = i + 1 + hold
    return trades


def _max_drawdown(pnl: pd.Series) -> float:
    cum = pnl.cumsum()
    return float((cum.cummax().clip(lower=0) - cum).max()) if len(cum) else 0.0


def _max_concurrent_capital(g: pd.DataFrame) -> float:
    """同時に保有していた資金の最大値（全銘柄合計）＝その条件で運用するのに必要な資金"""
    ev = pd.concat([
        pd.DataFrame({"d": pd.to_datetime(g["Entry_Date"]), "v": g["Capital_Yen"], "k": 1}),
        pd.DataFrame({"d": pd.to_datetime(g["Exit_Date"]), "v": -g["Capital_Yen"], "k": 0}),
    ]).sort_values(["d", "k"])  # 同日は決済を先に処理
    return float(ev["v"].cumsum().max()) if len(ev) else 0.0


def summarize(trades: pd.DataFrame, keys) -> pd.DataFrame:
    rows = []
    for k, g in trades.sort_values("Exit_Date").groupby(keys):
        k = k if isinstance(k, tuple) else (k,)
        win, lose = g[g["Profit_Yen"] > 0], g[g["Profit_Yen"] <= 0]
        gross_loss = -lose["Profit_Yen"].sum()
        rows.append(dict(zip(keys, k)) | {
            "Total_Trades": len(g),
            "Wins": len(win),
            "Win_Rate (%)": len(win) / len(g) * 100,
            "Avg_Profit_Rate": g["Profit_Rate"].mean(),
            "Total_PnL_Yen": g["Profit_Yen"].sum(),
            "Avg_PnL_Yen": g["Profit_Yen"].mean(),
            "Avg_Win_Yen": win["Profit_Yen"].mean() if len(win) else 0,
            "Avg_Loss_Yen": lose["Profit_Yen"].mean() if len(lose) else 0,
            "Max_Loss_Yen": g["Profit_Yen"].min(),
            "Profit_Factor": win["Profit_Yen"].sum() / gross_loss if gross_loss > 0 else None,
            "Max_DD_Yen": _max_drawdown(g["Profit_Yen"]),
            "Max_Capital_Yen": _max_concurrent_capital(g),
        })
    out = pd.DataFrame(rows)
    for col in out.columns:
        if col.endswith("_Yen"):
            out[col] = out[col].round(0)
    out["Win_Rate (%)"] = out["Win_Rate (%)"].round(1)
    out["Profit_Factor"] = out["Profit_Factor"].astype(float).round(2)
    return out


def monthly(trades: pd.DataFrame) -> pd.DataFrame:
    t = trades.copy()
    t["Month"] = pd.to_datetime(t["Exit_Date"]).dt.strftime("%Y-%m")  # 決済した月で計上
    m = t.pivot_table(index=["Score_Threshold", "Holding_Period"], columns="Month",
                      values="Profit_Yen", aggfunc="sum", fill_value=0)
    m["月平均"] = m.mean(axis=1).round(0)
    m = m.reset_index()
    m.insert(0, "条件", [f"スコア≥{t} {h}日保有" for t, h in zip(m["Score_Threshold"], m["Holding_Period"])])
    return m


def yen(v) -> str:
    return "—" if pd.isna(v) else f"{v:+,.0f}円"


def main():
    today = date.today()
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, help="この年のシグナルだけで検証（例: 2026）")
    ap.add_argument("--start", default=str(today.replace(year=today.year - 2)))
    ap.add_argument("--end", default=None)
    ap.add_argument("--thresholds", nargs="*", type=float, default=[2.0, 3.5])
    ap.add_argument("--holds", nargs="*", type=int, default=[3, 5, 10, 25])
    ap.add_argument("--shares", type=int, default=100, help="1回に買う株数（既定100株）")
    ap.add_argument("--overlap", action="store_true", help="旧版と同じく重複ポジションを許可")
    ap.add_argument("--cost", type=float, default=0.0, help="往復コスト(%%) 例: 0.2")
    a = ap.parse_args()
    if a.year:
        a.start, a.end = f"{a.year}-01-01", f"{a.year + 1}-01-01"

    import yfinance as yf
    all_trades = []
    for t in common.load_tickers(enabled_only=True):
        print(f"{t['code']} {t.get('name','')} …")
        # 75日線の助走期間ぶん早めに取得。決済用に終了日の後ろも少し取る
        start = (pd.Timestamp(a.start) - pd.Timedelta(days=150)).date()
        end = (pd.Timestamp(a.end) + pd.Timedelta(days=60)).date() if a.end else None
        raw = yf.download(t["code"], start=str(start), end=str(end) if end else None,
                          auto_adjust=False, progress=False)
        if raw.empty:
            print("  データなし")
            continue
        tr = backtest_one(raw, t["code"], a.thresholds, a.holds, a.overlap, a.cost, a.shares)
        lo, hi = pd.Timestamp(a.start), pd.Timestamp(a.end) if a.end else pd.Timestamp.max
        for x in tr:
            if lo <= pd.Timestamp(x["Signal_Date"]) < hi:
                x["Name"] = t.get("name", "")
                all_trades.append(x)

    if not all_trades:
        print("シグナルが発生しませんでした")
        return
    trades = pd.DataFrame(all_trades)
    by_ticker = summarize(trades, ["Ticker", "Score_Threshold", "Holding_Period"])
    by_rule = summarize(trades, ["Score_Threshold", "Holding_Period"])
    mon = monthly(trades)

    common.DATA_DIR.mkdir(exist_ok=True)
    by_ticker.to_csv(common.BACKTEST_FILE, index=False, encoding="utf-8-sig")
    by_rule.to_csv(common.DATA_DIR / "backtest_by_rule.csv", index=False, encoding="utf-8-sig")
    mon.to_csv(common.DATA_DIR / "backtest_monthly.csv", index=False, encoding="utf-8-sig")
    trades.to_csv(common.DATA_DIR / "backtest_trades_details.csv", index=False, encoding="utf-8-sig")
    (common.DATA_DIR / "backtest_meta.json").write_text(json.dumps({
        "start": a.start, "end": a.end, "shares": a.shares, "cost_pct": a.cost,
        "overlap": a.overlap, "generated_at": common.now_str(),
    }, ensure_ascii=False), encoding="utf-8")

    period = f"{a.start} 〜 {a.end or '現在'}（シグナル日ベース）"
    print(f"\n検証期間: {period} / 1回 {a.shares}株 / 往復コスト {a.cost}%"
          f"{' / 重複あり' if a.overlap else ''}")
    print("※ 期間末のシグナルで保有日数ぶんのデータがまだ無いものは集計に含まれません")

    print("\n== 条件別（全銘柄合計） ==")
    print(f"{'条件':<16}{'取引':>5}{'勝率':>7}{'総損益':>13}{'1回平均':>11}{'PF':>6}{'最大DD':>12}{'必要資金':>13}")
    for r in by_rule.to_dict("records"):
        pf = "—" if pd.isna(r["Profit_Factor"]) else f"{r['Profit_Factor']:.2f}"
        print(f"スコア≥{r['Score_Threshold']:<4} {r['Holding_Period']:>2}日保有"
              f"{r['Total_Trades']:>5}{r['Win_Rate (%)']:>6.1f}%{yen(r['Total_PnL_Yen']):>13}"
              f"{yen(r['Avg_PnL_Yen']):>11}{pf:>6}{r['Max_DD_Yen']:>11,.0f}円{r['Max_Capital_Yen']:>12,.0f}円")

    best = by_ticker[by_ticker["Total_Trades"] >= 5].sort_values("Total_PnL_Yen", ascending=False)
    print("\n== 銘柄×条件 損益上位10（取引5回以上） ==")
    names = trades.drop_duplicates("Ticker").set_index("Ticker")["Name"]
    for r in best.head(10).to_dict("records"):
        print(f"{r['Ticker']} {names.get(r['Ticker'], ''):<10} スコア≥{r['Score_Threshold']} "
              f"{r['Holding_Period']:>2}日 {r['Total_Trades']:>3}回 勝率{r['Win_Rate (%)']:>5.1f}% "
              f"総損益{yen(r['Total_PnL_Yen']):>11}")

    print("\n== 月別損益（全銘柄合計・決済月で計上） ==")
    view = mon.drop(columns=["Score_Threshold", "Holding_Period"]).set_index("条件")
    print((view / 10000).round(1).to_string() + "\n（単位: 万円）")
    print(f"\n保存: {common.DATA_DIR}")


if __name__ == "__main__":
    main()
