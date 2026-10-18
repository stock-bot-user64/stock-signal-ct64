"""
ローカル Web アプリ（ダッシュボード＋銘柄の追加・削除）

  python app.py            → ブラウザで http://127.0.0.1:8765 が開きます
  python app.py --port 9000 --no-browser

追加の Python ライブラリは不要（標準ライブラリの http.server を使用）。
自分の PC 内（127.0.0.1）だけで待ち受けるので、外部からはアクセスできません。
"""
from __future__ import annotations

import argparse
import io
import json
import threading
import traceback
import webbrowser
from contextlib import redirect_stderr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

import common
import daily_run
import report

FETCH = daily_run.fetch_prices          # テスト時に差し替え可能
JOB = {"running": False, "log": "", "finished_at": None}
_job_lock = threading.Lock()


def _log(msg: str):
    JOB["log"] = (JOB["log"] + msg + "\n")[-6000:]


def start_job(codes=None, mail=False) -> bool:
    with _job_lock:
        if JOB["running"]:
            return False
        JOB.update(running=True, log="")

    def work():
        try:
            with redirect_stderr(io.StringIO()):
                daily_run.run(codes=codes, mail=mail, sheets=codes is None, log=_log, fetch=FETCH)
            _log("完了しました")
        except Exception as e:
            _log(f"失敗: {e}")
            traceback.print_exc()
        finally:
            JOB.update(running=False, finished_at=common.now_str())

    threading.Thread(target=work, daemon=True).start()
    return True


def lookup_name(code: str) -> str:
    try:
        import yfinance as yf
        info = yf.Ticker(code).info
        return info.get("shortName") or info.get("longName") or ""
    except Exception:
        return ""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # アクセスログを抑制
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _err(self, msg, status=400):
        self._json({"error": msg}, status)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    # ------------------------------------------------------------ GET
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = (common.BASE / "web" / "dashboard.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
        elif self.path == "/api/state":
            self._json(report.state() | {"job": JOB})
        else:
            self._err("not found", 404)

    # ----------------------------------------------------------- POST
    def do_POST(self):
        try:
            data = self._body()
        except json.JSONDecodeError:
            return self._err("JSON が不正です")

        if self.path == "/api/run":
            ok = start_job(codes=None, mail=bool(data.get("mail")))
            return self._json({"started": ok}) if ok else self._err("すでに実行中です", 409)

        if self.path == "/api/tickers":
            code = common.normalize_code(data.get("code", ""))
            if not code:
                return self._err("銘柄コードを入力してください")
            items = common.load_tickers()
            if any(t["code"] == code for t in items):
                return self._err(f"{code} はすでに登録されています")
            try:
                px = FETCH(code, "5d")
            except Exception as e:
                return self._err(f"{code} の株価を取得できませんでした: {e}")
            if px is None or len(px) == 0:
                return self._err(f"{code} の株価データが見つかりません。コードを確認してください")
            name = (data.get("name") or "").strip() or lookup_name(code) or code
            t = {"code": code, "name": name, "enabled": True, "memo": (data.get("memo") or "").strip()}
            common.save_tickers(items + [t])
            # 追加した銘柄だけすぐ判定（メール・シートは送らない）
            try:
                daily_run.run(codes=[code], mail=False, sheets=False, log=lambda *_: None, fetch=FETCH)
            except Exception as e:
                return self._json({"ticker": t, "warning": f"判定に失敗: {e}"})
            return self._json({"ticker": t})

        self._err("not found", 404)

    # ---------------------------------------------------- PATCH/DELETE
    def _code_from_path(self):
        if not self.path.startswith("/api/tickers/"):
            return None
        return unquote(self.path.split("/api/tickers/", 1)[1])

    def do_PATCH(self):
        code = self._code_from_path()
        items = common.load_tickers()
        t = next((x for x in items if x["code"] == code), None)
        if not t:
            return self._err("銘柄が見つかりません", 404)
        data = self._body()
        for k in ("name", "memo"):
            if k in data:
                t[k] = str(data[k]).strip()
        if "enabled" in data:
            t["enabled"] = bool(data["enabled"])
        common.save_tickers(items)
        report.build()
        self._json({"ticker": t})

    def do_DELETE(self):
        code = self._code_from_path()
        items = common.load_tickers()
        rest = [x for x in items if x["code"] != code]
        if len(rest) == len(items):
            return self._err("銘柄が見つかりません", 404)
        common.save_tickers(rest)
        latest = common.load_latest()
        latest["results"] = [r for r in latest.get("results", []) if r["code"] != code]
        common.save_latest(latest)
        report.build()
        self._json({"deleted": code})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    common.load_dotenv()
    url = f"http://127.0.0.1:{a.port}"
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"ダッシュボード: {url}   （終了は Ctrl+C）")
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
