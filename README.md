# slot-line

`slot-line` は、LINE収集の実機PoCを進めるプロジェクトです。

現在はPIA町田の`text_trigger`と、エムアンドエム溝口の`passive`をWindows canonical RAW schemaへ載せる最小実装を進めています。設計の正は [`DESIGN.md`](DESIGN.md)、実機記録は [`PHASE0.md`](PHASE0.md) です。

## Status

🚧 Phase 1/RAW — `passive`と`text_trigger`を採用方式として固定。rich-card-only返信のRAW保存は実機確認済み。daily runnerのWindows手動実行とTask Scheduler経由の安全なdry-runは確認済み。Task Scheduler本番登録と日次安定運用は未実施。今回のWindows再起動試験は保留。

## Phase 1 runner

Windows運用機で、リポジトリルートから次を1回実行します。標準のtrigger方式はAndroidのLINE URL schemeで、通常運用にWindows版LINEの起動や現在の表示トークは要求しません。

```powershell
python scripts\run_pia_machida.py
```

2店舗をまとめて手動実行する最小runnerは次です。Task Schedulerにはまだ登録しません。

```powershell
python scripts\run_daily.py
```

Task Scheduler登録前の安全な実行環境確認は、次で行います。Adapterを起動せず、Python、ADB、Androidへのread-onlyコマンド、LINE package、RAWディレクトリ書き込みだけを確認します。PIA町田への送信とM&Mの取得は行いません。

```powershell
python scripts\run_daily.py --dry-run
```

summaryにはADB health、各`store_id`のstatus、今回runの`message_count`、保存総数`stored_message_count_total`、`image_count`、errors/warnings、`raw_path`を出力します。

PIA町田は当日すでに正常な`text_trigger` runがある場合、再送せず`skipped_already_successful`になります。当日に送信済みで`triggered_at`があるものの成功していない場合も再送せず、前回情報付きの`skipped_already_attempted`になります。送信前に失敗して`triggered_at`がない場合は通常再実行を妨げません。`skipped_already_attempted`は取得成功に変換せず、daily summaryは`partial_failure`を維持します。明示的に再送する場合だけ次を指定します。

```powershell
python scripts\run_daily.py --force-trigger
```

処理は、WindowsからADBで `https://line.me/R/oaMessage/%40030pwlwx/?%E6%9C%80%E6%96%B0%E6%83%85%E5%A0%B1` をAndroidへ開き、UI階層で `PIA町田` と入力欄の `最新情報` を完全一致確認してから送信します。対象確認できない場合は送信せず終了します。返信は `uiautomator` で検知し、LINE標準のダウンロード操作、`adb pull`、SHA-256/byte size記録までを行います。

旧方式のWindows UI Automation送信は、明示的に `--trigger-mode windows-uia` を指定した場合だけdebug/fallbackとして使用します。現在開いているWindowsトークへの盲目的送信は本番方式ではありません。

RAWは `data/raw/YYYY-MM-DD/<store_id>/` に保存されます。`manifest.json` は実行単位でupsertし、同一SHA-256の画像は再保存しません。実行時に作るTask Schedulerタスクは一時的な対話セッション用で、終了時に削除します。

保存形式は全店舗で次に固定します。

```text
data/raw/YYYY-MM-DD/<store_id>/
  manifest.json
  messages.json
  images/
  ui/
```

通常配信型A「エムアンドエム溝口」はtriggerを送らず、既存受信メッセージをAndroid UI階層から取得します。

```powershell
python scripts\run_m_and_m_mizoguchi.py
```

画像はWindows側でSHA-256を確認してから保存し、同じSHA-256は既存ファイルを再利用します。Windowsへのpull、ハッシュ確認、manifest保存が完了した後だけAndroid一時画像を削除し、削除失敗は`cleanup_warning`として記録します。

通常のAndroid操作に人間フォールバックはありません。ADB接続、セキュアロック、LINEの構造取得、送信、返信待ち、画像保存、pullの失敗はマニフェストに状態を記録して終了します。

### Task Scheduler本番定義案（未登録）

- task名: `SlotLineDaily`
- 実行時刻: 毎日21:05（PIA町田の21時台更新を第一候補。返信可能時刻の完全な境界は未確定）
- command: `C:\Users\Eita Ideguchi\AppData\Local\Programs\Python\Python312\python.exe <REPO_ROOT>\scripts\run_daily.py --repo-root <REPO_ROOT>`
- working directory: `<REPO_ROOT>`
- timeout: 15分
- 重複起動: `IgnoreNew`（前回実行中は新規起動しない）
- PCがスリープ中: 起床させず、その回は実行しない
- missed start: 自動追実行しない。次回定刻または明示的な手動実行で確認する
- ログ保存先: `<REPO_ROOT>\data\logs\run_daily_YYYY-MM-DD.log` と `.err.log`

本番タスクはまだ登録しません。`<REPO_ROOT>`はWindows上の実配置を確定後に置換します。

2026-09-21の実機確認では、ADB論理再接続、LINE強制終了後のADB起動、画面OFF後のADB復帰、物理USB再接続が成立しました。Windows再起動はユーザーによるWindows再起動後に復帰確認、Android本体再起動はキーガード解除後に復帰確認となり、完全無人復旧は未成立です。画面ロック方式やセキュリティ設定は変更していません。

## Repository

- Default branch: `main`
- Issueや設計、使い方は今後ここに整理します
