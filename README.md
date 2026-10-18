# 日本株シグナル v2

テクニカル指標で毎日の売買シグナルを判定し、HTMLダッシュボードで確認・銘柄管理できるツールです。

## ファイル構成

| ファイル | 役割 | 旧ファイル |
|---|---|---|
| `analyzer.py` | 指標計算・パターン検出・スコア（ロジックは旧版と同一） | StockAnalyzer.py |
| `daily_run.py` | 毎日の判定バッチ（履歴保存・シート・メール・HTML生成） | Stockmain.py / StockmainV1.py / Gmail2MeSA.py |
| `app.py` | **ローカルWebアプリ**（ダッシュボード＋銘柄の追加・削除） | なし（新規） |
| `report.py` | 結果を埋め込んだ1ファイル完結の `output/dashboard.html` を生成 | なし（新規） |
| `backtest.py` | バックテスト（結果はダッシュボードに表示） | backtest_SAv1 / SAv0 / SA2sheet / main_backtest |
| `notify.py` / `sheets.py` | Gmail まとめ通知 / スプレッドシート追記 | Gmail2MeSA.py の一部 |
| `config/tickers.json` | **銘柄リスト（ここ1か所だけ）** | 各ファイルに直書き |
| `config/settings.json` | 通知対象など（スプレッドシートIDは `.env` の SPREADSHEET_KEY） | 直書き |
| `mobile.py` / `web/mobile/` | スマホ版ページの生成 / 本体（銘柄管理・売買記録・紙上トレード） | なし（新規） |
| `paper.py` | 紙上トレードの自動記録（data/paper.json） | なし（新規） |
| `.github/workflows/daily.yml` | GitHub での自動実行 | なし（新規） |
| `data/` | history.csv（全履歴）、latest.json、backtest_summary.csv | |

## セットアップ

```bash
pip install -r requirements.txt
cp .env.example .env        # Gmail の設定を記入
# credentials.json（サービスアカウント鍵）をこのフォルダに置く
```

## 使い方

### 1. ダッシュボードで見る・銘柄を管理する
```bash
python app.py
```
ブラウザで http://127.0.0.1:8765 が開きます。
- **銘柄の追加・削除** … 4桁コードを入れるだけ（`.T` は自動付与、全角数字もOK）。株価が取れるか確認してからすぐ判定します。チェックを外すと削除せずに一時停止。
- **今すぐ判定** … 全銘柄を判定（メールを送るか選べます）
- 銘柄の行をクリック → ローソク足チャート（25/75日線・ボリンジャー帯・過去のシグナル▲▼）、日々のスコア、**スコアの内訳**、その銘柄のバックテスト勝率

### 2. 毎日の自動実行
```bash
python daily_run.py          # 判定 → 履歴 → シート → メール → output/dashboard.html
```
東証の大引け(15:30)後、**16:00以降**に実行してください（場中だと未確定の足で判定されます）。
Windows はタスクスケジューラ、Mac/Linux は cron で平日 16:30 などに登録。
`output/dashboard.html` はダブルクリックで開ける閲覧専用版です（スマホに送っても見られます）。

### 3. バックテスト
```bash
python backtest.py --year 2026             # 2026年のシグナルだけで検証
python backtest.py --year 2026 --cost 0.1  # 往復0.1%のコストを差し引く
python backtest.py --shares 200            # 1回200株で損益を計算（既定100株）
python backtest.py --overlap               # 旧版と同じ集計方法（重複あり）
```
画面に「条件別の勝率・総損益・PF・最大ドローダウン・必要資金」「銘柄別の損益上位」「月別損益」を表示し、
`data/` に backtest_summary.csv（銘柄×条件）、backtest_by_rule.csv（条件別）、backtest_monthly.csv（月別）、
backtest_trades_details.csv（明細）を保存します。損益はダッシュボードの各銘柄にも表示されます。


### 4. スマホで見る（Android）
GitHub で毎日自動実行し、スマホ用ページに公開できます。手順は **SETUP_MOBILE.md** を参照。
手元で確認するときは `python mobile.py` → `python -m http.server -d site 8000` → http://localhost:8000

## 旧版から修正した不具合

1. **毎日の判定で75日線が使われていなかった** — `period="100d"` は約68営業日なので SMA_75 が常に NaN になり、±0.5 点が一度も加算されていなかった。バックテスト（長期間データ）とは採点が食い違っていた → 2年分を取得するよう修正。
2. **MultiIndex 列の平坦化が指標計算の後だった** — yfinance の新しい版では列が2段になるため、指標計算時点で列構造が崩れる可能性があった → 最初に平坦化。
3. **Decision 列が未初期化**（先頭行が NaN）、デバッグ用 print の残り → 修正。
4. **同じ日に2回実行すると行が重複**、`END` マーカーで表が汚れる → (日付, 銘柄) で上書き保存。END は廃止。
5. **1銘柄ごとに Google 認証を3回**行っていた → 1回の実行で認証1回・書き込み1回。
6. **銘柄リストが3ファイルに散在** → `config/tickers.json` に一元化。
7. **メールが銘柄ごとに1通** → 1日1通のまとめメール（HTML表）。
8. `backtest_SAv0.py` は import しただけでバックテストが走っていた。
9. バックテスト（SAv1）は連日のシグナルを別トレードとして重複カウントしており、勝率が過大に出やすかった → 既定で重複なし。

## 変更した仕様（意図的）

- RSI を一般的なチャートツールと同じ **Wilder 方式**に変更（旧方式は `StockAnalyzer(df, rsi_method="sma")`）。
- 株価は配当調整なしの実際の終値（`auto_adjust=False`）。
- スプレッドシートは新しいシート「Daily」（見出し付き）に追記。旧 sheet1 は変更しません。シート名は settings.json で変更可。

## セキュリティ

`credentials.json` と `.env` は秘密情報です。`.gitignore` 済みですが、GitHub 等に一度でも上げた場合は Google Cloud コンソールで鍵を削除し、新しい鍵を発行してください。
