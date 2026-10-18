"""
テクニカル分析エンジン（旧 StockAnalyzer.py の改良版）

主な変更点
- yfinance の MultiIndex 列を「最初に」平坦化（旧版は指標計算の後だった）
- スコア計算を for ループからベクトル演算へ（同じロジック・高速）
- Decision 列を必ず初期化（旧版は先頭行が NaN）
- デバッグ用 print を削除
- RSI は Wilder 平滑化（一般的なチャートツールと同じ値）。旧方式は rsi_method="sma"
- 重み・閾値を引数で変更可能に（バックテストで調整しやすい）
- explain() で「なぜこのスコアになったか」の内訳を返す（ダッシュボード表示用）
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_WEIGHTS = {
    "sma_cross": 1.0,      # SMA5/25 ゴールデン/デッドクロス
    "sma75_side": 0.5,     # 終値が75日線より上/下
    "rsi": 1.0,            # RSI<=30 / >=70
    "macd_cross": 1.0,     # MACD ゴールデン/デッドクロス
    "bb_touch": 1.0,       # ボリンジャー ±2σ 接触
    "engulfing": 1.5,      # 包み線
    "pinbar": 1.5,         # ピンバー
    "three_soldiers": 2.0, # 赤三兵 / 黒三兵
}

DEFAULT_THRESHOLDS = {"strong_buy": 3.5, "buy": 2.0, "sell": -2.0, "strong_sell": -3.5}

DECISIONS = ["STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL"]


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance の出力を Open/High/Low/Close/Volume の単純な列に揃える"""
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        # yfinance 0.2.4x 以降: (Price, Ticker) の2段列
        df.columns = df.columns.get_level_values(0)
    df = df.loc[:, ~df.columns.duplicated()]
    missing = {"Open", "High", "Low", "Close"} - set(df.columns)
    if missing:
        raise ValueError(f"必要な列がありません: {missing}")
    if "Volume" not in df.columns:
        df["Volume"] = np.nan
    df = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
    df = df.dropna(subset=["Close"])
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


class StockAnalyzer:
    def __init__(self, df, weights=None, thresholds=None, rsi_method="wilder"):
        self.df = normalize_ohlcv(df)
        self.w = {**DEFAULT_WEIGHTS, **(weights or {})}
        self.th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        self.rsi_method = rsi_method
        self._signals: dict[str, tuple[pd.Series, float]] = {}

    # ---------------------------------------------------------------- 指標
    def calculate_indicators(self):
        df = self.df
        c = df["Close"]
        df["SMA_5"] = c.rolling(5).mean()
        df["SMA_25"] = c.rolling(25).mean()
        df["SMA_75"] = c.rolling(75).mean()

        delta = c.diff()
        gain, loss = delta.clip(lower=0), -delta.clip(upper=0)
        if self.rsi_method == "sma":
            avg_gain, avg_loss = gain.rolling(14).mean(), loss.rolling(14).mean()
        else:
            avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
            avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - 100 / (1 + rs)
        df["RSI_14"] = rsi.where(avg_loss != 0, 100.0).where(avg_gain.notna())

        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        df["MACD"] = ema12 - ema26
        df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()

        df["BB_SMA"] = c.rolling(20).mean()
        df["BB_STD"] = c.rolling(20).std()
        df["BB_Upper"] = df["BB_SMA"] + 2 * df["BB_STD"]
        df["BB_Lower"] = df["BB_SMA"] - 2 * df["BB_STD"]
        return df

    # ---------------------------------------------------- ローソク足パターン
    def detect_patterns(self):
        df = self.df
        o, h, l, c = df["Open"], df["High"], df["Low"], df["Close"]
        body = (c - o).abs()
        lower_wick = np.minimum(o, c) - l
        upper_wick = h - np.maximum(o, c)

        bull, bear = c > o, o > c
        pbull, pbear = bull.shift(1, fill_value=False), bear.shift(1, fill_value=False)

        df["Bullish_Engulfing"] = pbear & bull & (c >= o.shift(1)) & (o <= c.shift(1))
        df["Bearish_Engulfing"] = pbull & bear & (o >= c.shift(1)) & (c <= o.shift(1))
        df["Bullish_Pinbar"] = (lower_wick >= 2 * body) & (upper_wick <= body) & (body > 0)
        df["Bearish_Pinbar"] = (upper_wick >= 2 * body) & (lower_wick <= body) & (body > 0)
        df["Three_White_Soldiers"] = (
            bull & pbull & bull.shift(2, fill_value=False)
            & (c > c.shift(1)) & (c.shift(1) > c.shift(2))
        )
        df["Three_Black_Crows"] = (
            bear & pbear & bear.shift(2, fill_value=False)
            & (c < c.shift(1)) & (c.shift(1) < c.shift(2))
        )
        return df

    # ---------------------------------------------------------- スコア
    def calculate_score(self):
        df, w = self.df, self.w
        s5, s25, c = df["SMA_5"], df["SMA_25"], df["Close"]
        m, ms = df["MACD"], df["MACD_Signal"]

        bb_low = df["Low"] <= df["BB_Lower"]
        rsi_low = df["RSI_14"] <= 30

        # (シグナル名, 条件, 点数)。旧コードの if/elif の優先順位をそのまま再現
        sig = {
            "SMA GC": ((s5.shift(1) <= s25.shift(1)) & (s5 > s25), +w["sma_cross"]),
            "SMA DC": ((s5.shift(1) >= s25.shift(1)) & (s5 < s25), -w["sma_cross"]),
            "75日線より上": (c > df["SMA_75"], +w["sma75_side"]),
            "75日線より下": (c < df["SMA_75"], -w["sma75_side"]),
            "RSI <= 30": (rsi_low, +w["rsi"]),
            "RSI >= 70": (~rsi_low & (df["RSI_14"] >= 70), -w["rsi"]),
            "MACD GC": ((m.shift(1) <= ms.shift(1)) & (m > ms), +w["macd_cross"]),
            "MACD DC": ((m.shift(1) >= ms.shift(1)) & (m < ms), -w["macd_cross"]),
            "BB -2σ接触": (bb_low, +w["bb_touch"]),
            "BB +2σ接触": (~bb_low & (df["High"] >= df["BB_Upper"]), -w["bb_touch"]),
            "強気の包み線": (df["Bullish_Engulfing"], +w["engulfing"]),
            "弱気の包み線": (df["Bearish_Engulfing"], -w["engulfing"]),
            "強気ピンバー": (df["Bullish_Pinbar"], +w["pinbar"]),
            "弱気ピンバー": (df["Bearish_Pinbar"], -w["pinbar"]),
            "赤三兵": (df["Three_White_Soldiers"], +w["three_soldiers"]),
            "黒三兵": (df["Three_Black_Crows"], -w["three_soldiers"]),
        }
        sig = {k: (cond.fillna(False).astype(bool), pts) for k, (cond, pts) in sig.items()}
        self._signals = sig

        score = sum(cond * pts for cond, pts in sig.values())
        df["Score"] = score.astype(float).round(2)

        # 75日線の位置は「状態」なのでパターン欄には出さない（旧仕様どおり）
        shown = {k: v for k, v in sig.items() if not k.startswith("75日線")}
        flags = pd.DataFrame({k: cond for k, (cond, _) in shown.items()}, index=df.index)
        names = np.array(list(shown.keys()))
        df["Detected_Patterns"] = [", ".join(names[row]) for row in flags.to_numpy()]

        th = self.th
        df["Decision"] = np.select(
            [score >= th["strong_buy"], score >= th["buy"],
             score <= th["strong_sell"], score <= th["sell"]],
            ["STRONG BUY", "BUY", "STRONG SELL", "SELL"],
            default="HOLD",
        )
        return df

    def run_all(self) -> pd.DataFrame:
        self.calculate_indicators()
        self.detect_patterns()
        return self.calculate_score()

    # ---------------------------------------------------------- 内訳
    def explain(self, i: int = -1) -> list[dict]:
        """指定行で点数に寄与したシグナルの一覧 [{label, points}]"""
        if not self._signals:
            self.run_all()
        return [
            {"label": k, "points": pts}
            for k, (cond, pts) in self._signals.items()
            if bool(cond.iloc[i])
        ]
