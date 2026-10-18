"""Gmail 通知：シグナルを1通のまとめメール（HTML）で送る。旧版は銘柄ごとに1通ずつ送信していた"""
from __future__ import annotations

import html
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

COLORS = {"STRONG BUY": "#c62828", "BUY": "#e57373", "HOLD": "#757575",
          "SELL": "#64b5f6", "STRONG SELL": "#1565c0"}


def mail_configured() -> bool:
    return all(os.getenv(k) for k in ("GMAIL_USER", "GMAIL_APP_PASSWORD", "TO_EMAIL"))


def build_digest(signals: list[dict], date: str) -> tuple[str, str, str]:
    buys = sum(r["decision"].endswith("BUY") for r in signals)
    sells = len(signals) - buys
    subject = f"【株シグナル {date}】買い{buys}件 / 売り{sells}件"

    text_lines = [f"{date} の判定でシグナルが出た銘柄です。", ""]
    rows = []
    for r in signals:
        pats = r["patterns"] or "なし"
        text_lines.append(f"■ {r['name']} ({r['code']})  {r['decision']}  スコア {r['score']:+.1f}"
                          f"  終値 {r['close']:,.0f}円 ({r['change_pct']:+.2f}%)\n   {pats}")
        c = COLORS.get(r["decision"], "#757575")
        rows.append(
            f"<tr><td style='padding:8px;border-bottom:1px solid #eee'><b>{html.escape(r['name'])}</b>"
            f"<br><span style='color:#888;font-size:12px'>{r['code']}</span></td>"
            f"<td style='padding:8px;border-bottom:1px solid #eee'><span style='background:{c};color:#fff;"
            f"padding:2px 8px;border-radius:10px;font-size:12px'>{r['decision']}</span></td>"
            f"<td style='padding:8px;border-bottom:1px solid #eee;text-align:right'>{r['score']:+.1f}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #eee;text-align:right'>{r['close']:,.0f}<br>"
            f"<span style='font-size:12px;color:{'#c62828' if r['change_pct'] >= 0 else '#1565c0'}'>"
            f"{r['change_pct']:+.2f}%</span></td>"
            f"<td style='padding:8px;border-bottom:1px solid #eee;font-size:12px'>{html.escape(pats)}</td></tr>"
        )
    text_lines += ["", "※ ダッシュボード（output/dashboard.html）で詳細を確認できます。"]
    body_html = (
        f"<div style='font-family:sans-serif'><p>{date} の判定でシグナルが出た銘柄です。</p>"
        "<table style='border-collapse:collapse;font-size:14px'>"
        "<tr style='background:#f5f5f5'><th style='padding:8px;text-align:left'>銘柄</th><th>判定</th>"
        "<th>スコア</th><th>終値</th><th style='text-align:left'>検出パターン</th></tr>"
        + "".join(rows) + "</table><p style='color:#888;font-size:12px'>"
        "テクニカル指標による機械的な判定です。売買は自己判断で行ってください。</p></div>"
    )
    return subject, "\n".join(text_lines), body_html


def send_digest(signals: list[dict], date: str) -> None:
    if not signals:
        return
    subject, text, body_html = build_digest(signals, date)
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, os.environ["GMAIL_USER"], os.environ["TO_EMAIL"]
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
        server.login(os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"])
        server.send_message(msg)
