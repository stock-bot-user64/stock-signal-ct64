# スマホ版のセットアップ（GitHub で自動実行）

GitHub のサーバーが平日 9:20・12:00・14:20 に自動で判定し、スマホ用のページを更新します。PC の電源は不要です。
メール通知はありません（スマホで確認する前提）。
所要時間は約15分で、費用はかかりません。

```
平日 9:20 / 12:00 / 14:20 ──▶ GitHub Actions が daily_run.py を実行
                 ├─ 履歴を data/ に保存
                 └─ スマホ用ページを公開 ──▶ https://ユーザー名.github.io/stock-signal/
```

## 1. リポジトリを作る
1. https://github.com でアカウントを作成（持っていれば不要）
2. 右上「＋」→「New repository」
   - Repository name: `stock-signal`
   - **Public** を選択（無料プランで Pages を使うため）
   - 「Create repository」
3. 表示された画面の「uploading an existing file」を押す
4. PC の `stock_signal` フォルダの**中身**をまとめてドラッグ＆ドロップ
   - ⚠ **`credentials.json` と `.env` は絶対に入れない**（公開されてしまいます）
   - PC で使っていた `data/history.csv` を入れると、これまでの履歴も引き継げます
5. 下の「Commit changes」

> `.github` フォルダがアップロードされなかった場合は、「Add file」→「Create new file」で
> ファイル名に `.github/workflows/daily.yml` と入力し、同名ファイルの中身を貼り付けて保存してください。

## 2. 公開と秘密情報の設定
リポジトリの「Settings」タブで:

1. 左メニュー「Pages」→ Source を **「GitHub Actions」** に変更
2. 左メニュー「Secrets and variables」→「Actions」→「New repository secret」で以下を登録

| Name | 値 | 必須 |
|---|---|---|
| `SPREADSHEET_KEY` | スプレッドシートの ID | シートを使うなら |
| `GCP_SA_JSON` | `credentials.json` の中身をすべて貼り付け | シートを使うなら |

Secrets は暗号化され、公開リポジトリでも他人からは見えません。

## 3. 初回実行
1. 「Actions」タブ →（確認が出たら）「I understand my workflows, go ahead and enable them」
2. 左の「daily」→ 右の「Run workflow」→ 緑の「Run workflow」
3. 2〜3分で緑のチェックが付けば完了。「Settings」→「Pages」にページの URL が表示されます

## 4. スマホのホーム画面に追加（Android）
1. Chrome でページの URL を開く
2. 右上「⋮」→「ホーム画面に追加」（または「アプリをインストール」）
3. ホーム画面のアイコンから、アプリのように起動できます。電波がないときは前回の結果を表示します

## 5. スマホから銘柄管理・売買記録をする（任意）
スマホ画面から「銘柄の追加・削除」「今すぐ判定」「自分の売買記録」を使うための設定です。

### 5-1. 売買記録用の非公開リポジトリを作る
1. 右上「＋」→「New repository」
2. Repository name: `stock-private`、**Private** を選択、「Add a README file」にチェック →「Create repository」

売買記録（`trades.json`）はここに保存され、自分以外は見られません。

### 5-2. アクセストークンを作る
1. GitHub 右上のアイコン →「Settings」→ 左下「Developer settings」→「Personal access tokens」→「**Fine-grained tokens**」→「Generate new token」
2. 次のように設定
   - Token name: `stock-phone`（何でもよい）
   - Expiration: 長めに（期限が切れたら作り直してスマホの設定に入れ直します）
   - Repository access: **Only select repositories** → `stock-signal` と `stock-private` を選ぶ
   - Permissions → Repository permissions:
     - **Contents: Read and write**（銘柄リストと売買記録の保存）
     - **Actions: Read and write**（「今すぐ判定」ボタン）
3. 「Generate token」→ 表示された `github_pat_…` をコピー（この画面でしか見られません）

### 5-3. スマホに登録する
1. スマホ版の右上の歯車 →「アクセストークン」に貼り付け
2. ユーザー名・リポジトリ名は自動で入っています。違っていれば直す
3. 「保存して接続を確認」→「接続できました」と出れば完了
4. 同じ画面で、月の目標利益・利益確定の目安・損切りの目安を設定できます

トークンはそのスマホのブラウザにだけ保存されます。スマホを無くしたときは、GitHub の同じ画面でトークンを削除（Delete）してください。

## 機能の使い方
- **銘柄の追加・削除**（今日タブの下）: コードを入れて「追加する」。チェックを外すと一時停止。2〜3分後の再判定で一覧に出ます
- **保有タブ**: 「＋ 買いを記録」で記録。保有中の銘柄の含み損益と、次の目安を表示します
  - 利確の目安・損切りの目安に達した / 売りシグナルが出た / 予定の保有日数を過ぎた
  - 銘柄を押すと「売却を記録」。売ると今月の確定利益と目標の進み具合に反映されます
- **成績タブ → 紙上トレード**: 判定のたびに、ルールどおり売買したと仮定して自動で記録します（実際の注文はしません）
  - ルールは `config/settings.json` の `paper_rules` で変更・追加できます
    （`threshold`=買うスコア、`hold_days`=保有する営業日数、`shares`=株数）
  - 場中の株価で売買したものとして記録します。実際に注文するときの条件に近い形です
- **成績タブ → バックテスト**: 毎週土曜10時に今年の分を自動で更新します


## 注意
- **場中の判定は暫定**: 3回とも取引時間中なので、その日のローソク足は未確定です（株価も約20分遅れ）。
  画面に「場中・暫定」と表示されます。履歴にはその日最後（14:20）の判定が残ります
- 更新時刻は `.github/workflows/daily.yml` の `cron:` 行で変えられます（UTC＝日本時間−9時間で書く）
- **自動実行が失敗したとき**: GitHub から失敗通知のメールが届き、スマホ版には警告が表示されます。
  よくある原因は、Yahoo Finance が GitHub のサーバーからのアクセスを一時的に制限することです。
  多くは翌日に回復します。続く場合は「Run workflow」で手動実行してください
- GitHub の混雑により、実行が数分〜数十分遅れることがあります（特に 12:00 ちょうど）
- 公開リポジトリとページは、URL を知っている人なら監視銘柄・判定結果・紙上トレードを見られます。
  自分の売買記録は非公開リポジトリにだけ保存され、ページには載りません
- PC 版で使う場合、スプレッドシート ID は `.env` の `SPREADSHEET_KEY` に書いてください
  （公開リポジトリに載らないよう、`config/settings.json` からは外しました）
